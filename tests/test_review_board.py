"""Tests for review-board/: builder and local server. The browser test skips without Playwright."""
import http.client
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")

KIT = Path(__file__).resolve().parents[1]
SK = KIT / "review-board" / "scripts"
sys.path.insert(0, str(SK))
import build_review_board as brb  # noqa: E402
import review_server as rs  # noqa: E402


def make_png(path, color=(200, 80, 40), size=(800, 420)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def write_review(tmp, n_items=2, versions=2, **over):
    items = []
    for i in range(n_items):
        vs = []
        for j in range(versions):
            rel = "img/i%d-v%d.png" % (i, j)
            make_png(tmp / rel, (30 + i * 9 % 200, 60 + j * 40, 90))
            vs.append({"id": "i%d-v%d" % (i, j), "src": rel, "note": "n%d" % j})
        items.append({"id": "item%d" % i, "title": "Item %d" % i, "versions": vs})
    data = {"id": "t-board", "title": "Test round", "sections": [{"name": "Sec", "items": items}]}
    data.update(over)
    (tmp / "review.json").write_text(json.dumps(data))
    return tmp / "review.json"


def test_build_small(tmp_path):
    rj = write_review(tmp_path)
    out, meta, ni, nv = brb.build(rj)
    assert (ni, nv) == (2, 4)
    assert out == tmp_path / "review-board-review"
    for f in ("board.html", "board.css", "board.js", "board-meta.json"):
        assert (out / f).is_file()
    assert len(list((out / "_thumbs").glob("*.jpg"))) == 4
    assert Image.open(next((out / "_thumbs").glob("*.jpg"))).width == 360
    assert "__RB_TOKEN__" in (out / "board.html").read_text()
    assert len(meta["revision"]) == 12


def test_missing_image_and_duplicate_ids(tmp_path):
    rj = write_review(tmp_path)
    d = json.loads(rj.read_text())
    d["sections"][0]["items"][0]["versions"][0]["src"] = "img/nope.png"
    d["sections"][0]["items"][1]["id"] = "item0"
    d["sections"][0]["items"][1]["versions"][0]["id"] = "i0-v1"
    rj.write_text(json.dumps(d))
    with pytest.raises(brb.BoardError) as e:
        brb.build(rj)
    msg = str(e.value)
    assert "image not found: img/nope.png" in msg
    assert "duplicate item id 'item0'" in msg
    assert "duplicate version id 'i0-v1'" in msg
    r = subprocess.run([sys.executable, str(SK / "build_review_board.py"), str(rj)], capture_output=True, text=True)
    assert r.returncode == 2 and "image not found" in r.stderr


def test_item_needs_a_version(tmp_path):
    rj = write_review(tmp_path)
    d = json.loads(rj.read_text())
    d["sections"][0]["items"][0]["versions"] = []
    rj.write_text(json.dumps(d))
    with pytest.raises(brb.BoardError, match="at least one version"):
        brb.build(rj)


def test_200_versions(tmp_path):
    items = []
    for i in range(50):
        vs = []
        for j in range(4):
            rel = "img/%d-%d.png" % (i, j)
            make_png(tmp_path / rel, (i * 4 % 255, j * 60, 120), (600, 340))
            vs.append({"id": "v%d-%d" % (i, j), "src": rel})
        items.append({"id": "it%d" % i, "title": "T%d" % i, "versions": vs})
    (tmp_path / "review.json").write_text(json.dumps({"id": "big", "title": "Big", "sections": [{"name": "S", "items": items}]}))
    out, meta, ni, nv = brb.build(tmp_path / "review.json")
    assert nv == 200 and len(list((out / "_thumbs").glob("*.jpg"))) == 200
    assert sum(f.stat().st_size for f in (out / "_thumbs").iterdir()) < 2_000_000


# ---------- server ----------

class Live:
    def __init__(self, tmp, **kw):
        self.rj = write_review(tmp)
        self.out, self.meta, _, _ = brb.build(self.rj)
        self.srv, self.board = rs.make_server(self.out, **kw)
        self.port = self.board.port
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def fp(self, i):
        return list(self.meta["images"])[i]

    def thumb(self, i):
        return "_thumbs/" + self.fp(i) + ".jpg"

    def req(self, method, path, body=None, headers=None, host=None, raw_len=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest(method, path, skip_host=True)
        c.putheader("Host", host or "127.0.0.1:%d" % self.port)
        for k, v in (headers or {}).items():
            c.putheader(k, v)
        if body is not None or raw_len is not None:
            c.putheader("Content-Length", str(raw_len if raw_len is not None else len(body)))
        c.endheaders()
        if body:
            c.send(body)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def good_headers(self):
        return {"Origin": "http://127.0.0.1:%d" % self.port, "X-RB-Token": self.board.token, "Content-Type": "application/json"}

    def payload(self, **kw):
        p = {"board": "t-board", "revision": self.meta["revision"], "submission_id": "s1",
             "items": [{"id": "item0", "liked": ["i0-v1"], "note": "Keep this.\nTighten the title."}]}
        p.update(kw)
        return json.dumps(p).encode()

    def post(self, body=None, headers=None):
        h = self.good_headers()
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        return self.req("POST", "/api/feedback", body if body is not None else self.payload(), h)

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def live(tmp_path):
    L = Live(tmp_path)
    yield L
    L.close()


def test_serves_page_with_token_and_allowlist(live, tmp_path):
    st, body = live.req("GET", "/")
    assert st == 200 and live.board.token.encode() in body and b"__RB_TOKEN__" not in body
    assert live.req("GET", "/" + live.thumb(0))[0] == 200
    assert live.req("GET", "/img/" + live.fp(0))[0] == 200
    assert live.req("GET", "/img/0")[0] == 404
    assert live.req("GET", "/board-meta.json")[0] == 404
    assert live.req("GET", "/review.json")[0] == 404
    assert live.req("GET", "/../review.json")[0] == 404
    assert live.req("GET", "/_thumbs/../board-meta.json")[0] == 404
    assert live.req("GET", "/img/99")[0] == 404
    assert live.req("GET", "/", host="evil.example:80")[0] == 403


def test_symlink_escape_refused(live, tmp_path):
    secret = tmp_path.parent / ("secret-%d.txt" % os.getpid())
    secret.write_text("top secret")
    thumb = live.out / live.thumb(1)
    thumb.unlink()
    thumb.symlink_to(secret)
    assert live.req("GET", "/" + live.thumb(1))[0] == 404
    css = live.out / "board.css"
    css.unlink()
    css.symlink_to(secret)
    assert live.req("GET", "/board.css")[0] == 404
    # an image swapped for a symlink after the build is refused too
    real = Path(live.meta["images"][live.fp(0)])
    keep = real.read_bytes()
    real.unlink()
    real.symlink_to(secret)
    assert live.req("GET", "/img/" + live.fp(0))[0] == 404
    real.unlink()
    real.write_bytes(keep)
    secret.unlink()


def test_post_refusals(live):
    assert live.post(headers={"Origin": "http://evil.example"})[0] == 403
    assert live.post(headers={"Origin": None})[0] == 403
    assert live.post(headers={"X-RB-Token": "wrong"})[0] == 403
    assert live.post(headers={"X-RB-Token": None})[0] == 403
    assert live.post(headers={"Content-Type": "text/plain"})[0] == 415
    assert live.post(body=b"not json")[0] == 400
    st, _ = live.req("POST", "/api/feedback", b"x", live.good_headers(), raw_len=2 * 1024 * 1024)
    assert st == 413
    assert live.post(body=live.payload(items=[{"id": "ghost", "note": "x"}]))[0] == 400
    assert live.post(body=live.payload(items=[{"id": "item0", "liked": ["nope"]}]))[0] == 400
    assert live.post(body=live.payload(items=[{"id": "item0", "note": "  "}]))[0] == 400
    assert not (Path(live.meta["feedback_dir"])).exists()


def test_stale_revision_409(live):
    st, body = live.post(body=live.payload(revision="old"))
    assert st == 409 and b"rebuilt" in body
    assert not Path(live.meta["feedback_dir"]).exists()


def test_send_writes_json_and_markdown_and_dedupes(live):
    st, body = live.post()
    assert st == 200
    r = json.loads(body)
    fdir = Path(live.meta["feedback_dir"])
    assert fdir == live.rj.parent / "feedback"
    doc = json.loads(Path(r["json"]).read_text())
    assert doc["board"] == "t-board" and doc["items"] == [
        {"id": "item0", "title": "Item 0", "liked": ["i0-v1"], "note": "Keep this.\nTighten the title."}]
    md = Path(r["markdown"]).read_text()
    assert "## Sec" in md and "### Item 0" in md and "Liked: B (`i0-v1`)" in md
    assert "> Keep this.\n> Tighten the title." in md
    st2, body2 = live.post()
    assert st2 == 200 and json.loads(body2)["duplicate"] is True
    assert len(list(fdir.glob("*.json"))) == 1 and len(list(fdir.glob("*.md"))) == 1
    assert not list(fdir.glob("*.tmp")) and not list(fdir.glob(".*.tmp"))
    st3, _ = live.post(body=live.payload(submission_id="s2"))
    assert st3 == 200 and len(list(fdir.glob("*.json"))) == 2


def test_wait_mode_exits_zero_and_prints_markdown(tmp_path):
    rj = write_review(tmp_path)
    p = subprocess.Popen([sys.executable, str(SK / "build_review_board.py"), str(rj), "--serve", "--wait"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    lines = []
    port = None
    t0 = time.time()
    while time.time() - t0 < 15:
        ln = p.stdout.readline()
        lines.append(ln)
        if "Review board ready: http://127.0.0.1:" in ln:
            port = int(ln.split("127.0.0.1:")[1].split("/")[0])
            break
    assert port, lines
    assert 8700 <= port < 8800
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", "/")
    page = c.getresponse().read().decode()
    token = page.split('name="rb-token" content="')[1].split('"')[0]
    rev = json.loads((tmp_path / "review-board-review" / "board-meta.json").read_text())["revision"]
    time.sleep(1.0)  # a delayed send, like a person clicking
    body = json.dumps({"board": "t-board", "revision": rev, "submission_id": "x",
                       "items": [{"id": "item1", "liked": ["i1-v0"], "note": "Cut the subtitle"}]})
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("POST", "/api/feedback", body, {"Origin": "http://127.0.0.1:%d" % port, "X-RB-Token": token, "Content-Type": "application/json"})
    r = c.getresponse()
    assert r.status == 200 and json.loads(r.read())["closed"] is True
    out = p.communicate(timeout=10)[0]
    assert p.returncode == 0
    assert "FEEDBACK RECEIVED" in out and "Cut the subtitle" in out and "### Item 1" in out
    assert list((tmp_path / "feedback").glob("*.md"))


def test_fallback_port_when_preferred_is_busy(tmp_path):
    a = Live(tmp_path)
    try:
        srv2, b2 = rs.make_server(a.out)
        assert b2.port != a.port
        srv2.server_close()
    finally:
        a.close()


# ---------- fix round ----------

def test_thumbs_keyed_by_fingerprint(tmp_path):
    rj = write_review(tmp_path)
    out, meta, _, _ = brb.build(rj)
    names = {p.name for p in (out / "_thumbs").glob("*.jpg")}
    img = tmp_path / "img" / "i0-v0.png"
    assert rs.fingerprint(img) + ".jpg" in names
    # reordering the items keeps each image's thumb name; changing an image changes it
    d = json.loads(rj.read_text())
    d["sections"][0]["items"].reverse()
    rj.write_text(json.dumps(d))
    out2, _, _, _ = brb.build(rj)
    assert {p.name for p in (out2 / "_thumbs").glob("*.jpg")} == names
    old = rs.fingerprint(img)
    make_png(img, (1, 2, 3))
    os.utime(img, ns=(10**18, 10**18))
    assert rs.fingerprint(img) != old
    out3, _, _, _ = brb.build(rj)
    assert old + ".jpg" not in {p.name for p in (out3 / "_thumbs").glob("*.jpg")}


def test_server_rejects_non_string_input(live):
    for items in ([{"id": ["item0"], "note": "x"}], [{"id": {"a": 1}, "note": "x"}],
                  [{"id": "item0", "liked": [["i0-v1"]]}], [{"id": "item0", "liked": [{"a": 1}]}],
                  [{"id": "item0", "liked": [5]}]):
        assert live.post(body=live.payload(items=items))[0] == 400
    assert live.post(body=live.payload(submission_id=["x"]))[0] == 400
    assert live.post(headers={"X-RB-Token": "t\u00e9st"})[0] == 403  # non-ASCII token compares as bytes


def test_catch_all_returns_500_json(live, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(rs, "canonical_feedback", boom)
    st, body = live.post()
    assert st == 500 and json.loads(body)["error"].startswith("internal error")


def test_wait_exits_even_if_client_vanishes(tmp_path, capsys):
    L = Live(tmp_path, wait=True)
    try:
        orig = rs.Handler._json
        def drop(self, code, obj):
            if code == 200:
                raise BrokenPipeError()
            return orig(self, code, obj)
        rs.Handler._json = drop
        try:
            try:
                L.post()
            except http.client.HTTPException:
                pass
        finally:
            rs.Handler._json = orig
        assert L.board.first_send.is_set()
        assert L.board.last is not None
    finally:
        L.close()


def test_duplicate_sets_first_send_in_wait_mode(tmp_path):
    L = Live(tmp_path, wait=True)
    try:
        assert L.post()[0] == 200
        L.board.first_send.clear()
        st, body = L.post()
        assert st == 200 and json.loads(body)["duplicate"] is True
        assert L.board.first_send.is_set()
    finally:
        L.close()


def test_closed_round_410_but_duplicate_gets_stored_response(tmp_path):
    L = Live(tmp_path, wait=True)
    try:
        assert L.post()[0] == 200
        assert L.post(body=L.payload(submission_id="other"))[0] == 410
        assert L.post()[0] == 200
        assert len(list(Path(L.meta["feedback_dir"]).glob("*.json"))) == 1
    finally:
        L.close()


def test_failed_json_write_leaves_no_orphan_and_retry_makes_one(live, monkeypatch):
    real = rs.atomic_write
    real_link = rs.link_exclusive
    calls = {"n": 0}
    def flaky(tmp, final):
        if str(final).endswith(".json") and calls["n"] == 0:
            calls["n"] += 1
            raise OSError("disk full")
        return real_link(tmp, final)
    monkeypatch.setattr(rs, "link_exclusive", flaky)
    assert live.post()[0] == 500
    fdir = Path(live.meta["feedback_dir"])
    assert not list(fdir.glob("*.md")) and not list(fdir.glob("*.json"))
    assert live.post()[0] == 200
    assert len(list(fdir.glob("*.json"))) == 1 and len(list(fdir.glob("*.md"))) == 1


def test_feedback_names_are_exclusive_and_carry_submission_id(live):
    doc = rs.canonical_feedback(live.meta, json.loads(live.payload()), "2026-10-28T10:00:00Z")
    results = []
    def go():
        results.append(rs.write_feedback(live.meta, doc))
    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    paths = {r[0] for r in results}
    assert len(paths) == 8 and all("__s1" in p.name for p in paths)
    assert len(list(Path(live.meta["feedback_dir"]).glob("*.md"))) == 8


def test_default_out_dir_per_manifest_and_force(tmp_path):
    rj = write_review(tmp_path)
    out_a, *_ = brb.build(rj)
    other = tmp_path / "other.json"
    d = json.loads(rj.read_text())
    d["id"] = "other-board"
    other.write_text(json.dumps(d))
    out_b, *_ = brb.build(other)
    assert out_a != out_b and out_b.name == "review-board-other"
    with pytest.raises(brb.BoardError, match="already holds board"):
        brb.build(other, out_dir=out_a)
    brb.build(other, out_dir=out_a, force=True)


def test_server_refuses_another_board_in_its_folder(live, tmp_path):
    other = json.loads((tmp_path / "review.json").read_text())
    other["id"] = "intruder"
    (tmp_path / "x.json").write_text(json.dumps(other))
    brb.build(tmp_path / "x.json", out_dir=live.out, force=True)
    st, body = live.post()
    assert st == 409 and b"Another board" in body
    assert live.req("GET", "/")[0] == 409
    assert not Path(live.meta["feedback_dir"]).exists()


def test_stale_image_url_404_after_rebuild(live, tmp_path):
    fp = live.fp(0)
    real = Path(live.meta["images"][fp])
    make_png(real, (9, 9, 9))
    os.utime(real, ns=(2 * 10**18, 2 * 10**18))
    assert live.req("GET", "/img/" + fp)[0] == 404


# ---------- file mode ----------

def file_payload(meta, sid="sid-1", **over):
    p = {"board": meta["board_id"], "revision": meta["revision"], "submission_id": sid,
         "sent_at": "2026-10-28T12:00:00Z",
         "items": [{"id": "item1", "title": "Item 1", "liked": ["i1-v0"], "note": "Cut the subtitle"}]}
    p.update(over)
    return p


def drop(inbox, meta, sid="sid-1", name=None, **over):
    name = name or "review-feedback__%s__%s__%s.json" % (meta["board_id"], meta["revision"], sid)
    path = inbox / name
    path.write_text(json.dumps(file_payload(meta, sid, **over)))
    return path


def test_watcher_filters_dedupes_and_validates(tmp_path, capsys):
    rj = write_review(tmp_path)
    out, meta, _, _ = brb.build(rj)
    inbox = tmp_path / "dl"
    inbox.mkdir()
    w = rs.InboxWatcher(meta, inbox)
    drop(inbox, dict(meta, board_id="other-board"), "o1")                       # another board
    (inbox / ("review-feedback__t-board__%s__x.json.crdownload" % meta["revision"])).write_text("{")
    drop(inbox, meta, "old", revision="deadbeef0000")                          # wrong revision
    (inbox / ("review-feedback__t-board__%s__half.json" % meta["revision"])).write_text('{"board": ')  # partial
    assert w.poll() is None
    assert "different version of the board" in capsys.readouterr().err
    good = drop(inbox, meta, "sid-1", name="review-feedback__t-board__%s__sid-1 (1).json" % meta["revision"])
    got = w.poll()
    assert got and got[0] == good and got[1]["submission_id"] == "sid-1"
    drop(inbox, meta, "sid-1")                                                   # same submission again
    assert w.poll() is None


def test_file_mode_wait_picks_up_delayed_file_and_exits_zero(tmp_path):
    rj = write_review(tmp_path)
    inbox = tmp_path / "dl"
    inbox.mkdir()
    p = subprocess.Popen([sys.executable, str(SK / "build_review_board.py"), str(rj), "--wait",
                          "--inbox", str(inbox), "--poll", "0.2"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    ready = p.stdout.readline()
    while "Built" in ready:
        ready = p.stdout.readline()
    page = tmp_path / "review-board-review" / "board.html"
    assert ready.strip() == "Review board ready: %s" % page and page.is_file()
    meta = json.loads((page.parent / "board-meta.json").read_text())
    time.sleep(0.6)
    drop(inbox, dict(meta, board_id="other"), "zz")
    (inbox / "review-feedback__t-board__x__y.json.crdownload").write_text("{")
    drop(inbox, meta, "bad", revision="0000")
    time.sleep(0.6)
    assert p.poll() is None
    drop(inbox, meta, "sid-9")
    out, err = p.communicate(timeout=15)
    assert p.returncode == 0
    assert "FEEDBACK RECEIVED" in out and "Cut the subtitle" in out and "### Item 1" in out
    fdir = tmp_path / "feedback"
    assert len(list(fdir.glob("*__sid-9.json"))) == 1 and len(list(fdir.glob("*__sid-9.md"))) == 1
    assert not (inbox / ("review-feedback__t-board__%s__sid-9.json" % meta["revision"])).exists()


# ---------- last round ----------

def test_two_watchers_one_file_exactly_one_wins(tmp_path):
    rj = write_review(tmp_path)
    out, meta, _, _ = brb.build(rj)
    inbox = tmp_path / "dl"
    inbox.mkdir()
    cmd = [sys.executable, str(SK / "build_review_board.py"), str(rj), "--wait", "--inbox", str(inbox), "--poll", "0.1"]
    ps = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    time.sleep(2)
    drop(inbox, meta, "race-1")
    t0 = time.time()
    while time.time() - t0 < 15 and sum(p.poll() is not None for p in ps) == 0:
        time.sleep(0.1)
    time.sleep(1.5)
    done = [p for p in ps if p.poll() is not None]
    waiting = [p for p in ps if p.poll() is None]
    assert len(done) == 1 and len(waiting) == 1 and done[0].returncode == 0
    assert "Cut the subtitle" in done[0].communicate()[0]
    waiting[0].kill()
    waiting[0].communicate()
    assert len(list((tmp_path / "feedback").glob("*__race-1.json"))) == 1


def test_replay_after_restart_is_ignored(tmp_path):
    rj = write_review(tmp_path)
    out, meta, _, _ = brb.build(rj)
    inbox = tmp_path / "dl"
    inbox.mkdir()
    doc = rs.canonical_feedback(meta, file_payload(meta, "replay-1"), "2026-10-28T12:00:00Z")
    rs.write_feedback(meta, doc)
    w = rs.InboxWatcher(meta, inbox)          # a fresh watcher: no in-memory dedupe
    drop(inbox, meta, "replay-1")
    assert w.poll() is None
    # and the server path
    L = Live(tmp_path)
    try:
        st, body = L.post(body=L.payload(submission_id="replay-1"))
        assert st == 200 and json.loads(body).get("duplicate") is True
        assert len(list(Path(L.meta["feedback_dir"]).glob("*__replay-1.json"))) == 1
    finally:
        L.close()


def test_idle_focused_tab_does_not_overwrite_other_tabs_note(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    sync_playwright = sync_api.sync_playwright
    rj = write_review(tmp_path)
    out, *_ = brb.build(rj)
    url = (out / "board.html").as_uri()
    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception:
            try:
                br = p.chromium.launch(channel="chrome")
            except Exception:
                pytest.skip("no browser installed for Playwright")
        ctx = br.new_context()
        a, b = ctx.new_page(), ctx.new_page()
        a.goto(url)
        b.goto(url)
        a.locator("textarea.note").first.focus()            # A: empty note, focused, idle
        b.locator("textarea.note").first.fill("note from B")
        b.wait_for_timeout(700)                              # B saved; storage event reaches A
        a.wait_for_timeout(300)
        assert a.locator("textarea.note").first.input_value() == "note from B"   # focused but untouched: adopted
        a.locator(".likebtn").first.click()                  # A likes: must not blank B's note
        a.wait_for_timeout(700)
        b.reload()
        assert b.locator("textarea.note").first.input_value() == "note from B"
        assert b.locator(".likebtn").first.get_attribute("aria-pressed") == "true"
        # a local edit is not clobbered by a later incoming note
        a.locator("textarea.note").first.fill("A edit")
        b.locator("textarea.note").nth(1).fill("other item")
        b.wait_for_timeout(700)
        a.wait_for_timeout(300)
        assert a.locator("textarea.note").first.input_value() == "A edit"
        assert a.locator("textarea.note").nth(1).input_value() == "other item"
        br.close()
