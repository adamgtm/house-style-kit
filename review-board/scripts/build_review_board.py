#!/usr/bin/env python3
"""Build a review board from a review.json.

    build_review_board.py review.json [--out DIR] [--force] [--wait [--inbox DIR]] [--serve [--wait] [--port N]] [--open]

Writes board.html (data embedded), board.css, board.js, board-meta.json and
_thumbs/ into DIR (default: review-board-<manifest name>/ beside review.json).
board.html opens straight from disk: that is file mode, the default. Send in
the page downloads a review-feedback__*.json file.
  --wait   watch --inbox (default ~/Downloads) for this board's download, file it
           under feedback/ beside review.json, print the Markdown and exit 0.
  --serve  instead run the local server on 127.0.0.1 (add --wait to exit after
           the first send).
  --open   open board.html (or the served URL) in the browser.
  --force  build into a folder that holds a different board.

review.json (paths are relative to the file):
  {"id": "round-4", "title": "Round 4 review", "instruction": "...",
   "sections": [{"name": "Intro", "items": [{"id": "x", "title": "X",
     "versions": [{"id": "x-a", "label": "A", "src": "x/a.png", "note": "...",
                   "recommended": true, "info": {"file": "...", "sources": ["..."]}}]}]}]}

Standard library plus Pillow.
"""
import argparse
import hashlib
import html
import json
import os
import re
import shutil
import string
import sys
import webbrowser
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
sys.path.insert(0, str(HERE))
import review_server  # noqa: E402

THUMB_W = 360
DEFAULT_OUT_PREFIX = "review-board-"
THUMB_QUALITY = 74
PAPER = (250, 248, 243)


class BoardError(Exception):
    def __init__(self, problems):
        super().__init__("\n".join(problems))
        self.problems = problems


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "board"


def default_label(i):
    letters = string.ascii_uppercase
    return letters[i] if i < len(letters) else str(i + 1)


def validate(raw, base):
    """Return (normalized board, problems). Reports every problem, not just the first."""
    problems = []
    if not isinstance(raw, dict):
        return None, ["review.json must be a JSON object"]
    title = str(raw.get("title") or "Review")
    board = {"id": str(raw.get("id") or slug(title)), "title": title,
             "instruction": str(raw.get("instruction") or "Pick the versions you like. Leave a note on each."),
             "sections": []}
    sections = raw.get("sections")
    if not isinstance(sections, list) or not sections:
        return None, ["review.json needs a non-empty sections list"]
    item_ids, version_ids = {}, {}
    for si, sec in enumerate(sections):
        where_s = "sections[%d]" % si
        if not isinstance(sec, dict):
            problems.append("%s must be an object" % where_s)
            continue
        out_s = {"name": str(sec.get("name") or "Section %d" % (si + 1)), "items": []}
        items = sec.get("items")
        if not isinstance(items, list) or not items:
            problems.append("%s (%s) has no items" % (where_s, out_s["name"]))
            items = []
        for ii, it in enumerate(items):
            where_i = "%s.items[%d]" % (where_s, ii)
            if not isinstance(it, dict) or not it.get("id"):
                problems.append("%s needs an id" % where_i)
                continue
            iid = str(it["id"])
            if iid in item_ids:
                problems.append("duplicate item id %r (also at %s)" % (iid, item_ids[iid]))
            item_ids[iid] = where_i
            out_i = {"id": iid, "title": str(it.get("title") or iid), "versions": []}
            versions = it.get("versions")
            if not isinstance(versions, list) or not versions:
                problems.append("item %r needs at least one version" % iid)
                versions = []
            for vi, v in enumerate(versions):
                where_v = "item %r version[%d]" % (iid, vi)
                if not isinstance(v, dict) or not v.get("id"):
                    problems.append("%s needs an id" % where_v)
                    continue
                vid = str(v["id"])
                if vid in version_ids:
                    problems.append("duplicate version id %r (also in item %r)" % (vid, version_ids[vid]))
                version_ids[vid] = iid
                src = v.get("src")
                if not src or not isinstance(src, str):
                    problems.append("version %r has no src" % vid)
                    continue
                path = (base / src)
                if not path.is_file():
                    problems.append("version %r: image not found: %s" % (vid, src))
                    continue
                info = v.get("info") if isinstance(v.get("info"), dict) else {}
                out_i["versions"].append({
                    "id": vid, "label": str(v.get("label") or default_label(vi)),
                    "note": str(v.get("note") or ""), "recommended": bool(v.get("recommended")),
                    "info": info, "_path": path})
            out_s["items"].append(out_i)
        board["sections"].append(out_s)
    return (None if problems else board), problems


def make_thumb(src, dest):
    """Write a small JPEG. Returns (width, height) of the original, or None for formats Pillow can't open."""
    from PIL import Image
    try:
        with Image.open(src) as im:
            im.load()
            w, h = im.size
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, PAPER)
                bg.paste(im, mask=im.getchannel("A"))
                im = bg
            else:
                im = im.convert("RGB")
            if w > THUMB_W:
                im = im.resize((THUMB_W, max(1, round(h * THUMB_W / w))), Image.LANCZOS)
            im.save(dest, "JPEG", quality=THUMB_QUALITY, optimize=True, progressive=True)
            return w, h
    except Exception as e:  # unreadable or unsupported image
        raise BoardError(["cannot make a thumbnail for %s: %s" % (src, e)])


def revision_of(review_bytes, paths):
    h = hashlib.sha256(review_bytes)
    for p in paths:
        st = os.stat(p)
        h.update(("|%d|%d" % (st.st_size, st.st_mtime_ns)).encode())
    return h.hexdigest()[:12]


def build(review_path, out_dir=None, force=False):
    review_path = Path(review_path).resolve()
    if not review_path.is_file():
        raise BoardError(["review.json not found: %s" % review_path])
    base = review_path.parent
    try:
        review_bytes = review_path.read_bytes()
        raw = json.loads(review_bytes.decode("utf-8"))
    except ValueError as e:
        raise BoardError(["review.json is not valid JSON: %s" % e])
    board, problems = validate(raw, base)
    if problems:
        raise BoardError(problems)

    out = Path(out_dir).resolve() if out_dir else base / (DEFAULT_OUT_PREFIX + slug(review_path.stem))
    old_meta = out / review_server.META_NAME
    if old_meta.is_file() and not force:
        try:
            old_id = json.loads(old_meta.read_text(encoding="utf-8")).get("board_id")
        except ValueError:
            old_id = None
        if old_id is not None and old_id != board["id"]:
            raise BoardError(["%s already holds board %r, not %r. Pick another --out, or pass --force to replace it."
                              % (out, old_id, board["id"])])
    thumbs = out / "_thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)

    flat = [v for s in board["sections"] for it in s["items"] for v in it["versions"]]
    revision = revision_of(review_bytes, [v["_path"] for v in flat])
    thumb_names, images = [], {}
    meta_items = []
    for s in board["sections"]:
        for it in s["items"]:
            meta_items.append({"id": it["id"], "title": it["title"], "section": s["name"],
                               "versions": {v["id"]: v["label"] for v in it["versions"]}})
    for v in flat:
        src = v["_path"]
        real = str(src.resolve())
        fp = review_server.fingerprint(real)
        name = fp + ".jpg"
        dest = thumbs / name
        if not dest.exists() or dest.stat().st_size == 0:
            w, h = make_thumb(src, dest)
        else:
            from PIL import Image
            with Image.open(src) as im:
                w, h = im.size
        v.update(fp=fp, thumb="_thumbs/" + name, w=w, h=h,
                 file_src=quote(os.path.relpath(real, out).replace(os.sep, "/"), safe="/.-_~"))
        if name not in thumb_names:
            thumb_names.append(name)
        images[fp] = real
    for stale in thumbs.iterdir():
        if stale.name not in set(thumb_names):
            stale.unlink()

    path_key = hashlib.sha1(str(review_path).encode()).hexdigest()[:10]
    data = {"id": board["id"], "title": board["title"], "instruction": board["instruction"],
            "revision": revision, "pathKey": path_key,
            "sections": [{"name": s["name"], "items": [{
                "id": it["id"], "title": it["title"],
                "versions": [{"id": v["id"], "label": v["label"], "note": v["note"],
                              "recommended": v["recommended"], "info": v["info"], "fp": v["fp"],
                              "thumb": v["thumb"], "src": v["file_src"], "w": v["w"], "h": v["h"]}
                             for v in it["versions"]]} for it in s["items"]]} for s in board["sections"]]}
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    page = (ASSETS / "board.html").read_text(encoding="utf-8")
    page = (page.replace("{{TITLE}}", html.escape(board["title"]))
                .replace("{{REVISION}}", revision).replace("{{DATA}}", blob))
    (out / "board.html").write_text(page, encoding="utf-8")
    for name in ("board.css", "board.js"):
        shutil.copyfile(ASSETS / name, out / name)
    meta = {"board_id": board["id"], "title": board["title"], "revision": revision,
            "review_json": str(review_path), "feedback_dir": str(base / "feedback"),
            "items": meta_items, "thumbs": thumb_names, "images": images}
    review_server.atomic_write(out / "board-rev.js", "window.__RB_REV=%s;\n" % json.dumps(revision))
    review_server.atomic_write(out / review_server.META_NAME, json.dumps(meta, indent=1))
    return out, meta, len(meta_items), len(flat)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a review board from a review.json.")
    ap.add_argument("review_json")
    ap.add_argument("--out", help="output folder (default: review-board-<manifest name>/ beside review.json)")
    ap.add_argument("--force", action="store_true", help="build into a folder that holds a different board")
    ap.add_argument("--serve", action="store_true", help="serve the board on 127.0.0.1 instead of file mode")
    ap.add_argument("--wait", action="store_true", help="wait for the first send, then print it and exit 0")
    ap.add_argument("--inbox", help="file mode: folder Send downloads to (default ~/Downloads)")
    ap.add_argument("--poll", type=float, default=1.0, help=argparse.SUPPRESS)
    ap.add_argument("--port", type=int)
    ap.add_argument("--open", action="store_true", dest="open_browser", help="open the board in the browser")
    a = ap.parse_args(argv)
    try:
        out, meta, n_items, n_versions = build(a.review_json, a.out, a.force)
    except BoardError as e:
        print("Cannot build the board:", file=sys.stderr)
        for p in e.problems:
            print("  - " + p, file=sys.stderr)
        return 2
    print("Built %d items, %d versions -> %s (revision %s)" % (n_items, n_versions, out / "board.html", meta["revision"]), flush=True)
    if a.serve:
        return review_server.serve(out, wait=a.wait, port=a.port, open_browser=a.open_browser)
    if a.wait:
        return review_server.wait_for_file(out, a.inbox, a.poll, a.open_browser)
    print("Review board ready: %s" % (out / "board.html"), flush=True)
    if a.open_browser:
        review_server.open_path(out / "board.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
