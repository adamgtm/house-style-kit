#!/usr/bin/env python3
"""Check a page the way people will see it: on a phone, a tablet and a laptop.

Most layout bugs are invisible in the code and obvious on a phone. Some don't
show in a screenshot either. A tooltip hidden with opacity still takes up
room, so the page runs wider than the phone and the browser quietly zooms
out. This script measures instead of looking.

For each width it reports:
  - whether the page fits the screen, and if it doesn't, the elements that
    stick out past it (hidden ones included, because they cause it too);
  - text set smaller than a minimum size (default 11px);
and saves a screenshot, so you can look as well.

Usage
-----
  python3 house-style/check_page.py page.html
  python3 house-style/check_page.py https://example.com/pricing
  python3 house-style/check_page.py page.html --widths 390,768,1440
  python3 house-style/check_page.py page.html --min-text 12 --out checks --full
  python3 house-style/check_page.py page.html --json

Widths under 600px get a phone: a touch screen, a mobile viewport and 2x
pixels, so the page behaves the way it does in someone's hand.

Exit code: 0 when the page fits at every width, 1 when it runs wider than the
screen at any width, 2 when it can't be checked (a bad path, an error page,
a timeout, no browser). Small text is reported but doesn't fail the check.

Limits: it checks the right edge, where overflow makes a page scroll
sideways. Content cut off on the left, or an element shrunk with a transform,
can still slip past. That's what the screenshots are for.

Needs Playwright and a browser, once:
  pip install playwright
  python3 -m playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

DEFAULT_WIDTHS = (390, 768, 1440)
PHONE_MAX = 600
MIN_WIDTH, MAX_WIDTH = 240, 3840
# Phones identify as a phone, so sites that pick their layout by browser get the mobile one.
PHONE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36")

INSTALL_HELP = """This check needs Playwright and a browser. Install them once:
  pip install playwright
  python3 -m playwright install chromium"""

LAUNCH_HELP = """The browser couldn't start. Two usual causes:
  - It isn't installed yet: python3 -m playwright install chromium
  - Something is blocking it, like an agent's sandbox: run this check outside the sandbox."""


class CheckError(RuntimeError):
    """The page couldn't be checked: no browser, an error page, a timeout."""

# Runs in the page. Measures one width: page width, what sticks out, small text.
MEASURE_JS = r"""([width, minText]) => {
  const name = e => {
    let s = e.tagName.toLowerCase();
    if (e.id) s += '#' + e.id;
    const cls = (typeof e.className === 'string' ? e.className : '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
    if (cls.length) s += '.' + cls.join('.');
    return s;
  };
  // Visibility is inherited, so the element's own value already counts its parents
  // (and a child can turn itself visible again). Opacity isn't, so walk up for it.
  const isHidden = e => {
    if (getComputedStyle(e).visibility !== 'visible') return true;
    for (let p = e; p && p.nodeType === 1; p = p.parentElement) {
      if (parseFloat(getComputedStyle(p).opacity) === 0) return true;
    }
    return false;
  };
  // The box an element is positioned against. An absolutely positioned element
  // ignores every ancestor until the nearest positioned one.
  const containingBlock = e => {
    if (getComputedStyle(e).position !== 'absolute') return e.parentElement;
    for (let p = e.parentElement; p; p = p.parentElement) {
      if (getComputedStyle(p).position !== 'static') return p;
    }
    return document.documentElement;
  };
  // Inside a box that scrolls or clips sideways, overflow is on purpose. The box
  // only clips the element if the element's containing block sits inside it.
  const insideScroller = e => {
    const cb = containingBlock(e);
    for (let p = e.parentElement; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if ((o === 'auto' || o === 'scroll' || o === 'hidden' || o === 'clip') && (p === cb || p.contains(cb))) return true;
    }
    return false;
  };
  const right = e => e.getBoundingClientRect().right + window.scrollX;
  const snippet = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40);

  const doc = document.documentElement;
  const pageWidth = Math.max(doc.scrollWidth, document.body ? document.body.scrollWidth : 0);
  const candidates = [];
  for (const e of document.querySelectorAll('body *')) {
    const s = getComputedStyle(e);
    if (s.display === 'none' || s.position === 'fixed') continue;
    const b = e.getBoundingClientRect();
    if (b.width === 0 && b.height === 0) continue;
    if (right(e) <= width + 1 || insideScroller(e)) continue;
    const parent = e.parentElement;
    const parentOut = parent && parent !== document.body && right(parent) > width + 1;
    candidates.push({element: name(e), right: Math.round(right(e)), hidden: isHidden(e), text: snippet(e), culprit: !parentOut});
  }
  // The culprits are elements that stick out of a parent that fits.
  let wide = candidates.filter(c => c.culprit);
  if (!wide.length) wide = candidates.slice().sort((a, b) => b.right - a.right);
  wide = wide.slice(0, 8).map(({culprit, ...rest}) => rest);

  const small = [];
  for (const e of document.querySelectorAll('body, body *')) {
    const own = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own) continue;
    const s = getComputedStyle(e);
    if (s.display === 'none') continue;
    const b = e.getBoundingClientRect();
    if (b.width === 0 || b.height === 0 || isHidden(e)) continue;
    const size = parseFloat(s.fontSize);
    if (size < minText) small.push({element: name(e), size: Math.round(size * 10) / 10, text: snippet(e)});
  }
  small.sort((a, b) => a.size - b.size);

  return {width, innerWidth: window.innerWidth, pageWidth, wide, smallCount: small.length, small: small.slice(0, 5)};
}"""


def parse_widths(text: str) -> list[int]:
    """'390,768,1440' -> [390, 768, 1440]. Raises ValueError on anything else."""
    widths = []
    for part in text.split(","):
        part = part.strip().lower().removesuffix("px")
        if not part.isdigit():
            raise ValueError(f"widths are whole numbers of pixels, like 390,768,1440 (got {text!r})")
        w = int(part)
        if not MIN_WIDTH <= w <= MAX_WIDTH:
            raise ValueError(f"each width must be between {MIN_WIDTH} and {MAX_WIDTH} pixels (got {w})")
        widths.append(w)
    if not widths:
        raise ValueError("give at least one width")
    return widths


def target_url(arg: str) -> str:
    """A web address stays as it is; a file path becomes a file:// address."""
    if arg.startswith(("http://", "https://", "file://")):
        return arg
    path = Path(arg).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {arg}")
    return path.resolve().as_uri()


def device_for(width: int) -> dict:
    """Browser settings for one width. Under PHONE_MAX, behave like a phone."""
    if width < PHONE_MAX:
        return {"viewport": {"width": width, "height": 844}, "device_scale_factor": 2, "is_mobile": True,
                "has_touch": True, "user_agent": PHONE_UA}
    return {"viewport": {"width": width, "height": 1024 if width < 1024 else 900}}


def parse_min_text(value: float) -> float:
    """The smallest text size to allow, in pixels. Raises ValueError unless finite and positive."""
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"--min-text must be a positive number of pixels (got {value})")
    return value


def fits(result: dict) -> bool:
    """The page fits when nothing makes it wider than the screen.

    On a phone, a too-wide page makes the browser zoom out, which shows up as
    a window wider than the width asked for.
    """
    return result["pageWidth"] <= result["width"] and result["innerWidth"] == result["width"]


def exit_code(results: list[dict]) -> int:
    return 0 if all(fits(r) for r in results) else 1


def format_report(target: str, results: list[dict], min_text: float) -> str:
    lines = [target]
    for r in results:
        w = r["width"]
        label = f"{w}px".ljust(7)
        shot = f"  ·  {r['screenshot']}" if r.get("screenshot") else ""
        if fits(r):
            lines.append(f"  {label}fits{shot}")
        else:
            page = max(r["pageWidth"], r["innerWidth"])
            lines.append(f"  {label}TOO WIDE: the page is {page}px wide on a {w}px screen{shot}")
            if r["wide"]:
                lines.append("         sticks out:")
                for e in r["wide"]:
                    hid = ", hidden" if e["hidden"] else ""
                    txt = f' "{e["text"]}"' if e["text"] else ""
                    lines.append(f"           {e['element']}{txt} (right edge {e['right']}px{hid})")
        if r["smallCount"]:
            ex = r["small"][0]
            lines.append(f"         text under {min_text:g}px: {r['smallCount']}, smallest {ex['size']:g}px "
                         f'({ex["element"]} "{ex["text"]}")')
    bad = [r["width"] for r in results if not fits(r)]
    lines.append("All widths fit." if not bad else
                 "Fix what sticks out, then run this again. Hidden elements count: hide them with display:none, not opacity.")
    return "\n".join(lines)


def _first_line(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return f"{exc.__class__.__name__}: {text[0] if text else ''}"


def check(target: str, widths: list[int], min_text: float, out: Path | None, full: bool) -> list[dict]:
    """Open the page once per width and measure it. Raises CheckError when it can't."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise CheckError(INSTALL_HELP)
    results = []
    stem = Path(target.rstrip("/").split("/")[-1].split("?")[0] or "page").stem or "page"
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            raise CheckError(f"{LAUNCH_HELP}\n({_first_line(exc)})")
        try:
            for w in widths:
                ctx = browser.new_context(**device_for(w))
                try:
                    page = ctx.new_page()
                    try:
                        response = page.goto(target, wait_until="load", timeout=60000)
                    except Exception as exc:
                        raise CheckError(f"Couldn't open {target} at {w}px. ({_first_line(exc)})")
                    if response is not None and response.status >= 400:
                        raise CheckError(f"{target} answered with an error page (HTTP {response.status}), "
                                         "so there's nothing to check.")
                    try:
                        page.evaluate("document.fonts ? document.fonts.ready.then(() => true) : true")
                        page.wait_for_timeout(600)
                        r = page.evaluate(MEASURE_JS, [w, min_text])
                        if out is not None:
                            out.mkdir(parents=True, exist_ok=True)
                            shot = out / f"{stem}-{w}.png"
                            page.screenshot(path=str(shot), full_page=full)
                            r["screenshot"] = str(shot)
                    except CheckError:
                        raise
                    except Exception as exc:
                        raise CheckError(f"Couldn't measure {target} at {w}px. ({_first_line(exc)})")
                    results.append(r)
                finally:
                    ctx.close()
        finally:
            browser.close()
    return results


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Check a page at phone, tablet and laptop widths: does it fit the screen, and is any text too small?")
    p.add_argument("target", help="an HTML file or a web address")
    p.add_argument("--widths", default=",".join(str(w) for w in DEFAULT_WIDTHS),
                   help="comma-separated screen widths in pixels (default: 390,768,1440)")
    p.add_argument("--min-text", type=float, default=11, help="flag text smaller than this many pixels (default: 11)")
    p.add_argument("--out", type=Path, default=Path("checks"), help="folder for the screenshots (default: ./checks)")
    p.add_argument("--no-shots", action="store_true", help="measure only, save no screenshots")
    p.add_argument("--full", action="store_true", help="screenshot the whole page, not just the first screen")
    p.add_argument("--json", action="store_true", help="print the measurements as JSON")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        widths = parse_widths(args.widths)
        min_text = parse_min_text(args.min_text)
        target = target_url(args.target)
    except (ValueError, FileNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        results = check(target, widths, min_text, None if args.no_shots else args.out, args.full)
    except CheckError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(results, indent=1) if args.json else format_report(args.target, results, min_text))
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
