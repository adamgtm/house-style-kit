#!/usr/bin/env python3
"""Build a house style gallery: one browsable page of the work you want more of.

The gallery reads one manifest (a JSON file) that lists your role models: the
graphics, charts, slides, pages and emails that set the bar for your brand.
It checks every file the manifest names and writes a self-contained page.

Usage
-----
  python3 scripts/build_gallery.py
      Reads house-style/role-models/manifest.json under the current folder
      and writes index.html next to it. If there is none, it looks beside
      this script, so a copy saved as house-style/build_gallery.py works
      from any folder.

  python3 scripts/build_gallery.py --root path/to/project
      Same, under another folder.

  python3 scripts/build_gallery.py --manifest path/to/manifest.json
      Uses any manifest. index.html is written next to it.

  python3 scripts/build_gallery.py --check
      Validates the manifest only. Exits 1 and lists every problem.

  python3 scripts/build_gallery.py --open
      Builds, then opens the page in your default browser.

  python3 scripts/build_gallery.py --sheet out.html --ids a,b,c
        [--theme light|dark] [--size 1080x1350] [--cols 3]
      Draws the gallery itself as a fixed-size graphic for a social post:
      title, count line, group chips and a grid of the items you pick.
      Images are embedded, so this needs Pillow (pip install pillow).

Only the Python standard library is needed, except for --sheet.

Manifest schema
---------------
Every file path in a manifest is relative to the manifest's own folder, so
the folder can move or be shared as one piece ("chart.png", "images/x.png").
Write paths with forward slashes; Windows backslashes are converted. Images
("file" and "dark") must live inside the manifest's folder, and must be
.png, .jpg, .jpeg, .webp, .gif or .svg. For a PDF, deck or web page, save a
preview image and put the original's path in "source".

  {
    "title":   "House style gallery",          optional page title
    "intro":   "One line under the title.",    optional
    "brand":   {"name": "Your brand",          optional, shown in the footer
                "url":  "yourdomain.com"},
    "updated": "2026-10-07",                   optional
    "tokens": {                                optional; all keys optional
      "paper":  "#ffffff",   page background         (hex colors only)
      "ink":    "#141414",   main text
      "card":   "#f6f6f7",   behind each image       (derived if missing)
      "line":   "#e3e3e6",   borders                 (derived if missing)
      "accent": "#2563eb",   links, focus, "approved" chips
      "serif":  "ui-serif, Georgia, serif",          headings
      "sans":   "system-ui, sans-serif",             body text
      "mono":   "ui-monospace, Menlo, monospace",    labels
      "dark":   {"paper": "...", "ink": "...", ...}  optional dark colors;
                                                     derived if missing
    },
    "surfaces": [                              required: the kinds of work
      {"id": "social",          required, letters/numbers/dashes
       "group": "Graphics",     required, one filter chip per group
       "name": "Social graphics",  required
       "standard": "../social-graphics.md",  optional; linked if the file exists
       "gap": "Add the first post you'd publish again."}  optional; shown
                                                     while the surface is empty
    ],
    "items": [                                 required: the role models
      {"id": "launch-chart",    required, unique
       "surface": "social",     required, a surface id
       "title": "Launch chart", required
       "file": "launch-chart.png",           required image path
       "dark": "launch-chart-dark.png",      optional dark version
       "status": "approved",    required: approved | shipped | borrowed
       "date": "2026-10-07",    optional
       "where": "LinkedIn",     optional; linked when "url" is set
       "url": "https://...",    optional: http, https, mailto or a relative
                                link; no spaces or hidden characters
       "words": "Yes. This.",   optional: your own words about it
       "why": "One idea, real numbers.",     optional: what makes it a model
       "note": "Footer is out of date.",     optional
       "source": "launch-chart.html"}        optional: what it was made from
                                             (may point outside the folder;
                                             linked if it exists, never read)
    ]
  }

Statuses: "approved" means you said this is the bar. "shipped" means it went
out and you'd do it again. "borrowed" means someone else's work you admire,
kept until your own work replaces it.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import quote

DEFAULT_MANIFEST = Path("house-style") / "role-models" / "manifest.json"
DEFAULT_TITLE = "House style gallery"

STATUSES = {
    "approved": ("Approved", "You approved this as the bar"),
    "shipped": ("Shipped", "Published, and you'd do it again"),
    "borrowed": ("Borrowed", "Someone else's work you admire, kept until your own replaces it"),
}

DEFAULT_COLORS = {"paper": "#ffffff", "ink": "#141414", "accent": "#2563eb"}
DEFAULT_FONTS = {
    "serif": 'ui-serif, "New York", Georgia, "Times New Roman", serif',
    "sans": 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    "mono": 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
}
COLOR_KEYS = ("paper", "ink", "card", "line", "accent")
FONT_KEYS = tuple(DEFAULT_FONTS)

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
FONT_RE = re.compile(r"""^[A-Za-z0-9 ,"'._-]+$""")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
DRIVE_RE = re.compile(r"^[A-Za-z]:/")
SAFE_SCHEMES = ("http:", "https:", "mailto:")
OPTIONAL_TEXT = ("dark", "date", "where", "url", "words", "why", "note", "source")
PAGE_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")


class GalleryError(Exception):
    """A problem the user can fix. Printed plainly, without a traceback."""


# --------------------------------------------------------------------------- helpers


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def norm_rel(value: str) -> str:
    """Manifest paths use forward slashes. Windows backslashes are converted."""
    return value.replace("\\", "/")


def clean_url(url: str) -> str:
    """Drop stray spaces around a URL. Tabs, line breaks and control characters stay
    put so url_problem can refuse them."""
    return url.strip(" ")


def url_problem(url: str):
    """Why a URL can't be linked, or None. Allowed: http, https, mailto, or a link
    with no scheme (relative). Refused: any whitespace or hidden character inside it,
    since browsers drop those and "java\\tscript:" would become "javascript:"."""
    url = clean_url(url)
    if not url:
        return "is empty"
    if any(ch.isspace() or unicodedata.category(ch) in ("Cc", "Cf") for ch in url):
        return "has a space, tab, line break or hidden character in it. Remove it (write a space as %20)"
    if SCHEME_RE.match(url) and not url.lower().startswith(SAFE_SCHEMES):
        return "should start with http://, https:// or mailto: (or be a relative link like posts/launch.html)"
    return None


def is_safe_url(url) -> bool:
    return isinstance(url, str) and url_problem(url) is None


def page_href(rel: str) -> str:
    """A manifest-relative file path as a URL the page can use."""
    return quote(norm_rel(rel))


def local_link(base: Path, value: str):
    """Link a manifest-relative reference (standard, source) when it names a file that
    exists. It may sit outside the manifest folder: it is only checked for existence
    and linked, never read."""
    value = norm_rel(value or "")
    if not value or SCHEME_RE.match(value) or value.startswith("/") or Path(value).is_absolute():
        return None
    try:
        return page_href(value) if (base / value).is_file() else None
    except OSError:
        return None


def image_problem(base: Path, rel: str):
    """Why a manifest image path can't be used, or None. The path must be relative,
    name a browser-friendly image, and resolve (following symlinks) to a file inside
    the manifest's folder."""
    rel = norm_rel(rel)
    drive = DRIVE_RE.match(rel)
    if SCHEME_RE.match(rel) and not drive:
        return "should be a file path relative to the manifest folder, not a URL. Save the image next to the manifest."
    if drive or rel.startswith("/") or Path(rel).is_absolute():
        return 'should be relative to the manifest folder (for example "images/chart.png"), not an absolute path.'
    if Path(rel).suffix.lower() not in PAGE_IMAGE_EXTS:
        return ("is not an image the gallery can show (.png, .jpg, .jpeg, .webp, .gif or .svg). "
                'Add a preview image and keep the original in "source".')
    try:
        root = base.resolve()
        target = (base / rel).resolve()
        target.relative_to(root)
    except ValueError:
        return ("points outside the manifest folder. Keep images inside the folder that holds "
                "manifest.json; a symlink that leads outside counts as outside.")
    except (OSError, RuntimeError) as exc:  # e.g. a symlink loop
        return f"can't be read ({exc})."
    if not target.is_file():
        return "not found."
    if target.suffix.lower() not in PAGE_IMAGE_EXTS:
        return (f'is a link to "{target.name}", which is not an image the gallery can show. '
                'Add a preview image and keep the original in "source".')
    return None


def image_path(base: Path, rel: str) -> Path:
    """The resolved image file, or a GalleryError. The one gate before any image is read."""
    problem = image_problem(base, rel)
    if problem:
        raise GalleryError(f'Image "{rel}" {problem}')
    return (base / norm_rel(rel)).resolve()


def describe(kind: str, entry, index: int) -> str:
    if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]:
        return f'{kind} "{entry["id"]}"'
    return f"{kind} #{index + 1}"


# --------------------------------------------------------------------------- manifest


def load_manifest(path: Path) -> dict:
    if not path.is_file():
        raise GalleryError(
            f"No manifest found at {path}.\n"
            "Pass --manifest PATH, or run from the folder that holds house-style/ "
            "(or point --root at it).")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GalleryError(
            f"{path} is not valid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}.\n"
            "Look for a missing comma, a trailing comma, or an unquoted value.") from None
    except UnicodeDecodeError:
        raise GalleryError(f"{path} is not UTF-8 text.") from None
    if not isinstance(data, dict):
        raise GalleryError(f"{path} should hold one JSON object: {{ \"surfaces\": [...], \"items\": [...] }}.")
    return data


def check_manifest(data: dict, base: Path) -> tuple[list[str], list[str]]:
    """Return (problems, warnings). Problems stop a build; warnings don't."""
    problems: list[str] = []
    warnings: list[str] = []

    for key in ("title", "intro", "updated"):
        if key in data and not isinstance(data[key], str):
            problems.append(f'"{key}" should be text in quotes.')
    brand = data.get("brand", {})
    if not isinstance(brand, dict):
        problems.append('"brand" should be an object like {"name": "...", "url": "..."}.')
    else:
        for key in ("name", "url"):
            if key in brand and not isinstance(brand[key], str):
                problems.append(f'brand "{key}" should be text in quotes.')
        burl = brand.get("url")
        if isinstance(burl, str) and clean_url(burl):
            problem = url_problem(brand_href(burl))
            if problem:
                problems.append(f"brand url {burl!r} {problem}.")

    problems.extend(check_tokens(data.get("tokens", {}), warnings))

    surfaces = data.get("surfaces")
    items = data.get("items")
    if not isinstance(surfaces, list):
        problems.append('"surfaces" is missing or is not a list. Add "surfaces": [ ... ].')
        surfaces = []
    if not isinstance(items, list):
        problems.append('"items" is missing or is not a list. Add "items": [] even when it is empty.')
        items = []

    surface_ids: set[str] = set()
    for n, s in enumerate(surfaces):
        label = describe("surface", s, n)
        if not isinstance(s, dict):
            problems.append(f"{label} should be an object with id, group and name.")
            continue
        for key in ("id", "group", "name"):
            if not isinstance(s.get(key), str) or not s[key].strip():
                problems.append(f'{label} is missing "{key}".')
        for key in ("standard", "gap"):
            if key in s and not isinstance(s[key], str):
                problems.append(f'{label}: "{key}" should be text in quotes.')
        sid = s.get("id")
        if isinstance(sid, str) and sid:
            if not ID_RE.match(sid):
                problems.append(f'{label}: ids use letters, numbers, dots, dashes or underscores '
                                f'(try "{slug(sid)}").')
            if sid in surface_ids:
                problems.append(f'duplicate surface id "{sid}".')
            surface_ids.add(sid)

    seen: dict[str, int] = {}
    for n, item in enumerate(items):
        label = describe("item", item, n)
        if not isinstance(item, dict):
            problems.append(f"{label} should be an object with id, surface, title, file and status.")
            continue
        for key in ("id", "surface", "title", "file", "status"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                problems.append(f'{label} is missing "{key}".')
        for key in OPTIONAL_TEXT:
            if key in item and not isinstance(item[key], str):
                problems.append(f'{label}: "{key}" should be text in quotes.')

        iid = item.get("id")
        if isinstance(iid, str) and iid:
            if not ID_RE.match(iid):
                problems.append(f'{label}: ids use letters, numbers, dots, dashes or underscores '
                                f'(try "{slug(iid)}").')
            seen[iid] = seen.get(iid, 0) + 1

        surface = item.get("surface")
        if isinstance(surface, str) and surface and surface not in surface_ids:
            known = ", ".join(sorted(surface_ids)) or "none yet"
            problems.append(f'{label}: unknown surface "{surface}". Known surfaces: {known}.')

        status = item.get("status")
        if isinstance(status, str) and status and status not in STATUSES:
            problems.append(f'{label}: status "{status}" should be one of: {", ".join(STATUSES)}.')

        for key in ("file", "dark"):
            rel = item.get(key)
            if not isinstance(rel, str) or not rel.strip():
                continue
            problem = image_problem(base, rel)
            if problem == "not found.":
                problems.append(f"{label}: {key} not found: {norm_rel(rel)}")
            elif problem:
                problems.append(f'{label}: {key} "{rel}" {problem}')

        url = item.get("url")
        if isinstance(url, str) and url != "":
            problem = url_problem(url)
            if problem:
                problems.append(f"{label}: url {url!r} {problem}.")
            elif not item.get("where"):
                warnings.append(f'{label} has a url but no "where", so the link has no text. Add "where".')

    for iid, count in seen.items():
        if count > 1:
            problems.append(f'duplicate item id "{iid}" ({count} times). Each item needs its own id.')
    return problems, warnings


def check_tokens(tokens, warnings: list[str]) -> list[str]:
    problems: list[str] = []
    if not isinstance(tokens, dict):
        return ['"tokens" should be an object like {"paper": "#ffffff", "ink": "#141414"}.']
    known = set(COLOR_KEYS) | set(FONT_KEYS) | {"dark"}
    for key, value in tokens.items():
        if key not in known:
            warnings.append(f'tokens: "{key}" is not used. Known tokens: {", ".join(sorted(known))}.')
        elif key in COLOR_KEYS and not (isinstance(value, str) and HEX_RE.match(value)):
            problems.append(f'tokens "{key}" should be a hex color like "#1a1a1a" (got {value!r}).')
        elif key in FONT_KEYS and not (isinstance(value, str) and FONT_RE.match(value)):
            problems.append(f'tokens "{key}" should be a font list like "Inter, system-ui, sans-serif" '
                            f"(letters, numbers, spaces, commas and quotes only).")
    dark = tokens.get("dark", {})
    if not isinstance(dark, dict):
        problems.append('tokens "dark" should be an object like {"paper": "#161616", "ink": "#ededed"}.')
    else:
        for key, value in dark.items():
            if key not in COLOR_KEYS:
                warnings.append(f'tokens.dark: "{key}" is not used. Dark tokens: {", ".join(COLOR_KEYS)}.')
            elif not (isinstance(value, str) and HEX_RE.match(value)):
                problems.append(f'tokens.dark "{key}" should be a hex color like "#161616" (got {value!r}).')
    return problems


def slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", text.strip()).strip("-.").lower()
    return s or "item-1"


def validated(path: Path) -> dict:
    data = load_manifest(path)
    problems, warnings = check_manifest(data, path.parent)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if problems:
        lines = "\n".join(f"  - {p}" for p in problems)
        noun = "problem" if len(problems) == 1 else "problems"
        hint = ""
        if any(" not found: " in p for p in problems):
            hint = f"\nFile paths are read relative to the manifest's folder: {path.parent.resolve()}"
        raise GalleryError(f"{path} has {len(problems)} {noun}:\n{lines}{hint}\nFix these and run again.")
    return data


# --------------------------------------------------------------------------- colors


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def mix(a: str, b: str, t: float) -> str:
    """Move color a toward color b by t (0..1)."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(x + (y - x) * t for x, y in zip(ra, rb))


def luminance(color: str) -> float:
    def chan(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable(fg: str, bg: str, target: float = 4.5) -> str:
    """Nudge fg toward black or white until it reads on bg."""
    pole = "#000000" if luminance(bg) > 0.4 else "#ffffff"
    for _ in range(20):
        if contrast(fg, bg) >= target:
            return fg
        fg = mix(fg, pole, 0.15)
    return fg


def is_dark(color: str) -> bool:
    return luminance(color) < 0.3


def complete(colors: dict) -> dict:
    """Fill derived colors from paper, ink and accent."""
    c = dict(colors)
    paper, ink = c["paper"], c["ink"]
    c.setdefault("card", mix(paper, ink, 0.04 if not is_dark(paper) else 0.05))
    c.setdefault("line", mix(paper, ink, 0.13 if not is_dark(paper) else 0.16))
    c["soft"] = readable(mix(ink, paper, 0.30), c["card"])
    c["faint"] = readable(mix(ink, paper, 0.42), c["card"])
    c["accent_ink"] = readable(c["accent"], c["card"])
    return c


def schemes(tokens: dict) -> tuple[dict, dict, str]:
    """(light, dark, default) color sets. Missing dark colors are derived from the light ones."""
    tokens = tokens if isinstance(tokens, dict) else {}
    base = dict(DEFAULT_COLORS)
    base.update({k: tokens[k] for k in COLOR_KEYS if k in tokens})
    given_dark = {k: v for k, v in (tokens.get("dark") or {}).items() if k in COLOR_KEYS}

    paper, ink, accent = base["paper"], base["ink"], base["accent"]
    other = {"paper": mix(ink, paper, 0.05), "ink": mix(paper, ink, 0.08)}
    other["accent"] = mix(accent, "#ffffff", 0.3) if is_dark(other["paper"]) else mix(accent, "#000000", 0.25)

    if is_dark(paper):
        dark, light, default = complete(base), complete(other), "dark"
    else:
        other.update(given_dark)
        light, dark, default = complete(base), complete(other), "light"

    for c in (light, dark):
        c["bar"] = light["ink"] if c is light else mix(dark["paper"], "#000000", 0.45)
        if not is_dark(c["bar"]):
            c["bar"] = "#111111"
        c["bar_fg"] = "#ffffff" if luminance(c["bar"]) < 0.2 else "#000000"
        c["bar_url"] = readable(dark["accent"], c["bar"])
    return light, dark, default


def fonts(tokens: dict) -> dict:
    tokens = tokens if isinstance(tokens, dict) else {}
    return {k: tokens.get(k) or v for k, v in DEFAULT_FONTS.items()}


def css_vars(c: dict) -> str:
    return (f"--paper:{c['paper']};--ink:{c['ink']};--card:{c['card']};--line:{c['line']};"
            f"--accent:{c['accent']};--accent-ink:{c['accent_ink']};--soft:{c['soft']};--faint:{c['faint']};"
            f"--bar:{c['bar']};--bar-fg:{c['bar_fg']};--bar-url:{c['bar_url']}")


# --------------------------------------------------------------------------- page

PAGE_CSS = """
*{box-sizing:border-box}
[hidden]{display:none!important}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 var(--sans);-webkit-font-smoothing:antialiased}
a{color:var(--accent-ink);text-underline-offset:2px}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.wrap{max-width:1240px;margin:0 auto;padding:44px clamp(16px,4vw,40px) 0}
h1{font:400 clamp(38px,7vw,68px)/1.04 var(--serif);letter-spacing:-.01em;margin:0;text-wrap:balance;overflow-wrap:anywhere}
.lede{max-width:64ch;margin:14px 0 0;color:var(--soft);font-size:16px;text-wrap:pretty}
.count{font:13px/1.5 var(--mono);color:var(--soft);margin:12px 0 0;font-variant-numeric:tabular-nums}
.filters{position:sticky;top:0;z-index:2;display:flex;flex-wrap:wrap;gap:8px;margin:28px 0 0;padding:12px 0;background:var(--paper);border-bottom:1px solid var(--line)}
.filters button{flex:none;font:12px/1 var(--mono);color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:6px;padding:9px 12px;cursor:pointer}
.filters button:hover{border-color:var(--faint)}
.filters button[aria-pressed="true"]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
section{padding:40px 0 12px;border-bottom:1px solid var(--line);scroll-margin-top:72px}
h2{font:400 clamp(26px,4vw,36px)/1.1 var(--serif);margin:0;overflow-wrap:anywhere}
.meta{font:12px/1.5 var(--mono);color:var(--faint);margin:8px 0 0;overflow-wrap:anywhere}
.meta a{color:inherit}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr));gap:32px 24px;margin-top:22px}
figure{margin:0;display:flex;flex-direction:column;gap:12px;min-width:0}
.shot{position:relative;display:block;width:100%;aspect-ratio:4/3;padding:0;margin:0;overflow:hidden;background:var(--card);border:1px solid var(--line);border-radius:8px;cursor:zoom-in;font:inherit;color:inherit}
.shot:hover{border-color:var(--faint)}
.shot img{position:absolute;inset:10px;width:calc(100% - 20px);height:calc(100% - 20px);object-fit:contain}
figcaption{display:flex;flex-direction:column;gap:7px;min-width:0}
h3{font:600 16px/1.3 var(--sans);margin:0;overflow-wrap:anywhere}
.when{margin:0;font:12px/1.9 var(--mono);color:var(--soft);overflow-wrap:anywhere}
.when .chip{margin-right:8px}
.chip{display:inline-block;font:11px/1 var(--mono);padding:4px 7px;border:1px solid var(--line);border-radius:4px;background:var(--card);color:var(--ink)}
.chip.approved{border-color:var(--accent);color:var(--accent-ink)}
.chip.borrowed{border-style:dashed;border-color:var(--faint);color:var(--soft);background:transparent}
blockquote{margin:2px 0;padding-left:12px;border-left:2px solid var(--accent);font:italic 400 18px/1.35 var(--serif);overflow-wrap:anywhere}
.why{margin:0;color:var(--soft);font-size:14px;overflow-wrap:anywhere}
.note{margin:0;color:var(--faint);font-size:13px;overflow-wrap:anywhere}
.src{margin:0;font:11px/1.4 var(--mono);color:var(--faint);overflow-wrap:anywhere}
.src a{color:inherit}
.toggle{display:flex;gap:6px}
.toggle button{font:11px/1 var(--mono);padding:6px 10px;border:1px solid var(--line);border-radius:4px;background:var(--card);color:var(--ink);cursor:pointer}
.toggle button[aria-pressed="true"]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.gap{margin:22px 0 0;padding:20px;border:1px dashed var(--line);border-radius:8px;color:var(--soft);font-size:14px}
.gap b{color:var(--ink);font-weight:600}
footer.bar{margin-top:56px;background:var(--bar);color:var(--bar-fg)}
footer.bar .in{max-width:1240px;margin:0 auto;display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px 16px;padding:20px clamp(16px,4vw,40px)}
footer.bar b{font:700 16px/1.25 var(--sans);overflow-wrap:anywhere}
footer.bar a,footer.bar span{font:14px/1.25 var(--mono);color:var(--bar-url);text-decoration:none;overflow-wrap:anywhere}
footer.bar a:hover{text-decoration:underline}
dialog{padding:12px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);max-width:min(96vw,1500px);max-height:94vh}
dialog::backdrop{background:rgba(0,0,0,.8)}
dialog img{display:block;max-width:100%;max-height:calc(94vh - 84px);width:auto;height:auto;margin:0 auto}
dialog .cap{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:10px;font:12px/1.4 var(--mono);color:var(--soft)}
dialog button{flex:none;font:12px/1 var(--mono);padding:9px 12px;border:1px solid var(--ink);border-radius:6px;background:var(--ink);color:var(--paper);cursor:pointer}
@media (min-width:960px){
  section{display:grid;grid-template-columns:minmax(0,240px) minmax(0,1fr);gap:0 40px;align-items:start}
  .head{position:sticky;top:76px}
  .grid,.gap{margin-top:6px}
}
@media (max-width:600px){
  .wrap{padding-top:28px}
  .filters{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:thin}
  section{padding-top:32px}
}
"""

PAGE_JS = """
(function(){
  var buttons=[].slice.call(document.querySelectorAll('.filters button'));
  var sections=[].slice.call(document.querySelectorAll('section[data-group]'));
  var KEY='house-style-gallery-group';
  function pick(g){
    buttons.forEach(function(b){b.setAttribute('aria-pressed', String(b.getAttribute('data-group')===g));});
    sections.forEach(function(s){s.hidden=!(g==='all'||s.getAttribute('data-group')===g);});
    try{localStorage.setItem(KEY,g);}catch(e){}
  }
  buttons.forEach(function(b){b.addEventListener('click',function(){pick(b.getAttribute('data-group'));});});
  var saved='all';
  try{saved=localStorage.getItem(KEY)||'all';}catch(e){}
  if(!buttons.some(function(b){return b.getAttribute('data-group')===saved;})) saved='all';
  pick(saved);

  [].forEach.call(document.querySelectorAll('.toggle'),function(t){
    var fig=t.closest('figure'), shot=fig.querySelector('.shot'), img=shot.querySelector('img');
    var opts=[].slice.call(t.querySelectorAll('button'));
    opts.forEach(function(b){
      b.addEventListener('click',function(){
        img.src=b.getAttribute('data-src'); shot.setAttribute('data-full',b.getAttribute('data-src'));
        opts.forEach(function(x){x.setAttribute('aria-pressed',String(x===b));});
      });
    });
  });

  var dlg=document.getElementById('hsg-lightbox'), big=document.getElementById('hsg-lightbox-img'), cap=document.getElementById('hsg-lightbox-cap');
  [].forEach.call(document.querySelectorAll('.shot'),function(s){
    s.addEventListener('click',function(){
      var full=s.getAttribute('data-full'), alt=s.querySelector('img').alt;
      if(!dlg.showModal){window.open(full,'_blank');return;}
      big.src=full; big.alt=alt; cap.textContent=alt; dlg.showModal();
    });
  });
  document.getElementById('hsg-lightbox-close').addEventListener('click',function(){dlg.close();});
  dlg.addEventListener('click',function(e){if(e.target===dlg) dlg.close();});
  dlg.addEventListener('close',function(){big.removeAttribute('src');});
})();
"""


def groups_of(surfaces: list) -> list[str]:
    return list(dict.fromkeys(s["group"] for s in surfaces))


def status_chip(status: str) -> str:
    label, tip = STATUSES.get(status, (status.title(), ""))
    return f'<span class="chip {esc(status)}" title="{esc(tip)}">{esc(label)}</span>'


def when_line(item: dict) -> str:
    parts = []
    if item.get("date"):
        parts.append(esc(item["date"]))
    if item.get("where"):
        where = esc(item["where"])
        url = item.get("url")
        if isinstance(url, str) and is_safe_url(url):
            url = clean_url(url)
            where = f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{where} ↗</a>'
        parts.append(where)
    return f'<p class="when">{status_chip(item["status"])}{" · ".join(parts)}</p>'


def render_page(data: dict, base: Path) -> str:
    surfaces, items = data["surfaces"], data["items"]
    title = (data.get("title") or DEFAULT_TITLE).strip() or DEFAULT_TITLE
    tokens = data.get("tokens") or {}
    light, dark, default = schemes(tokens)
    f = fonts(tokens)
    by_surface: dict[str, list] = {s["id"]: [] for s in surfaces}
    for item in items:
        by_surface[item["surface"]].append(item)
    filled = sum(1 for s in surfaces if by_surface[s["id"]])

    if default == "light":
        scheme_css = (f":root{{{css_vars(light)};color-scheme:light}}\n"
                      f"@media (prefers-color-scheme: dark){{:root{{{css_vars(dark)};color-scheme:dark}}}}")
    else:
        scheme_css = (f":root{{{css_vars(dark)};color-scheme:dark}}\n"
                      f"@media (prefers-color-scheme: light){{:root{{{css_vars(light)};color-scheme:light}}}}")
    font_css = f":root{{--serif:{f['serif']};--sans:{f['sans']};--mono:{f['mono']}}}"

    count = [f"{len(items)} role model{'s' if len(items) != 1 else ''}",
             f"{filled} of {len(surfaces)} kinds of work covered"]
    if data.get("updated"):
        count.append(f"updated {esc(data['updated'])}")

    out = ["<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
           '<meta name="color-scheme" content="light dark">',
           '<meta name="generator" content="House Style Kit build_gallery.py">',
           f"<title>{esc(title)}</title>",
           f"<style>\n{scheme_css}\n{font_css}\n{PAGE_CSS}</style>", "</head>", "<body>",
           '<div class="wrap">', "<header>", f"<h1>{esc(title)}</h1>"]
    if data.get("intro"):
        out.append(f'<p class="lede">{esc(data["intro"])}</p>')
    out.append(f'<p class="count">{" · ".join(count)}</p>')
    out.append("</header>")

    out.append('<nav class="filters" aria-label="Filter by group">')
    out.append(f'<button type="button" data-group="all" aria-pressed="true">All · {len(items)}</button>')
    for g in groups_of(surfaces):
        n = sum(len(by_surface[s["id"]]) for s in surfaces if s["group"] == g)
        out.append(f'<button type="button" data-group="{esc(g)}" aria-pressed="false">{esc(g)} · {n}</button>')
    out.append("</nav>")
    out.append("<main>")

    for s in surfaces:
        out.append(f'<section id="surface-{esc(s["id"])}" data-group="{esc(s["group"])}" '
                   f'aria-labelledby="heading-{esc(s["id"])}">')
        out.append(f'<div class="head"><h2 id="heading-{esc(s["id"])}">{esc(s["name"])}</h2>')
        meta = [esc(s["group"])]
        if s.get("standard"):
            link = local_link(base, s["standard"])
            std = esc(s["standard"])
            meta.append(f'Standard: <a href="{esc(link)}">{std}</a>' if link else f"Standard: {std}")
        out.append(f'<p class="meta">{" · ".join(meta)}</p></div>')
        members = by_surface[s["id"]]
        if not members:
            gap = f" {esc(s['gap'])}" if s.get("gap") else ""
            out.append(f'<p class="gap"><b>No role model yet.</b>{gap}</p>')
            out.append("</section>")
            continue
        out.append('<div class="grid">')
        for item in members:
            light_src = page_href(item["file"])
            alt = esc(item["title"])
            out.append(f'<figure id="item-{esc(item["id"])}">')
            out.append(f'<button type="button" class="shot" data-full="{esc(light_src)}" '
                       f'aria-label="Enlarge: {alt}"><img loading="lazy" '
                       f'src="{esc(light_src)}" alt="{alt}"></button>')
            out.append("<figcaption>")
            out.append(f"<h3>{esc(item['title'])}</h3>")
            out.append(when_line(item))
            if item.get("words"):
                out.append(f"<blockquote>“{esc(item['words'])}”</blockquote>")
            if item.get("why"):
                out.append(f'<p class="why">{esc(item["why"])}</p>')
            if item.get("note"):
                out.append(f'<p class="note">Note: {esc(item["note"])}</p>')
            if item.get("dark"):
                dark_src = page_href(item["dark"])
                out.append('<div class="toggle" role="group" aria-label="Light or dark version">'
                           f'<button type="button" data-src="{esc(light_src)}" aria-pressed="true">Light</button>'
                           f'<button type="button" data-src="{esc(dark_src)}" aria-pressed="false">Dark</button>'
                           "</div>")
            if item.get("source"):
                link = local_link(base, item["source"])
                src = esc(item["source"])
                out.append(f'<p class="src">Source: <a href="{esc(link)}">{src}</a></p>' if link
                           else f'<p class="src">Source: {src}</p>')
            out.append("</figcaption></figure>")
        out.append("</div></section>")

    out.append("</main></div>")
    out.append(footer_html(data.get("brand") or {}))
    out.append('<dialog id="hsg-lightbox" aria-label="Enlarged role model"><img id="hsg-lightbox-img" alt="">'
               '<div class="cap"><span id="hsg-lightbox-cap"></span>'
               '<button type="button" id="hsg-lightbox-close">Close</button></div></dialog>')
    out.append(f"<script>{PAGE_JS}</script>")
    out.append("</body>\n</html>\n")
    return "\n".join(out)


def brand_href(url: str) -> str:
    """The footer link for a brand url; a bare domain like "yourdomain.com" gets https://."""
    url = clean_url(url)
    return url if SCHEME_RE.match(url) else "https://" + url.lstrip("/")


def footer_html(brand: dict) -> str:
    name = (brand.get("name") or "").strip()
    url = clean_url(brand.get("url") or "")
    if not name and not url:
        return ""
    right = ""
    if url:
        href = brand_href(url)
        if is_safe_url(href):
            right = f'<a href="{esc(href)}" target="_blank" rel="noopener noreferrer">{esc(url)}</a>'
        else:
            right = f"<span>{esc(url)}</span>"
    return f'<footer class="bar"><div class="in"><b>{esc(name)}</b>{right}</div></footer>'


def write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def build_page(manifest: Path) -> Path:
    data = validated(manifest)
    out = manifest.parent / "index.html"
    write_text(out, render_page(data, manifest.parent))
    surfaces, items = data["surfaces"], data["items"]
    filled = len({i["surface"] for i in items})
    print(f"Wrote {out} ({len(items)} role models, {filled} of {len(surfaces)} kinds of work covered)")
    return out


# --------------------------------------------------------------------------- sheet


def _thumb(path: Path, width: int) -> tuple[str, float]:
    """An embedded, downscaled copy: (data URI, height / width)."""
    if path.suffix.lower() == ".svg":
        raw = path.read_bytes()
        return "data:image/svg+xml;base64," + base64.b64encode(raw).decode(), _svg_ratio(raw)
    from PIL import Image  # checked by build_sheet before any image is read

    try:
        with Image.open(path) as im:
            im.load()
            has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
            if has_alpha:
                rgba = im.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
                im2 = flat
            else:
                im2 = im.convert("RGB")
    except Exception as exc:  # Pillow raises several types for unreadable files
        raise GalleryError(f"Could not read image {path}: {exc}") from None
    ratio = im2.height / im2.width
    if im2.width > width:
        resample = getattr(Image, "Resampling", Image).LANCZOS
        im2 = im2.resize((width, max(1, round(width * ratio))), resample)
    buf = io.BytesIO()
    im2.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), ratio


def _svg_ratio(raw: bytes) -> float:
    """height / width from an SVG's viewBox, or its width and height; 1.0 if neither."""
    head = raw[:4096].decode("utf-8", "replace")
    tag = re.search(r"<svg\b[^>]*>", head, re.S)
    if tag:
        box = re.search(r'viewBox\s*=\s*["\']\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', tag.group(0))
        if box and float(box.group(1)) > 0:
            return float(box.group(2)) / float(box.group(1))
        w = re.search(r'\bwidth\s*=\s*["\']\s*([\d.]+)(?:px)?\s*["\']', tag.group(0))
        h = re.search(r'\bheight\s*=\s*["\']\s*([\d.]+)(?:px)?\s*["\']', tag.group(0))
        if w and h and float(w.group(1)) > 0:
            return float(h.group(1)) / float(w.group(1))
    return 1.0


def parse_size(size: str) -> tuple[int, int]:
    m = re.match(r"^\s*(\d{2,5})\s*[xX×]\s*(\d{2,5})\s*$", size or "")
    if not m:
        raise GalleryError(f'--size should look like 1080x1350 (got "{size}").')
    w, h = int(m.group(1)), int(m.group(2))
    if min(w, h) < 200 or max(w, h) > 8000:
        raise GalleryError("--size should be between 200 and 8000 pixels on each side.")
    return w, h


def render_sheet(data: dict, base: Path, ids: list[str], theme: str = "light",
                 size: str = "1080x1350", cols: int = 3) -> tuple[str, float]:
    """The sheet's HTML, plus a rough share (0..1) of the grid the cards leave empty."""
    w, h = parse_size(size)
    if cols < 1 or cols > 8:
        raise GalleryError("--cols should be between 1 and 8.")
    by_id = {i["id"]: i for i in data["items"]}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        known = ", ".join(by_id) or "none yet"
        raise GalleryError(f"Unknown item ids: {', '.join(unknown)}. Known ids: {known}.")
    if not ids:
        raise GalleryError("--ids needs at least one item id, for example --ids chart-a,chart-b.")

    tokens = data.get("tokens") or {}
    light, dark, _ = schemes(tokens)
    c = dark if theme == "dark" else light
    f = fonts(tokens)
    names = {s["id"]: s["name"] for s in data["surfaces"]}
    filled = len({i["surface"] for i in data["items"]})
    n_items = len(data["items"])
    title = (data.get("title") or DEFAULT_TITLE).strip() or DEFAULT_TITLE
    brand = data.get("brand") or {}

    k = w / 1080  # type scale follows the canvas width
    def px(n: float) -> str:
        return f"{max(1, round(n * k))}px"

    cols = min(cols, len(ids))
    rows = math.ceil(len(ids) / cols)
    frame, pad, gap_x = 12 * k, 36 * k, 20 * k
    cell_w = (w - 2 * frame - 2 * pad - (cols - 1) * gap_x) / cols - 16 * k
    thumb_w = max(240, int(cell_w * 2))

    cards, ratios = [], []
    for i in ids:
        item = by_id[i]
        key = "dark" if theme == "dark" and item.get("dark") else "file"
        src, ratio = _thumb(image_path(base, item[key]), thumb_w)
        ratios.append(ratio)
        cards.append(
            f'<figure data-ratio="{ratio:.4f}"><div class="shot"><img src="{esc(src)}" alt="{esc(item["title"])}">'
            f'</div><figcaption><h3>{esc(names.get(item["surface"], item["surface"]))}</h3>'
            f'{status_chip(item["status"])}</figcaption></figure>')

    chips = ['<span class="fchip on">All</span>'] + [
        f'<span class="fchip">{esc(g)}</span>' for g in groups_of(data["surfaces"])]

    bar_name = esc((brand.get("name") or "").strip())
    bar_url = esc(clean_url(brand.get("url") or ""))
    bar = (f'<div class="bar"><b>{bar_name}</b><span>{bar_url}</span></div>'
           if bar_name or bar_url else "")

    css = f"""
*{{box-sizing:border-box}}
html,body{{margin:0;padding:0;background:{c['bar']}}}
body{{width:{w}px;height:{h}px;overflow:hidden}}
.canvas{{width:{w}px;height:{h}px;background:{c['bar']};padding:{px(12)} {px(12)} {px(12) if not bar else '0'};display:flex;flex-direction:column;overflow:hidden}}
.paper{{flex:1;min-height:0;background:{c['paper']};color:{c['ink']};font-family:{f['sans']};-webkit-font-smoothing:antialiased;
  padding:{px(40)} {px(36)} {px(32)};display:flex;flex-direction:column;gap:{px(18)}}}
h1{{font:400 {px(76)}/1 {f['serif']};letter-spacing:-.015em;margin:0;overflow-wrap:anywhere}}
.count{{font:{px(18)}/1.3 {f['mono']};color:{c['soft']};margin:0}}
.filters{{display:flex;flex-wrap:wrap;gap:{px(8)};padding-bottom:{px(18)};border-bottom:1px solid {c['line']}}}
.fchip{{font:{px(15)}/1 {f['mono']};padding:{px(9)} {px(12)};border:1px solid {c['line']};border-radius:{px(6)};background:{c['card']};color:{c['ink']}}}
.fchip.on{{background:{c['ink']};color:{c['paper']};border-color:{c['ink']}}}
.grid{{flex:1;min-height:0;display:grid;grid-template-columns:repeat({cols},minmax(0,1fr));grid-template-rows:repeat({rows},minmax(0,1fr));align-content:center;gap:{px(22)} {px(20)}}}
figure{{margin:0;display:flex;flex-direction:column;gap:{px(10)};min-width:0;min-height:0}}
.shot{{flex:1;min-height:0;display:flex;padding:{px(8)};background:{c['card']};border:1px solid {c['line']};border-radius:{px(8)};overflow:hidden}}
.shot img{{display:block;width:100%;height:100%;min-height:0;object-fit:contain}}
figcaption{{display:flex;flex-direction:column;align-items:flex-start;gap:{px(7)};min-width:0}}
h3{{font:600 {px(21)}/1.2 {f['sans']};margin:0;max-width:100%;overflow:hidden;overflow-wrap:anywhere;
  display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-clamp:2}}
.chip{{font:{px(15)}/1 {f['mono']};padding:{px(5)} {px(8)};border:1px solid {c['line']};border-radius:{px(5)};background:{c['card']};color:{c['ink']}}}
.chip.approved{{border-color:{c['accent']};color:{c['accent_ink']}}}
.chip.borrowed{{border-style:dashed;border-color:{c['faint']};color:{c['soft']};background:transparent}}
.bar{{flex:none;height:{px(84)};display:flex;align-items:center;justify-content:space-between;gap:{px(24)};padding:0 {px(28)};color:{c['bar_fg']}}}
.bar b{{font:700 {px(26)}/1.1 {f['sans']};min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}}
.bar span{{flex:none;font:{px(24)}/1 {f['mono']};color:{c['bar_url']};white-space:nowrap}}
"""
    # Rough share of the grid the cards fill; the page script does the exact sizing.
    grid_h = h - 373 * k
    card_h = cell_w * max(ratios) + 18 * k + 77 * k
    slack = max(0.0, 1 - rows * card_h / grid_h) if grid_h > 0 else 0.0
    count = (f"{n_items} role model{'s' if n_items != 1 else ''} · "
             f"{filled} kind{'s' if filled != 1 else ''} of work")
    page = (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width={w}">'
            f"<title>{esc(title)}</title>\n<style>{css}</style></head><body>\n"
            f'<div class="canvas" data-canvas="{w}x{h}"><div class="paper">\n'
            f"<h1>{esc(title)}</h1>\n<p class=\"count\">{count}</p>\n"
            f'<div class="filters">{"".join(chips)}</div>\n'
            f'<div class="grid" data-cols="{cols}">{"".join(cards)}</div>\n</div>\n{bar}\n</div>\n'
            f"<script>{SHEET_JS}</script>\n</body></html>\n")
    return page, slack


# Cards share one height: the tallest chosen image's shape, capped by the space
# the canvas leaves. An image taller than its card is cropped from the top down;
# every other image is shown whole. Without JavaScript the CSS fallback above
# shows every image whole in equal cells.
SHEET_JS = """
(function(){
  var grid=document.querySelector('.grid'); if(!grid) return;
  var figs=[].slice.call(grid.children); if(!figs.length) return;
  var cols=+grid.getAttribute('data-cols')||1, rows=Math.ceil(figs.length/cols);
  var gs=getComputedStyle(grid), gapY=parseFloat(gs.rowGap)||0;
  var figGap=parseFloat(getComputedStyle(figs[0]).rowGap)||0;
  var shot0=figs[0].querySelector('.shot'), ss=getComputedStyle(shot0);
  var padY=parseFloat(ss.paddingTop)+parseFloat(ss.paddingBottom)+parseFloat(ss.borderTopWidth)+parseFloat(ss.borderBottomWidth);
  var padX=parseFloat(ss.paddingLeft)+parseFloat(ss.paddingRight)+parseFloat(ss.borderLeftWidth)+parseFloat(ss.borderRightWidth);
  var capH=Math.max.apply(null, figs.map(function(f){return f.querySelector('figcaption').offsetHeight;}));
  var maxR=Math.max.apply(null, figs.map(function(f){return +f.getAttribute('data-ratio')||1;}));
  var cellW=figs[0].clientWidth, innerW=cellW-padX;
  var avail=(grid.clientHeight-(rows-1)*gapY)/rows-capH-figGap;
  var shotH=Math.max(40, Math.min(avail, innerW*maxR+padY));
  var innerR=(shotH-padY)/innerW;
  grid.style.gridTemplateRows='repeat('+rows+',auto)';
  figs.forEach(function(f){
    var s=f.querySelector('.shot'), img=s.querySelector('img'), r=+f.getAttribute('data-ratio')||1;
    s.style.flex='none'; s.style.height=shotH+'px';
    if(r>innerR*1.04){img.style.objectFit='cover'; img.style.objectPosition='top';}
  });
})();
"""


def chrome_command() -> str:
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if sys.platform == "darwin" and Path(mac).exists():
        return f'"{mac}"'
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        if shutil.which(name):
            return name
    return "chrome"


def build_sheet(manifest: Path, out: Path, ids: list[str], theme: str, size: str, cols: int) -> Path:
    data = validated(manifest)
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise GalleryError("The sheet embeds images, which needs Pillow. Install it with: pip install pillow") from None
    page, slack = render_sheet(data, manifest.parent, ids, theme, size, cols)
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    write_text(out, page)
    w, h = parse_size(size)
    print(f"Wrote {out} ({len(ids)} role models, {theme}, {w}x{h})")
    if slack > 0.3:
        print(f"Tip: {len(ids)} items leave much of this {w}x{h} canvas empty. "
              "Add items, or try --size 1080x1080 or a different --cols.")
    png = out.with_suffix(".png")
    print(f"To make a PNG, open it and screenshot the {w}x{h} canvas, or run: {chrome_command()} --headless=new "
          f"--hide-scrollbars --window-size={w},{h} --screenshot=\"{png}\" \"{out.as_uri()}\"")
    return out


# --------------------------------------------------------------------------- cli


def open_in_browser(path: Path) -> None:
    """Fail soft: a missing opener is a note, not an error."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=True, timeout=30)
        elif os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]  # what `start` does
        else:
            subprocess.run(["xdg-open", str(path)], check=True, timeout=30)
    except Exception as exc:
        print(f"Could not open a browser ({exc}). Open this file yourself: {path}", file=sys.stderr)


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="build_gallery.py",
        description="Build a house style gallery page from house-style/role-models/manifest.json.",
        epilog="The manifest schema is documented at the top of this file.")
    p.add_argument("--root", type=Path,
                   help="project folder that holds house-style/ (default: current folder)")
    p.add_argument("--manifest", type=Path, help="use this manifest instead of <root>/house-style/role-models/manifest.json")
    p.add_argument("--check", action="store_true", help="validate the manifest only; exit 1 on problems")
    p.add_argument("--open", action="store_true", help="open the result in your default browser")
    p.add_argument("--sheet", type=Path, metavar="OUT.html", help="draw the gallery as a fixed-size graphic")
    p.add_argument("--ids", help="comma-separated item ids for --sheet, in grid order")
    p.add_argument("--theme", choices=("light", "dark"), default="light", help="sheet colors (default: light)")
    p.add_argument("--size", default="1080x1350", help="sheet canvas in pixels (default: 1080x1350)")
    p.add_argument("--cols", type=int, default=3, help="sheet grid columns (default: 3)")
    return p.parse_args(argv)


def default_manifest(root) -> Path:
    """<root>/house-style/role-models/manifest.json. With no --root, fall back to the
    manifest beside this script (house-style/build_gallery.py or scripts/build_gallery.py)."""
    first = (root or Path(".")) / DEFAULT_MANIFEST
    if root is not None or first.is_file():
        return first
    here = Path(__file__).resolve().parent
    for candidate in (here / "role-models" / "manifest.json", here.parent / DEFAULT_MANIFEST):
        if candidate.is_file():
            return candidate
    return first


def main(argv=None) -> int:
    args = parse_args(argv)
    manifest = args.manifest if args.manifest else default_manifest(args.root)
    try:
        if args.check:
            data = validated(manifest)
            filled = len({i["surface"] for i in data["items"]})
            print(f"Manifest OK: {len(data['items'])} role models, "
                  f"{filled} of {len(data['surfaces'])} kinds of work covered.")
            return 0
        if args.sheet:
            if not args.ids:
                raise GalleryError("--sheet needs --ids, for example --ids chart-a,chart-b,chart-c.")
            ids = [i.strip() for i in args.ids.split(",") if i.strip()]
            out = build_sheet(manifest, args.sheet, ids, args.theme, args.size, args.cols)
        else:
            if args.ids:
                raise GalleryError("--ids only works with --sheet.")
            out = build_page(manifest)
    except GalleryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.open:
        open_in_browser(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
