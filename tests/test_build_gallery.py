"""Offline tests for scripts/build_gallery.py. No network, no browser."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
EXAMPLE = KIT / "examples" / "role-models" / "manifest.json"
TEMPLATE = KIT / "templates" / "house-style" / "role-models" / "manifest.json"

_spec = importlib.util.spec_from_file_location("build_gallery", KIT / "scripts" / "build_gallery.py")
bg = importlib.util.module_from_spec(_spec)
sys.modules["build_gallery"] = bg
_spec.loader.exec_module(bg)

# A valid 1x1 PNG, so tests that only need a file on disk don't need Pillow.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def make_gallery(folder: Path, items=None, surfaces=None, files=("a.png",), **extra) -> Path:
    """Write a small manifest (plus image files) into folder and return its path."""
    folder.mkdir(parents=True, exist_ok=True)
    for rel in files:
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(PNG)
    if surfaces is None:
        surfaces = [{"id": "social", "group": "Graphics", "name": "Social graphics"},
                    {"id": "email", "group": "Email", "name": "Email", "gap": "Add an email you were proud of."}]
    if items is None:
        items = [{"id": "a", "surface": "social", "title": "Launch chart", "file": "a.png", "status": "approved"}]
    data = {"title": "Test gallery", "brand": {"name": "Test Co", "url": "test.example"},
            "surfaces": surfaces, "items": items, **extra}
    path = folder / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def run(*args) -> int:
    return bg.main([str(a) for a in args])


# --------------------------------------------------------------------------- check


def test_check_passes_on_example(capsys):
    assert run("--check", "--manifest", EXAMPLE) == 0
    assert "Manifest OK: 3 role models" in capsys.readouterr().out


def test_check_passes_on_starter_template(capsys):
    assert run("--check", "--manifest", TEMPLATE) == 0
    assert "0 role models, 0 of 5 kinds of work" in capsys.readouterr().out


def test_check_fails_on_missing_file(tmp_path, capsys):
    m = make_gallery(tmp_path, items=[
        {"id": "a", "surface": "social", "title": "A", "file": "nope.png", "status": "approved"}])
    assert run("--check", "--manifest", m) == 1
    err = capsys.readouterr().err
    assert 'item "a": file not found: nope.png' in err
    assert "relative to the manifest's folder" in err


def test_check_fails_on_missing_dark_file(tmp_path, capsys):
    m = make_gallery(tmp_path, items=[
        {"id": "a", "surface": "social", "title": "A", "file": "a.png", "dark": "a-dark.png", "status": "shipped"}])
    assert run("--check", "--manifest", m) == 1
    assert "dark not found: a-dark.png" in capsys.readouterr().err


def test_check_fails_on_duplicate_id(tmp_path, capsys):
    item = {"id": "a", "surface": "social", "title": "A", "file": "a.png", "status": "approved"}
    m = make_gallery(tmp_path, items=[item, dict(item)])
    assert run("--check", "--manifest", m) == 1
    assert 'duplicate item id "a"' in capsys.readouterr().err


def test_check_fails_on_unknown_surface(tmp_path, capsys):
    m = make_gallery(tmp_path, items=[
        {"id": "a", "surface": "decks", "title": "A", "file": "a.png", "status": "approved"}])
    assert run("--check", "--manifest", m) == 1
    err = capsys.readouterr().err
    assert 'unknown surface "decks"' in err
    assert "Known surfaces: email, social" in err


def test_check_fails_on_missing_required_fields_and_bad_status(tmp_path, capsys):
    m = make_gallery(tmp_path,
                     surfaces=[{"id": "social", "name": "Social"}],
                     items=[{"id": "a", "surface": "social", "file": "a.png", "status": "loved"}])
    assert run("--check", "--manifest", m) == 1
    err = capsys.readouterr().err
    assert 'surface "social" is missing "group"' in err
    assert 'item "a" is missing "title"' in err
    assert 'status "loved" should be one of: approved, shipped, borrowed' in err


def test_check_rejects_unsafe_url_and_absolute_path(tmp_path, capsys):
    m = make_gallery(tmp_path, items=[
        {"id": "a", "surface": "social", "title": "A", "file": str(tmp_path / "a.png"),
         "status": "approved", "where": "Blog", "url": "javascript:alert(1)"}])
    assert run("--check", "--manifest", m) == 1
    err = capsys.readouterr().err
    assert "should be relative to the manifest folder" in err
    assert "should start with http://, https:// or mailto:" in err


def test_check_reports_bad_json_plainly(tmp_path, capsys):
    m = tmp_path / "manifest.json"
    m.write_text('{"surfaces": [], "items": [],}', encoding="utf-8")
    assert run("--check", "--manifest", m) == 1
    assert "is not valid JSON" in capsys.readouterr().err


def test_missing_manifest_is_a_clear_error(tmp_path, capsys):
    assert run("--check", "--root", tmp_path) == 1
    assert "No manifest found" in capsys.readouterr().err


# --------------------------------------------------------------------------- page


def test_page_lists_every_title_and_escapes_html(tmp_path):
    items = [
        {"id": "a", "surface": "social", "title": "Launch chart", "file": "a.png", "status": "approved",
         "words": "Yes. This one.", "why": "One idea.", "where": "LinkedIn", "url": "https://example.com/p"},
        {"id": "b", "surface": "social", "title": "<script>alert(1)</script>", "file": "b.png",
         "status": "borrowed", "note": 'Says "hi" & <b>bye</b>'},
    ]
    m = make_gallery(tmp_path, items=items, files=("a.png", "b.png"))
    assert run("--manifest", m) == 0
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Launch chart" in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert "&lt;b&gt;bye&lt;/b&gt;" in page
    assert '<span class="chip borrowed"' in page
    assert '<span class="chip approved"' in page
    assert "“Yes. This one.”" in page
    assert 'href="https://example.com/p"' in page
    assert "Test Co" in page and "test.example" in page
    # Only the page's own script block, never one from the manifest.
    assert page.count("<script>") == 1


def test_example_page_has_every_item_title():
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    page = bg.render_page(data, EXAMPLE.parent)
    for item in data["items"]:
        assert bg.esc(item["title"]) in page
    assert 'data-src="buyer-waves-dark.png"' in page  # light/dark toggle for the item with a dark file


def test_empty_surface_shows_gap_placeholder(tmp_path):
    m = make_gallery(tmp_path)
    assert run("--manifest", m) == 0
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "No role model yet." in page
    assert "Add an email you were proud of." in page


def test_paths_resolve_relative_to_manifest_folder(tmp_path, monkeypatch):
    project = tmp_path / "project"
    m = make_gallery(project / "house-style" / "role-models",
                     items=[{"id": "a", "surface": "social", "title": "A", "file": "images/a b.png",
                             "status": "shipped"}],
                     files=("images/a b.png",))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert run("--check", "--manifest", m) == 0
    assert run("--root", project) == 0
    page = (m.parent / "index.html").read_text(encoding="utf-8")
    assert 'src="images/a%20b.png"' in page

    # A file that exists next to the current folder but not next to the manifest is still missing.
    (elsewhere / "b.png").write_bytes(PNG)
    m2 = make_gallery(tmp_path / "other", items=[
        {"id": "b", "surface": "social", "title": "B", "file": "b.png", "status": "approved"}], files=())
    assert run("--check", "--manifest", m2) == 1


def test_default_manifest_location_under_root(tmp_path, monkeypatch):
    make_gallery(tmp_path / "house-style" / "role-models")
    monkeypatch.chdir(tmp_path)
    assert run() == 0
    assert (tmp_path / "house-style" / "role-models" / "index.html").is_file()


def test_copy_saved_in_house_style_folder_runs_from_anywhere(tmp_path):
    """START-HERE copies the script to house-style/build_gallery.py; it should find its manifest."""
    import shutil
    import subprocess

    folder = tmp_path / "project" / "house-style"
    make_gallery(folder / "role-models")
    shutil.copy(KIT / "scripts" / "build_gallery.py", folder / "build_gallery.py")
    for cwd in (tmp_path / "project", folder, tmp_path):
        done = subprocess.run([sys.executable, "-B", str(folder / "build_gallery.py"), "--check"],
                              cwd=cwd, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        assert "Manifest OK" in done.stdout


def test_tokens_drive_colors_and_derive_dark(tmp_path):
    m = make_gallery(tmp_path, tokens={"paper": "#fbf8f1", "ink": "#1a1a1a", "accent": "#d94f00",
                                       "sans": "Inter, system-ui, sans-serif"})
    assert run("--manifest", m) == 0
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "--paper:#fbf8f1" in page
    assert "--sans:Inter, system-ui, sans-serif" in page
    dark_block = page.split("@media (prefers-color-scheme: dark)", 1)[1]
    paper = re.search(r"--paper:(#[0-9a-f]{6})", dark_block).group(1)
    assert bg.is_dark(paper)


def test_bad_token_is_a_problem(tmp_path, capsys):
    m = make_gallery(tmp_path, tokens={"paper": "white", "serif": "x;}</style><script>"})
    assert run("--check", "--manifest", m) == 1
    err = capsys.readouterr().err
    assert 'tokens "paper" should be a hex color' in err
    assert 'tokens "serif" should be a font list' in err


# --------------------------------------------------------------------------- sheet


def test_sheet_builds_with_pillow(tmp_path, capsys):
    pytest.importorskip("PIL")
    out = tmp_path / "sheet.html"
    ids = "data-collection-flow,acquisitions-table,buyer-waves"
    assert run("--manifest", EXAMPLE, "--sheet", out, "--ids", ids, "--size", "1080x1350") == 0
    page = out.read_text(encoding="utf-8")
    assert page.count("<figure") == 3
    assert 'data-canvas="1080x1350"' in page
    assert "width:1080px;height:1350px" in page
    assert page.count("data:image/png;base64,") == 3
    assert "3 role models · 3 kinds of work" in page
    assert ">Social graphics<" in page and "Social graphics · " not in page  # chips without counts
    assert "Adam&#x27;s GTM Report (example)" in page and "adamGTM.com" in page
    assert "--screenshot" in capsys.readouterr().out


def test_sheet_dark_uses_dark_files_and_flattens_transparency(tmp_path):
    pytest.importorskip("PIL")
    import io

    from PIL import Image

    folder = tmp_path / "g"
    folder.mkdir()
    Image.new("RGBA", (40, 30), (255, 0, 0, 0)).save(folder / "clear.png")
    Image.new("RGB", (40, 30), (0, 0, 0)).save(folder / "clear-dark.png")
    m = make_gallery(folder, files=(), items=[
        {"id": "c", "surface": "social", "title": "Clear", "file": "clear.png", "dark": "clear-dark.png",
         "status": "approved"}])
    data = json.loads(m.read_text(encoding="utf-8"))

    light, _ = bg.render_sheet(data, folder, ["c"], "light", "800x800", 2)
    uri = re.search(r'src="data:image/png;base64,([^"]+)"', light).group(1)
    with Image.open(io.BytesIO(base64.b64decode(uri))) as im:
        assert im.mode == "RGB" and im.getpixel((5, 5)) == (255, 255, 255)

    dark, _ = bg.render_sheet(data, folder, ["c"], "dark", "800x800", 2)
    uri = re.search(r'src="data:image/png;base64,([^"]+)"', dark).group(1)
    with Image.open(io.BytesIO(base64.b64decode(uri))) as im:
        assert im.getpixel((5, 5)) == (0, 0, 0)


def test_sheet_rejects_unknown_ids_and_bad_size(tmp_path, capsys):
    pytest.importorskip("PIL")
    out = tmp_path / "sheet.html"
    assert run("--manifest", EXAMPLE, "--sheet", out, "--ids", "nope") == 1
    assert "Unknown item ids: nope" in capsys.readouterr().err
    assert run("--manifest", EXAMPLE, "--sheet", out, "--ids", "buyer-waves", "--size", "big") == 1
    assert "--size should look like 1080x1350" in capsys.readouterr().err
    assert run("--manifest", EXAMPLE, "--sheet", out) == 1
    assert "--sheet needs --ids" in capsys.readouterr().err


def test_sheet_without_pillow_says_how_to_install(tmp_path, capsys, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_pil(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("No module named 'PIL'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pil)
    assert run("--manifest", EXAMPLE, "--sheet", tmp_path / "s.html", "--ids", "buyer-waves") == 1
    assert "pip install pillow" in capsys.readouterr().err


# --------------------------------------------------------------------------- review fixes


def item(iid="a", file="a.png", **extra):
    return {"id": iid, "surface": "social", "title": iid.upper(), "file": file, "status": "approved", **extra}


# 1. Image paths can't escape the manifest folder, by ../ or by symlink.

def test_relative_path_outside_manifest_folder_is_refused(tmp_path, capsys):
    (tmp_path / "outside.png").write_bytes(PNG)
    folder = tmp_path / "gallery"
    m = make_gallery(folder, files=(), items=[item(file="../outside.png")])
    assert run("--check", "--manifest", m) == 1
    assert 'file "../outside.png" points outside the manifest folder' in capsys.readouterr().err
    # The sheet refuses it as well, even when called without a --check first.
    data = json.loads(m.read_text(encoding="utf-8"))
    with pytest.raises(bg.GalleryError, match="points outside the manifest folder"):
        bg.render_sheet(data, folder, ["a"])


def test_symlink_leading_outside_is_refused(tmp_path, capsys):
    (tmp_path / "secret.png").write_bytes(PNG)
    folder = tmp_path / "gallery"
    folder.mkdir()
    (folder / "real.png").write_bytes(PNG)
    (folder / "deck.pdf").write_bytes(b"%PDF-1.4")
    try:
        os.symlink(tmp_path / "secret.png", folder / "escape.png")
        os.symlink(folder / "real.png", folder / "alias.png")
        os.symlink(folder / "deck.pdf", folder / "deck.png")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    m = make_gallery(folder, files=(), items=[
        item("escape", "escape.png"), item("alias", "alias.png"), item("deck", "deck.png")])
    assert run("--check", "--manifest", m) == 1
    err = capsys.readouterr().err
    assert 'item "escape": file "escape.png" points outside the manifest folder' in err
    assert 'item "deck": file "deck.png" is a link to "deck.pdf"' in err
    assert 'item "alias"' not in err  # a symlink that stays inside is fine
    data = json.loads(m.read_text(encoding="utf-8"))
    with pytest.raises(bg.GalleryError, match="outside"):
        bg.render_sheet(data, folder, ["escape"])


# 2. URLs with whitespace or control characters are refused, and never linked.

@pytest.mark.parametrize("url", [
    "java\tscript:alert(1)", "java\nscript:alert(1)", "java\rscript:alert(1)",
    "\x01javascript:alert(1)", "java\u200bscript:alert(1)", " javascript:alert(1)"])
def test_url_with_hidden_characters_or_bad_scheme_is_refused(tmp_path, capsys, url):
    m = make_gallery(tmp_path, items=[item(where="Blog", url=url)])
    assert run("--check", "--manifest", m) == 1
    assert "url" in capsys.readouterr().err
    # Even if the page is rendered without a check, the URL never reaches an href.
    page = bg.render_page(json.loads(m.read_text(encoding="utf-8")), tmp_path)
    hrefs = re.findall(r'href="([^"]*)"', page)
    assert hrefs == ["https://test.example"]  # only the footer's brand link


def test_brand_url_with_control_character_is_refused(tmp_path, capsys):
    m = make_gallery(tmp_path, brand={"name": "Test Co", "url": "java\tscript:alert(1)"})
    assert run("--check", "--manifest", m) == 1
    assert "brand url" in capsys.readouterr().err
    page = bg.render_page(json.loads(m.read_text(encoding="utf-8")), tmp_path)
    assert "script:alert" not in "".join(re.findall(r'href="([^"]*)"', page))


def test_safe_urls_still_link(tmp_path):
    m = make_gallery(tmp_path, items=[item("a", where="Post", url=" https://example.com/p "),
                                      item("b", where="Mail", url="mailto:me@example.com"),
                                      item("c", where="Local", url="posts/launch.html")],
                     files=("a.png",))
    assert run("--check", "--manifest", m) == 0
    page = bg.render_page(json.loads(m.read_text(encoding="utf-8")), tmp_path)
    for href in ("https://example.com/p", "mailto:me@example.com", "posts/launch.html"):
        assert f'href="{href}"' in page


# 3. Manifest ids can't collide with each other or with the page's own element ids.

class _Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        self.ids += [v for k, v in attrs if k == "id"]


def test_element_ids_never_collide(tmp_path):
    names = ("lb", "hsg-lightbox", "lightbox", "item-a", "heading-x", "x", "surface-x")
    surfaces = [{"id": n, "group": "G", "name": n} for n in names]
    items = [{"id": "a", "surface": "lb", "title": "A", "file": "a.png", "status": "approved"},
             {"id": "hsg-lightbox-img", "surface": "x", "title": "B", "file": "a.png", "status": "approved"}]
    m = make_gallery(tmp_path, surfaces=surfaces, items=items)
    assert run("--manifest", m) == 0
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    parser = _Ids()
    parser.feed(page)
    assert len(parser.ids) == len(set(parser.ids)), sorted(parser.ids)
    for wanted in re.findall(r"getElementById\('([^']+)'\)", page):
        assert parser.ids.count(wanted) == 1, wanted
    assert 'id="surface-lb"' in page and 'id="item-a"' in page


# 4. Windows-style backslashes are normalized everywhere.

def test_backslash_paths_are_normalized(tmp_path, capsys):
    m = make_gallery(tmp_path, files=("images/a.png", "images/a-dark.png"),
                     items=[item(file="images\\a.png", dark="images\\a-dark.png")])
    assert run("--check", "--manifest", m) == 0
    assert run("--manifest", m) == 0
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'src="images/a.png"' in page and 'data-src="images/a-dark.png"' in page
    assert "images\\" not in page
    if importlib.util.find_spec("PIL"):
        sheet, _ = bg.render_sheet(json.loads(m.read_text(encoding="utf-8")), tmp_path, ["a"], "dark")
        assert sheet.count("data:image/png;base64,") == 1

    bad = make_gallery(tmp_path / "w", files=(), items=[item(file="C:\\work\\a.png")])
    capsys.readouterr()
    assert run("--check", "--manifest", bad) == 1
    assert "not an absolute path" in capsys.readouterr().err


# 5. A file must be an image the browser (and the sheet) can show.

@pytest.mark.parametrize("name", ["deck.pdf", "page.html", "notes.txt", "noextension"])
def test_non_image_file_is_refused(tmp_path, capsys, name):
    m = make_gallery(tmp_path, files=(name,), items=[item(file=name)])
    assert run("--check", "--manifest", m) == 1
    err = capsys.readouterr().err
    assert "is not an image the gallery can show" in err
    assert 'keep the original in "source"' in err


def test_svg_works_on_the_page_and_the_sheet(tmp_path):
    folder = tmp_path / "g"
    folder.mkdir()
    (folder / "logo.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"><rect width="200" height="100"/></svg>',
        encoding="utf-8")
    m = make_gallery(folder, files=(), items=[item(file="logo.svg", source="../originals/logo.ai")])
    assert run("--manifest", m) == 0
    page = (folder / "index.html").read_text(encoding="utf-8")
    assert 'src="logo.svg"' in page
    assert "Source: ../originals/logo.ai" in page  # source may point outside; it is shown, not read
    sheet, _ = bg.render_sheet(json.loads(m.read_text(encoding="utf-8")), folder, ["a"])
    assert "data:image/svg+xml;base64," in sheet and 'data-ratio="0.5000"' in sheet
