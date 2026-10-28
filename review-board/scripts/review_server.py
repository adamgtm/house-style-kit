#!/usr/bin/env python3
"""Local server for a review board. Standard library only.

    review_server.py BOARD_DIR [--wait] [--port N] [--open]        (localhost server)
    review_server.py BOARD_DIR --inbox DIR --wait [--open]         (file mode; build_review_board.py --wait does this)

BOARD_DIR is the folder build_review_board.py wrote (it holds board-meta.json).

Server mode binds 127.0.0.1 only, serves an allowlist of files, and accepts one
kind of write: POST /api/feedback. Each accepted send is written to
feedback/<UTC timestamp>.json (canonical, atomic) and a derived .md beside
review.json. With --wait the first accepted send is acknowledged and the
process exits 0 after printing the Markdown, so a background job's exit is the
signal that feedback has arrived.

File mode (the default way to review) needs no server: the board is a plain
board.html. Send downloads review-feedback__<board>__<revision>__<id>.json and
the watcher here picks it up from the inbox (default ~/Downloads), validates it
the same way the server does, files it beside review.json, prints the Markdown
and exits 0.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sys
import threading
import shutil
import subprocess
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOST = "127.0.0.1"
MAX_BODY = 1024 * 1024
MAX_NOTE = 20000
REQUEST_TIMEOUT = 10
META_NAME = "board-meta.json"
TOKEN_PLACEHOLDER = "__RB_TOKEN__"
PORT_BASE, PORT_SPAN = 8700, 100

CSP = ("default-src 'self'; img-src 'self' data: blob:; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")

TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"}


def preferred_port(board_id):
    h = int(hashlib.sha1(str(board_id).encode("utf-8")).hexdigest()[:8], 16)
    return PORT_BASE + h % PORT_SPAN


def load_meta(board_dir):
    return json.loads((Path(board_dir) / META_NAME).read_text(encoding="utf-8"))


# ---------- feedback documents ----------

def canonical_feedback(meta, payload, sent_at):
    """Validate a page payload against the board and return the canonical document.
    Only items with a like or a note are kept, in board order. Raises ValueError."""
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    sent = payload.get("items")
    if not isinstance(sent, list):
        raise ValueError("items must be a list")
    known = {it["id"]: it for it in meta["items"]}
    by_id = {}
    for entry in sent:
        eid = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(eid, str) or eid not in known:
            raise ValueError("unknown item id: %r" % (eid if isinstance(entry, dict) else entry))
        item = known[eid]
        liked = entry.get("liked") or []
        if (not isinstance(liked, list)
                or any(not isinstance(v, str) or v not in item["versions"] for v in liked)):
            raise ValueError("unknown version id for item %s" % item["id"])
        note = entry.get("note") or ""
        if not isinstance(note, str):
            raise ValueError("note must be text")
        if len(note) > MAX_NOTE:
            raise ValueError("note too long for item %s" % item["id"])
        order = list(item["versions"])
        liked = sorted(set(liked), key=order.index)
        if liked or note.strip():
            by_id[item["id"]] = {"id": item["id"], "title": item["title"], "liked": liked, "note": note}
    if not by_id:
        raise ValueError("nothing to send: no likes or notes")
    items = [by_id[it["id"]] for it in meta["items"] if it["id"] in by_id]
    sid = payload.get("submission_id")
    return {"board": meta["board_id"], "revision": meta["revision"],
            "submission_id": sid if isinstance(sid, str) else None, "sent_at": sent_at, "items": items}


def render_markdown(meta, doc):
    known = {it["id"]: it for it in meta["items"]}
    lines = ["# %s: feedback" % meta["title"], "",
             "Board `%s`. Sent %s." % (meta["board_id"], doc["sent_at"]), ""]
    section = None
    for entry in doc["items"]:
        it = known[entry["id"]]
        if it["section"] != section:
            section = it["section"]
            lines += ["## " + section, ""]
        lines += ["### " + entry["title"], ""]
        if entry["liked"]:
            liked = ", ".join("%s (`%s`)" % (it["versions"][v], v) for v in entry["liked"])
            lines += ["Liked: " + liked, ""]
        else:
            lines += ["Liked: none", ""]
        if entry["note"].strip():
            lines += ["Note:", ""] + ["> " + ln if ln else ">" for ln in entry["note"].rstrip("\n").split("\n")] + [""]
    skipped = len(meta["items"]) - len(doc["items"])
    lines.append("%d of %d items had no like or note." % (skipped, len(meta["items"])))
    return "\n".join(lines) + "\n"


def atomic_write(path, text):
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def safe_name(text):
    """File-name-safe form of an id. The page's JavaScript uses the same rule."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text))


def fingerprint(path):
    """Content fingerprint of an image file: sha1(realpath, size, mtime_ns). Names its thumb and URL."""
    real = os.path.realpath(path)
    st = os.stat(real)
    return hashlib.sha1(("%s|%d|%d" % (real, st.st_size, st.st_mtime_ns)).encode("utf-8")).hexdigest()[:16]


def link_exclusive(tmp, final):
    """Publish tmp as final, failing with FileExistsError if final already exists."""
    os.link(tmp, final)


def write_feedback(meta, doc):
    """Write feedback/<UTC ts>__<submission id>.md then .json.

    Each file is created exclusively (temp file, then os.link, which fails if the target
    exists), so two processes can never overwrite each other's accepted feedback. The
    Markdown goes first; if the JSON cannot be written the Markdown is removed, so a retry
    never leaves two JSON files for one send."""
    fdir = Path(meta["feedback_dir"])
    fdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.strptime(doc["sent_at"], "%Y-%m-%dT%H:%M:%SZ").strftime("%Y%m%dT%H%M%SZ")
    ident = stamp + "__" + (safe_name(doc.get("submission_id") or "nosid")[:60] or "nosid")
    md = render_markdown(meta, doc)
    js = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    for n in range(1, 1000):
        base = ident if n == 1 else "%s-%d" % (ident, n)
        jpath, mpath = fdir / (base + ".json"), fdir / (base + ".md")
        tmps = []
        made_md = False
        try:
            for text, final in ((md, mpath), (js, jpath)):
                tmp = final.with_name(".%s.%d.%d.tmp" % (final.name, os.getpid(), threading.get_ident()))
                tmps.append(tmp)
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(text)
                    f.flush()
                    os.fsync(f.fileno())
                try:
                    link_exclusive(tmp, final)
                except FileExistsError:
                    if made_md:
                        try:
                            mpath.unlink()
                        except OSError:
                            pass
                    raise
                made_md = True
            return jpath, mpath, md
        except FileExistsError:
            continue  # this identity is taken by another process: try the next suffix
        except BaseException:
            if made_md:
                try:
                    mpath.unlink()
                except OSError:
                    pass
            raise
        finally:
            for t in tmps:
                try:
                    t.unlink()
                except OSError:
                    pass
    raise OSError("could not reserve a feedback file name")


# ---------- server ----------

class BoardChanged(Exception):
    pass


class Board:
    """Shared state for one run."""

    def __init__(self, board_dir, wait, port):
        self.dir = Path(board_dir).resolve()
        self.wait = wait
        self.port = port
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.seen = {}
        self.first_send = threading.Event()
        self.acked = threading.Event()
        self.last = None
        self.hosts = {"%s:%d" % (HOST, port), "localhost:%d" % port}
        self.origins = {"http://" + h for h in self.hosts}
        self.bound = load_meta(self.dir)  # the board and revision this run started with

    def meta(self):
        """The bound board's metadata. Raises BoardChanged if the folder now holds another build."""
        disk = load_meta(self.dir)
        if disk.get("board_id") != self.bound["board_id"]:
            raise BoardChanged("Another board (%s) was built in this folder. This server only serves %s."
                               % (disk.get("board_id"), self.bound["board_id"]))
        if disk.get("revision") != self.bound["revision"]:
            raise BoardChanged("This board was rebuilt. Restart the review to use the new version.")
        return self.bound

    def resolve(self, url_path):
        """Map a URL path to a real file, or None. Checked after symlinks resolve."""
        meta = self.meta()
        if url_path in ("/", "/board.html"):
            name = "board.html"
        elif url_path in ("/board.css", "/board.js"):
            name = url_path[1:]
        elif url_path.startswith("/_thumbs/") and "/" not in url_path[len("/_thumbs/"):]:
            name = url_path[1:]
            if name[len("_thumbs/"):] not in meta.get("thumbs", []):
                return None
        elif url_path.startswith("/img/"):
            allowed = meta.get("images", {})
            key = url_path[len("/img/"):]
            real = allowed.get(key)
            if not real:
                return None
            try:
                cand = Path(real).resolve(strict=True)
                same = str(cand) == real and cand.is_file() and fingerprint(cand) == key
            except OSError:
                return None
            return cand if same else None
        else:
            return None
        try:
            cand = (self.dir / name).resolve(strict=True)
        except OSError:
            return None
        if self.dir not in cand.parents or not cand.is_file():
            return None
        return cand


class Handler(BaseHTTPRequestHandler):
    server_version = "ReviewBoard/1"
    protocol_version = "HTTP/1.0"
    timeout = REQUEST_TIMEOUT

    @property
    def board(self):
        return self.server.board

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Connection", "close")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.wfile.flush()

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode("utf-8"), extra={"Cache-Control": "no-store"})

    def _host_ok(self):
        if self.headers.get("Host", "") not in self.board.hosts:
            self._json(403, {"error": "bad host"})
            return False
        return True

    def _guard(self, fn):
        """Run a handler; any unexpected error becomes a 500 JSON reply, never a dropped connection."""
        try:
            fn()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except BoardChanged as e:
            try:
                self._json(409, {"error": str(e)})
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001 - the catch-all is the point
            try:
                self._json(500, {"error": "internal error: %s" % type(e).__name__})
            except Exception:  # noqa: BLE001
                pass

    def do_HEAD(self):
        self._guard(self._get)

    def do_GET(self):
        self._guard(self._get)

    def do_POST(self):
        self._guard(self._post)

    def _get(self):
        if not self._host_ok():
            return
        parts = urlsplit(self.path)
        real = self.board.resolve(parts.path)
        if real is None:
            return self._json(404, {"error": "not found"})
        data = real.read_bytes()
        if real.name == "board.html":
            data = data.replace(TOKEN_PLACEHOLDER.encode(), self.board.token.encode())
            cache = "no-store"
        else:
            cache = "no-store" if real.suffix in (".css", ".js") else "private, max-age=3600"
        self._send(200, data, TYPES.get(real.suffix.lower(), "application/octet-stream"), {"Cache-Control": cache})

    def _post(self):
        b = self.board
        if not self._host_ok():
            return
        if urlsplit(self.path).path != "/api/feedback":
            return self._json(404, {"error": "not found"})
        if self.headers.get("Origin", "") not in b.origins:
            return self._json(403, {"error": "bad origin"})
        got = self.headers.get("X-RB-Token", "").encode("utf-8", "replace")
        if not hmac.compare_digest(got, b.token.encode("utf-8")):
            return self._json(403, {"error": "bad token"})
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._json(415, {"error": "content type must be application/json"})
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._json(411, {"error": "content length required"})
        if length < 0 or length > MAX_BODY:
            return self._json(413, {"error": "body too large"})
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError):
            return self._json(400, {"error": "invalid JSON"})
        if not isinstance(payload, dict):
            return self._json(400, {"error": "body must be a JSON object"})
        sid = payload.get("submission_id")
        if not isinstance(sid, str) or not sid or len(sid) > 100:
            return self._json(400, {"error": "submission_id required"})
        try:
            self._accept(b, sid, payload)
        finally:
            b.acked.set()

    def _accept(self, b, sid, payload):
        with b.lock:
            if sid in b.seen:
                if b.wait:
                    b.first_send.set()
                return self._json(200, dict(b.seen[sid], duplicate=True))
            if already_filed(b.bound, sid):
                return self._json(200, {"ok": True, "closed": b.wait, "duplicate": True})
            if b.wait and b.first_send.is_set():
                return self._json(410, {"error": "This round is closed. Your first send was saved."})
            try:
                meta = b.meta()
            except (OSError, ValueError):
                return self._json(500, {"error": "board metadata unreadable"})
            if payload.get("revision") != meta["revision"] or payload.get("board") != meta["board_id"]:
                return self._json(409, {"error": "This board was rebuilt. Reload; your notes are kept."})
            sent_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                doc = canonical_feedback(meta, payload, sent_at)
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            try:
                jpath, mpath, md = write_feedback(meta, doc)
            except OSError as e:
                return self._json(500, {"error": "could not write feedback: %s" % e})
            resp = {"ok": True, "closed": b.wait, "json": str(jpath), "markdown": str(mpath)}
            b.seen[sid] = resp
            b.last = (jpath, mpath, md)
            if b.wait:
                b.first_send.set()  # the write is done: the waiting job must exit even if the client vanished
        try:
            self._json(200, resp)
        except (OSError, ValueError):
            pass
        if not b.wait:
            safe_print(jpath, mpath, md)


def safe_print(jpath, mpath, md):
    try:
        print_feedback(jpath, mpath, md)
    except (OSError, ValueError):
        pass


def print_feedback(jpath, mpath, md):
    print("\nFEEDBACK RECEIVED", flush=True)
    print("Markdown: %s" % mpath, flush=True)
    print("JSON: %s\n" % jpath, flush=True)
    print(md, flush=True)


# ---------- file mode: watch an inbox for the page's downloaded JSON ----------

SENT_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DOWNLOAD_RE = re.compile(r"( \(\d+\))?\.json$")  # Chrome adds " (1)"; .crdownload never matches
UNREADABLE_POLLS = 10


def already_filed(meta, sid):
    """True if feedback for this submission id is already on disk (survives restarts)."""
    fdir = Path(meta["feedback_dir"])
    tag = "__%s" % (safe_name(sid)[:60])
    try:
        for n in os.listdir(fdir):
            if n.endswith(".json") and not n.startswith(".") and (n[:-5].endswith(tag) or re.search(re.escape(tag) + r"-\d+$", n[:-5])):
                return True
    except OSError:
        pass
    return False


def default_inbox():
    return Path(os.path.expanduser("~/Downloads"))


def open_path(path):
    """Open a file with the OS opener."""
    path = str(path)
    if sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    elif os.name == "nt":
        os.startfile(path)  # noqa: S606 - Windows only
    else:
        subprocess.run(["xdg-open", path], check=False)


class InboxWatcher:
    """Finds this board's feedback files in an inbox folder. Bound to the board id and
    revision it started with; validation is the server's (canonical_feedback)."""

    def __init__(self, meta, inbox):
        self.meta = meta
        self.inbox = Path(inbox)
        self.prefix = "review-feedback__%s__" % safe_name(meta["board_id"])
        self.seen = set()       # accepted submission ids
        self.reported = {}      # path -> (size, mtime_ns) already judged
        self.unreadable = {}    # path -> [signature, polls]

    def _say(self, msg):
        print(msg, file=sys.stderr, flush=True)

    def candidates(self):
        try:
            names = os.listdir(self.inbox)
        except OSError:
            return []
        out = []
        for n in names:
            if n.startswith(self.prefix) and DOWNLOAD_RE.search(n):
                p = self.inbox / n
                try:
                    out.append((p.stat().st_mtime_ns, p))
                except OSError:
                    pass
        return [p for _, p in sorted(out)]

    def poll(self):
        """Return (path, canonical doc) for the first acceptable file, or None."""
        meta = self.meta
        for p in self.candidates():
            try:
                st = p.stat()
            except OSError:
                continue
            sig = (st.st_size, st.st_mtime_ns)
            if self.reported.get(p) == sig:
                continue
            try:
                payload = json.loads(p.read_bytes().decode("utf-8"))
            except (OSError, ValueError):
                # likely still being written: look again next poll, and say so once if it stays broken
                u = self.unreadable.setdefault(p, [sig, 0])
                if u[0] != sig:
                    u[0], u[1] = sig, 0
                u[1] += 1
                if u[1] == UNREADABLE_POLLS:
                    self._say("Ignoring %s: not readable as JSON yet. Still waiting." % p.name)
                    self.reported[p] = sig
                continue
            self.reported[p] = sig
            if not isinstance(payload, dict) or payload.get("board") != meta["board_id"]:
                continue
            sid = payload.get("submission_id")
            if not isinstance(sid, str) or not sid or len(sid) > 100:
                self._say("Ignoring %s: no submission id." % p.name)
                continue
            if sid in self.seen or already_filed(meta, sid):
                continue
            if payload.get("revision") != meta["revision"]:
                self._say("Ignoring %s: it was sent from a different version of the board (revision %s, this board is %s). "
                          "Ask the reviewer to reload board.html and send again. Still waiting."
                          % (p.name, payload.get("revision"), meta["revision"]))
                continue
            sent_at = payload.get("sent_at")
            if not (isinstance(sent_at, str) and SENT_AT_RE.match(sent_at)):
                sent_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                doc = canonical_feedback(meta, payload, sent_at)
            except ValueError as e:
                self._say("Ignoring %s: %s. Still waiting." % (p.name, e))
                continue
            self.seen.add(sid)
            return p, doc
        return None


def wait_for_file(board_dir, inbox=None, interval=1.0, open_browser=False, timeout=None):
    """File mode: watch the inbox until one valid send arrives, file it, print it, return 0."""
    board_dir = Path(board_dir).resolve()
    meta = load_meta(board_dir)
    inbox = Path(inbox) if inbox else default_inbox()
    watcher = InboxWatcher(meta, inbox)
    page = board_dir / "board.html"
    print("Review board ready: %s" % page, flush=True)
    print("Waiting for feedback in %s (files named %s*.json)" % (inbox, watcher.prefix), flush=True)
    if not inbox.is_dir():
        print("Warning: %s does not exist yet." % inbox, file=sys.stderr, flush=True)
    if open_browser:
        open_path(page)
    t0 = time.time()
    try:
        while True:
            got = watcher.poll()
            if got:
                src, doc = got
                claim_dir = Path(meta["feedback_dir"]) / ".claiming"
                claim_dir.mkdir(parents=True, exist_ok=True)
                claimed = claim_dir / src.name
                try:
                    os.rename(src, claimed)  # atomic: exactly one watcher wins a download
                except FileNotFoundError:
                    watcher.seen.discard(doc.get("submission_id"))
                    continue
                if already_filed(meta, doc["submission_id"]):
                    claimed.unlink()
                    continue
                try:
                    jpath, mpath, md = write_feedback(meta, doc)
                except BaseException:
                    try:
                        os.rename(claimed, src)  # put it back so a retry can find it
                    except OSError:
                        pass
                    raise
                try:
                    claimed.unlink()
                except OSError:
                    pass
                safe_print(jpath, mpath, md)
                return 0
            if timeout is not None and time.time() - t0 > timeout:
                print("Timed out waiting for feedback.", file=sys.stderr, flush=True)
                return 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print("review_server: stopped", flush=True)
        return 130


def make_server(board_dir, wait=False, port=None):
    """Bind and return (server, board). An explicit port must be free; otherwise use the
    board's stable preferred port, then the next free one, then any free port."""
    board_dir = Path(board_dir).resolve()
    meta = load_meta(board_dir)
    candidates = [port] if port else [PORT_BASE + (preferred_port(meta["board_id"]) - PORT_BASE + i) % PORT_SPAN
                                      for i in range(PORT_SPAN)] + [0]
    last_err = None
    for p in candidates:
        try:
            srv = ThreadingHTTPServer((HOST, p), Handler)
        except OSError as e:
            last_err = e
            continue
        srv.daemon_threads = True
        srv.board = Board(board_dir, wait, srv.server_address[1])
        return srv, srv.board
    raise SystemExit("review_server: could not bind %s:%s (%s)" % (HOST, port, last_err))


def serve(board_dir, wait=False, port=None, open_browser=False):
    srv, board = make_server(board_dir, wait, port)
    url = "http://%s:%d/" % (HOST, board.port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("Review board ready: %s%s" % (url, "  (waiting for the first send)" if wait else ""), flush=True)
    print("Review board file: %s" % (board.dir / "board.html"), flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        if wait:
            board.first_send.wait()
            board.acked.wait(3)
            if board.last:
                safe_print(*board.last)
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        print("review_server: stopped", flush=True)
        return 130
    finally:
        srv.shutdown()
        srv.server_close()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("board_dir")
    ap.add_argument("--wait", action="store_true", help="exit 0 after the first accepted send")
    ap.add_argument("--port", type=int)
    ap.add_argument("--open", action="store_true", dest="open_browser")
    ap.add_argument("--inbox", help="file mode: folder to watch (default ~/Downloads); needs --wait")
    ap.add_argument("--poll", type=float, default=1.0, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.inbox:
        return wait_for_file(a.board_dir, a.inbox, a.poll, a.open_browser)
    return serve(a.board_dir, a.wait, a.port, a.open_browser)


if __name__ == "__main__":
    sys.exit(main())
