"""Tests for scripts/check_page.py.

The first group is offline: no network, no browser. The browser tests at the
end run only when Playwright and its Chromium are installed, and skip
otherwise.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("check_page", KIT / "scripts" / "check_page.py")
cp = importlib.util.module_from_spec(_spec)
sys.modules["check_page"] = cp
_spec.loader.exec_module(cp)


def result(width=390, inner=None, page=None, wide=(), small=()):
    return {"width": width, "innerWidth": width if inner is None else inner,
            "pageWidth": width if page is None else page, "wide": list(wide),
            "smallCount": len(small), "small": list(small)}


# ---------------------------------------------------------------- offline

def test_parse_widths_reads_a_list():
    assert cp.parse_widths("390,768,1440") == [390, 768, 1440]
    assert cp.parse_widths(" 390px , 1024 ") == [390, 1024]


@pytest.mark.parametrize("bad", ["", "abc", "390,,768", "100", "9000", "390.5"])
def test_parse_widths_refuses_nonsense(bad):
    with pytest.raises(ValueError):
        cp.parse_widths(bad)


def test_target_url_keeps_web_addresses():
    assert cp.target_url("https://example.com/a?b=1") == "https://example.com/a?b=1"


def test_target_url_turns_a_file_into_a_file_address(tmp_path):
    f = tmp_path / "my page.html"
    f.write_text("<p>hi</p>")
    url = cp.target_url(str(f))
    assert url.startswith("file://") and url.endswith("my%20page.html")


def test_target_url_refuses_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        cp.target_url(str(tmp_path / "nope.html"))


def test_phones_get_a_phone():
    phone = cp.device_for(390)
    assert phone["is_mobile"] and phone["has_touch"] and phone["viewport"]["width"] == 390
    assert "Mobile" in phone["user_agent"]  # sites that choose their layout by browser serve the phone one
    laptop = cp.device_for(1440)
    assert "is_mobile" not in laptop and "user_agent" not in laptop and laptop["viewport"]["width"] == 1440


@pytest.mark.parametrize("bad", [0, -3, float("nan"), float("inf")])
def test_min_text_must_be_a_positive_number(bad):
    with pytest.raises(ValueError):
        cp.parse_min_text(bad)


def test_main_rejects_a_bad_min_text_with_exit_2(tmp_path):
    f = tmp_path / "p.html"
    f.write_text("<p>hi</p>")
    assert cp.main([str(f), "--min-text", "nan"]) == 2


def test_fits_needs_both_the_page_and_the_window_to_match():
    assert cp.fits(result())
    assert not cp.fits(result(page=430))           # content wider than the screen
    assert not cp.fits(result(inner=487, page=487))  # a phone that zoomed out to show it all


def test_exit_code_fails_on_any_width():
    assert cp.exit_code([result(), result(width=768)]) == 0
    assert cp.exit_code([result(), result(width=768, page=812)]) == 1


def test_report_names_what_sticks_out_and_says_hidden():
    r = result(width=768, page=812, wide=[{"element": "span.tip", "right": 812, "hidden": True, "text": "More info"}],
               small=[{"element": "p.note", "size": 9, "text": "Source: survey"}])
    text = cp.format_report("page.html", [result(), r], 11)
    assert "390px  fits" in text
    assert "TOO WIDE: the page is 812px wide on a 768px screen" in text
    assert 'span.tip "More info" (right edge 812px, hidden)' in text
    assert "text under 11px: 1, smallest 9px" in text
    assert "display:none" in text


def test_report_says_all_widths_fit():
    assert cp.format_report("page.html", [result(), result(width=1440)], 11).endswith("All widths fit.")


def test_main_rejects_a_missing_file_with_exit_2(tmp_path, capsys):
    assert cp.main([str(tmp_path / "missing.html")]) == 2
    assert "no such file" in capsys.readouterr().err


def test_main_rejects_bad_widths_with_exit_2(tmp_path, capsys):
    f = tmp_path / "p.html"
    f.write_text("<p>hi</p>")
    assert cp.main([str(f), "--widths", "tiny"]) == 2


# ---------------------------------------------------------------- browser

def _browser_or_skip():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright isn't installed")
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception as exc:  # name the real reason, so a broken setup isn't mistaken for a missing one
        pytest.skip(f"Chromium couldn't start here: {cp._first_line(exc)}")


PAGE = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{margin:0;font:16px sans-serif}} .wrap{{padding:16px}} {extra}</style></head>
<body><div class="wrap"><h1>Title</h1><p>Body copy.</p>{body}</div></body></html>"""


def test_a_page_that_fits_passes(tmp_path):
    _browser_or_skip()
    f = tmp_path / "ok.html"
    f.write_text(PAGE.format(extra="", body=""))
    results = cp.check(cp.target_url(str(f)), [390, 1024], 11, tmp_path / "shots", False)
    assert cp.exit_code(results) == 0
    assert (tmp_path / "shots" / "ok-390.png").is_file()


def test_an_invisible_tooltip_that_widens_the_phone_is_caught(tmp_path):
    _browser_or_skip()
    f = tmp_path / "tip.html"
    f.write_text(PAGE.format(extra=".tip{position:absolute;left:300px;width:300px;opacity:0}",
                             body='<span class="tip">Hidden help text</span>'))
    results = cp.check(cp.target_url(str(f)), [390], 11, None, False)
    assert cp.exit_code(results) == 1
    wide = results[0]["wide"]
    assert any(e["element"] == "span.tip" and e["hidden"] for e in wide)


def test_sideways_scrollers_are_allowed(tmp_path):
    _browser_or_skip()
    f = tmp_path / "scroller.html"
    f.write_text(PAGE.format(extra=".row{overflow-x:auto;white-space:nowrap} .row span{display:inline-block;width:300px}",
                             body='<div class="row"><span>a</span><span>b</span><span>c</span></div>'))
    assert cp.exit_code(cp.check(cp.target_url(str(f)), [390], 11, None, False)) == 0


def test_a_tooltip_that_escapes_a_scroller_is_still_caught(tmp_path):
    # The scroller isn't positioned, so the absolute tooltip is placed against the page, not clipped by it.
    _browser_or_skip()
    f = tmp_path / "escape.html"
    f.write_text(PAGE.format(extra=".row{overflow-x:auto} .tip{position:absolute;left:300px;width:300px;opacity:0}",
                             body='<div class="row"><span class="tip">Help</span></div>'))
    results = cp.check(cp.target_url(str(f)), [390], 11, None, False)
    assert cp.exit_code(results) == 1
    assert any(e["element"] == "span.tip" for e in results[0]["wide"])


def test_a_tooltip_inside_a_positioned_scroller_is_allowed(tmp_path):
    _browser_or_skip()
    f = tmp_path / "contained.html"
    f.write_text(PAGE.format(extra=".row{position:relative;overflow-x:auto;height:40px} .tip{position:absolute;left:300px;width:300px}",
                             body='<div class="row"><span class="tip">Help</span></div>'))
    assert cp.exit_code(cp.check(cp.target_url(str(f)), [390], 11, None, False)) == 0


def test_small_text_counts_a_child_made_visible_and_text_on_the_page_itself(tmp_path):
    _browser_or_skip()
    f = tmp_path / "vis.html"
    f.write_text('<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                 '<style>body{font-size:9px;margin:0} .off{visibility:hidden} .on{visibility:visible;font-size:8px}</style></head>'
                 '<body>Loose text<div class="off"><span class="on">Shown again</span></div></body></html>')
    small = cp.check(cp.target_url(str(f)), [390], 11, None, False)[0]["small"]
    found = {e["text"] for e in small}
    assert "Shown again" in found and any(t.startswith("Loose text") for t in found)


def test_an_error_page_is_not_reported_as_fitting(tmp_path):
    _browser_or_skip()
    import http.server, threading
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp_path), **k)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/missing.html"
        with pytest.raises(cp.CheckError, match="HTTP 404"):
            cp.check(url, [390], 11, None, False)
        assert cp.main([url, "--no-shots"]) == 2
    finally:
        server.shutdown()


def test_an_unreachable_address_exits_2_without_a_traceback(capsys):
    _browser_or_skip()
    assert cp.main(["http://127.0.0.1:9/", "--no-shots", "--widths", "390"]) == 2
    assert "Couldn't open" in capsys.readouterr().err


def test_small_text_is_counted_but_does_not_fail(tmp_path):
    _browser_or_skip()
    f = tmp_path / "small.html"
    f.write_text(PAGE.format(extra=".fine{font-size:9px}", body='<p class="fine">Source: a survey</p>'))
    results = cp.check(cp.target_url(str(f)), [390], 11, None, False)
    assert cp.exit_code(results) == 0
    assert results[0]["smallCount"] == 1 and results[0]["small"][0]["size"] == 9
