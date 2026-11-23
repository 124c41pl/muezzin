"""Web panel tests: what the page is allowed to read, and - more importantly -
what it is allowed to write. A config edit that fails validation must never
reach the file the daemon reads, and a disabled output must stay silent."""
from __future__ import annotations

import json
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from muezzin import geocode
from muezzin.cli import STARTER
from muezzin.config import AUDIO_SUFFIXES, load_profile
from muezzin.scheduler import PRAYER_KEYS, Runner
from muezzin.web import AUDIO_SUFFIXES as WEB_AUDIO_SUFFIXES, WebPanel, _fmt, _lead_shown

from test_scheduler import BASE, profile_for, write


def call(port, path, body=None, raw=False, headers=None):
    """Return (status, payload) - a 4xx is a normal answer here, not an exception.
    `headers` lets a test pretend to be something other than the muezzin page."""
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers=hdrs,
        method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", "replace")
            return resp.status, text if raw else json.loads(text)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(text)
        except json.JSONDecodeError:
            return exc.code, text


@pytest.fixture
def panel(tmp_path):
    profile, out = profile_for(tmp_path)
    runner = Runner(profile)
    web = WebPanel(runner, port=0)
    web.start()
    try:
        yield web, out, tmp_path
    finally:
        web.stop()
        runner.shutdown()


NARROW = "@media (max-width:620px)"


def column_widths(html, table, cell="th"):
    """The widths the columns of one table are told, as two lists: what a wide window
    gets, and what the rules for a narrow window get. A media query retells a table's
    columns for a phone, so read as one list they would be a table with twice as many
    columns as it has. Most tables are told by their headers; a table built without a
    header row has to be told by its cells, which is the same rule from the other end."""
    wide, _, phone = html.partition(NARROW)

    def grab(text):
        return [int(w) for w in
                re.findall(rf"{table} {cell}:nth-child\(\d\) \{{ width:(\d+)%", text)]

    return grab(wide), grab(phone)


def test_the_page_itself_is_served(panel):
    web, _, _ = panel
    status, html = call(web.port, "/", raw=True)
    assert status == 200
    assert html.startswith("<!doctype html")
    assert "muezzin" in html and "/api/state" in html


def test_the_page_script_only_reaches_elements_the_page_has(panel):
    """The page is one file with no build step and no browser in the test run, so
    the cheap thing worth checking is that the script's '#yaml' and '#media' style
    lookups name ids that are actually in the HTML."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    script = html.split("<script>", 1)[1]
    ids = set(re.findall(r'id="([^"]+)"', html))
    used = set(re.findall(r"\$\('#([a-zA-Z]+)'\)", script))
    assert used, "the script reaches nothing, which means it does nothing"
    assert used <= ids, f"the script looks up {sorted(used - ids)} but the page has no such id"
    for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
        assert script.count(opener) == script.count(closer), f"unbalanced {opener}"


def test_the_page_script_needs_no_backslashes(panel):
    """The page is one Python string on its way to a browser, so a \' in it is
    not an escaped quote over there: Python eats the backslash first and the
    script arrives as a syntax error that takes the whole page down with it.
    Every word in it is therefore written so no backslash was needed at all."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    script = html.split("<script>", 1)[1]
    assert "\\" not in script, "a backslash in the page is Python's, not JavaScript's"


def test_state_shows_times_events_and_outputs(panel):
    web, _, _ = panel
    status, st = call(web.port, "/api/state")
    assert status == 200
    assert len(st["days"]) == 3
    for day in st["days"]:
        assert set(day["times"]) == set(PRAYER_KEYS)
        assert ":" in day["times"]["fajr"] or day["times"]["fajr"] == "--:--"
    assert st["method"]["label"].startswith("ISNA")
    assert st["method"]["midnight"] == "solar"
    assert st["outputs"][0]["name"] == "outbox" and st["outputs"][0]["enabled"] is True
    assert any(e["name"] == "fajr-adhan" and e["targets"] == ["outbox"] for e in st["upcoming"])
    assert "preset: isna" in st["config_text"]
    # a file-only profile needs no media server, so the page says so instead of
    # claiming a URL the speakers would never fetch
    assert st["media_url"] is None
    assert "fajr.mp3" in st["media_files"]


def test_an_event_that_draws_from_the_library_says_so_on_the_page(panel):
    """A row whose recordings are chosen as it fires has nothing to name in advance, and
    a blank cell would read as a broken event rather than as a plan. The state carries
    the ask, and the row writes it out in words next to whatever the event does promise."""
    web, _, _ = panel
    _, st = call(web.port, "/api/state")
    edited = st["config_text"].replace("    media: [fajr.mp3]",
                                       "    media: [fajr.mp3]\n    random: 2")
    assert edited != st["config_text"], "the fixture stopped looking like the example"
    status, body = call(web.port, "/api/config", {"text": edited})
    assert status == 200, body
    _, st = call(web.port, "/api/state")
    row = [e for e in st["upcoming"] if e["name"] == "fajr-adhan"][0]
    assert row["random"] == 2 and row["media"] == ["fajr.mp3"], row
    assert [e["random"] for e in st["events"] if e["name"] == "fajr-adhan"] == [2]
    _, html = call(web.port, "/", raw=True)
    assert "e.random?[e.random+' at random']:[]" in html, "the row says nothing about the draw"


def test_state_carries_the_hijri_date_and_the_credit(panel):
    """The Hijri date and the credit line are display, so they ride along with
    the rest of the state instead of needing an endpoint of their own."""
    web, _, _ = panel
    _, st = call(web.port, "/api/state")
    assert st["version"]
    assert st["attribution"] is None and st["hijri_offset"] == 0
    for key in ("hijri", "hijri_ar", "marks"):
        assert key in st["today"]
    for day in st["days"]:
        assert day["hijri"] and day["hijri_ar"]
        assert all(m["kind"] in ("mourn", "celebrate", "plain") for m in day["marks"])


def test_the_hijri_offset_in_the_profile_moves_the_date_on_screen(panel):
    """The whole point of the knob is that the moon, not the arithmetic, decides
    - so the page has to show the community's date when the profile asks for it."""
    web, _, _ = panel
    _, st = call(web.port, "/api/state")
    original, before = st["config_text"], st["days"][0]["hijri"]
    times_before = st["days"][0]["times"]
    status, _ = call(web.port, "/api/config", {"text": original + "hijri_offset: 3\n"})
    assert status == 200
    _, st = call(web.port, "/api/state")
    assert st["hijri_offset"] == 3 and st["days"][0]["hijri"] != before
    # a calendar decoration must not touch a single prayer time
    assert st["days"][0]["times"] == times_before
    status, body = call(web.port, "/api/config", {"text": original + "hijri_offset: 30\n"})
    assert status == 400 and "between -3 and 3" in body["error"]


def test_the_page_buys_nothing_from_the_internet(panel):
    """A LAN panel that phones home to a font CDN is a panel that shows an ugly
    page the night the internet goes down, and a privacy problem on top."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    assert not re.search(r'(src|href)\s*=\s*["\']https?', html), "the page pulls from the internet"
    assert "data:image/svg" in html                    # the star lattice is drawn inline
    assert "الفجر" in html and "المغرب" in html        # and the Arabic is in the file


def test_the_page_says_who_wrote_it(panel):
    """A credit has to name a person, because a person is who answers questions
    about the code; the assistant that helped is named as what it was."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    assert "attribution" in html and "AI assistant" in html
    _, st = call(web.port, "/api/state")
    status, _ = call(web.port, "/api/config",
                     {"text": st["config_text"] + 'attribution: "Bilal of the downstairs masjid"\n'})
    assert status == 200
    _, st = call(web.port, "/api/state")
    assert st["attribution"] == "Bilal of the downstairs masjid"


def test_a_test_play_really_reaches_the_output(panel):
    web, out, _ = panel
    status, res = call(web.port, "/api/test", {"output": "outbox", "media": ["fajr.mp3"]})
    assert status == 200 and res["output"] == "outbox"
    assert (out / "fajr.mp3").read_bytes() == b"ID3\x03fake"


def test_disabling_an_output_silences_it_and_re_enabling_restores_it(panel):
    web, out, _ = panel
    status, res = call(web.port, "/api/output", {"name": "outbox", "enabled": False})
    assert status == 200 and res["enabled"] is False
    _, st = call(web.port, "/api/state")
    assert st["outputs"][0]["enabled"] is False
    assert all(e["targets"] == [] for e in st["upcoming"])

    status, res = call(web.port, "/api/test", {"output": "outbox", "media": ["fajr.mp3"]})
    # 409, not 500: the panel is fine, the output simply has no player behind it
    assert status == 409 and "disabled" in res["error"]

    call(web.port, "/api/output", {"name": "outbox", "enabled": True})
    status, _ = call(web.port, "/api/test", {"output": "outbox", "media": ["dua.mp3"]})
    assert status == 200
    assert (out / "dua.mp3").exists()


def test_an_invalid_edit_is_refused_and_the_file_is_untouched(panel):
    web, _, tmp_path = panel
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    bad = before.replace("kind: file", "kind: google_case")
    status, res = call(web.port, "/api/config", {"text": bad})
    assert status == 400
    assert "unknown kind" in res["error"] and "google_cast" in res["error"]
    # the message must point at the file in the editor, not our scratch copy
    assert "muezzin.yaml" in res["error"] and "webtmp" not in res["error"]
    assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before
    assert not list(tmp_path.glob("*.webtmp"))
    _, st = call(web.port, "/api/state")
    assert st["outputs"][0]["kind"] == "file"


def test_the_page_says_a_network_speaker_gets_a_head_start(panel):
    """Every time printed on this page is the computed one, so an adhan that
    starts a few seconds early has to be explained where the speakers are listed.
    Left unexplained it reads as a clock that is wrong, in a program whose whole
    job is the clock. A file output needs no head start, so it says `0`."""
    web, _, _ = panel
    _, st = call(web.port, "/api/state")
    assert st["outputs"][0]["lead"] == 0.0, "writing a copy out is instant"
    assert _lead_shown(8.0) == 8, "eight seconds on the page reads 8s early, not 8.0s early"
    assert _lead_shown(0.333) == 0.33
    _, html = call(web.port, "/", raw=True)
    assert "lead_seconds" in html, "the page names the knob that sets it by hand"
    assert "the times shown are the computed ones" in html


def test_a_valid_edit_is_saved_and_the_running_daemon_picks_it_up(panel):
    web, _, tmp_path = panel
    edited = BASE.replace("preset: isna", "preset: qom").replace(
        "  - name: outbox",
        '  - name: spare\n    kind: file\n    host: "{out}"\n  - name: outbox')
    status, res = call(web.port, "/api/config", {"text": edited})
    assert status == 200 and res["outputs"] == 2 and res["events"] == 3
    assert "preset: qom" in (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    _, st = call(web.port, "/api/state")
    assert st["method"]["label"].startswith("Qom")
    assert st["method"]["midnight"] == "jafari"
    assert [o["name"] for o in st["outputs"]] == ["spare", "outbox"]
    # the editor must keep showing the file it just wrote, not the temp file it
    # validated the edit against
    assert st["config_text"] == edited
    assert st["config_path"].endswith("muezzin.yaml")


def test_a_read_only_panel_can_look_but_not_touch(tmp_path):
    profile, _ = profile_for(tmp_path)
    runner = Runner(profile)
    web = WebPanel(runner, port=0, allow_edit=False)
    web.start()
    try:
        status, _ = call(web.port, "/api/state")
        assert status == 200
        for path, body in (("/api/config", {"text": "location: {}"}),
                           ("/api/output", {"name": "outbox", "enabled": False}),
                           ("/api/output/volume", {"name": "outbox", "volume": 0.4}),
                           ("/api/test", {"output": "outbox", "media": ["fajr.mp3"]})):
            status, res = call(web.port, path, body)
            assert status == 403 and "read-only" in res["error"]
    finally:
        web.stop()
        runner.shutdown()


def test_unknown_paths_do_not_bring_the_server_down(panel):
    web, _, _ = panel
    status, res = call(web.port, "/api/Settings/exeCommand")
    assert status == 404 and "no such path" in res["error"]
    status, res = call(web.port, "/api/test", {"nope": 1})
    assert status == 400 and "missing field" in res["error"]
    _, st = call(web.port, "/api/state")
    assert st["outputs"], "still serving afterwards"


def test_a_yaml_syntax_error_is_refused_as_a_bad_request(panel):
    """A stray tab is the commonest edit mistake, and it must come back as a
    clear 400, not as the daemon appearing to be broken."""
    web, _, tmp_path = panel
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    broken = before.replace("  - name: outbox", "\t- name: outbox")
    status, res = call(web.port, "/api/config", {"text": broken})
    assert status == 400, res
    assert "muezzin.yaml" in res["error"], "YAML points at '<unicode string>'; say which file"
    assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before
    assert not list(tmp_path.glob("*.webtmp"))


def test_saving_keeps_the_line_endings_the_file_already_had(panel):
    """A textarea sends LF. On Windows the profile is usually CRLF, and turning
    every line of it over would bury the actual change in a whole-file diff."""
    web, _, tmp_path = panel
    path = tmp_path / "muezzin.yaml"
    path.write_bytes(path.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
    # what the page would send: the same file, LF-only, with one preset changed
    edited = path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace(
        "preset: isna", "preset: qom")
    status, res = call(web.port, "/api/config", {"text": edited})
    assert status == 200, res
    saved = path.read_bytes()
    assert saved.replace(b"\r\n", b"\n").decode("utf-8") == edited
    assert saved.count(b"\r\n") == edited.count("\n"), "one CRLF per line, none doubled"


def test_the_page_cannot_ask_for_audio_outside_media_dir(panel):
    web, out, tmp_path = panel
    (tmp_path / "private.mp3").write_bytes(b"ID3\x03private")
    for entry in ("../private.mp3", str(tmp_path / "private.mp3")):
        status, res = call(web.port, "/api/test", {"output": "outbox", "media": [entry]})
        assert status == 400 and "outside media_dir" in res["error"], res
    assert not (out / "private.mp3").exists()


def test_two_tests_at_once_are_refused_rather_than_talking_over_each_other(panel):
    web, _, _ = panel
    # hold the lock a real playback would be holding, for the whole call
    assert web.testing.acquire(blocking=False)
    try:
        status, res = call(web.port, "/api/test", {"output": "outbox", "media": ["fajr.mp3"]})
    finally:
        web.testing.release()
    assert status == 409 and "still playing" in res["error"]


def test_a_write_from_another_page_is_refused(panel):
    """There is no login, so the Origin check is what stands between a website
    someone in the house visited and the profile the daemon is running."""
    web, _, tmp_path = panel
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    status, res = call(web.port, "/api/output", {"name": "outbox", "enabled": False},
                       headers={"Origin": "http://evil.example"})
    assert status == 403 and "origin" in res["error"]
    status, res = call(web.port, "/api/config", {"text": before},
                       headers={"Sec-Fetch-Site": "cross-site"})
    assert status == 403 and "origin" in res["error"]

    # a cross-site attack posts a plain form, not JSON: that is refused too
    req = urllib.request.Request(f"http://127.0.0.1:{web.port}/api/output",
                                 data=b"name=outbox&enabled=false",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Origin": f"http://127.0.0.1:{web.port}"},
                                 method="POST")
    try:
        urllib.request.urlopen(req, timeout=15)
        status = 200
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == 400
    _, st = call(web.port, "/api/state")
    assert st["outputs"][0]["enabled"] is True, "the form post changed nothing"


def test_an_absurd_body_is_refused(panel):
    """This is a LAN control panel, not a file host: it must not sit there
    downloading a body it has no intention of using."""
    web, _, tmp_path = panel
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{web.port}/api/config",
        data=json.dumps({"text": "x" * (300 * 1024)}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=15)
        outcome = "accepted"
    except urllib.error.HTTPError as exc:
        outcome = exc.code
    except OSError:
        # refusing also means refusing to download the rest of the body, and on
        # Windows the client learns that as an aborted connection rather than a
        # status line, so both answers mean the same thing here
        outcome = "hung up"
    assert outcome in (413, "hung up"), outcome
    assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before
    _, st = call(web.port, "/api/state")
    assert st["outputs"], "still serving afterwards"


def test_two_browsers_saving_at_once_do_not_blend_into_one_file(panel):
    web, out, tmp_path = panel
    def variant(preset):
        return (BASE.replace("{out}", str(out).replace("\\", "/"))
                .replace("preset: isna", f"preset: {preset}"))
    answers = []

    def save(text):
        answers.append(call(web.port, "/api/config", {"text": text})[0])

    threads = [threading.Thread(target=save, args=(t,))
               for t in (variant("qom"), variant("tehran"), variant("qom"), variant("tehran"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert answers == [200, 200, 200, 200]
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert on_disk in (variant("qom"), variant("tehran")), "the file is a mix of two edits"
    assert not list(tmp_path.glob("*.webtmp"))
    _, st = call(web.port, "/api/state")
    assert st["config_text"] == on_disk, "the daemon runs what is on disk"


def test_times_past_midnight_keep_their_day_marker():
    assert _fmt(None) == "--:--"
    assert _fmt(5.3334) == "05:20"
    assert _fmt(24.47) == "00:28 +1"
    assert _fmt(23.999) == "00:00 +1"      # rounds up, and says which day it belongs to


# ---- the buttons: method, clips, speakers, recordings ----------------------
#
# Each of these goes through the real HTTP routes, because the interesting part
# is not the string building but what the file looks like afterwards: a change
# that the daemon will not run has to be refused before it is written.

def _serve(tmp_path, text=None):
    profile, out = profile_for(tmp_path, text)
    runner = Runner(profile)
    web = WebPanel(runner, port=0)
    web.start()
    return web, out, runner


TWO = (BASE.replace('    host: "{out}"\n',
                    '    host: "{out}"\n  - name: second\n    kind: file\n    host: "{out}"\n',
                    1)
       .replace("    media: [fajr.mp3]\n", "    media: [fajr.mp3]\n    targets: [outbox]\n")
       .replace("    media: [dua.mp3]\n",
                "    media: [dua.mp3]\n    targets: [outbox, second]\n"))


@pytest.fixture
def two_outputs(tmp_path):
    web, out, runner = _serve(tmp_path, TWO)
    try:
        yield web, out, tmp_path
    finally:
        web.stop()
        runner.shutdown()


def post_raw(port, path, data, ctype="application/octet-stream"):
    """The file *is* the body here, so there is no JSON envelope to hide inside."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 headers={"Content-Type": ctype}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def get_bytes(port, path, headers=None):
    """Fetch a path and hand back (status, raw body, content type). A recording is
    bytes, not text: decoding it to check it would be the first way a test could
    pass while the browser got something it could not play."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type")


def get_all(port, path, headers=None):
    """The same fetch, keeping every response header. An answer to a ranged request is
    mostly headers: the bytes are only useful once you know which bytes they are."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers


def test_the_state_names_the_methods_the_page_can_offer(panel):
    web, _, _ = panel
    _, st = call(web.port, "/api/state")
    names = {p["name"] for p in st["presets"]}
    assert {"isna", "qom", "tehran", "shia_ithna_ashari"} <= names
    jafari = {p["name"] for p in st["presets"] if p["jafari"]}
    assert {"qom", "tehran", "shia_ithna_ashari", "qom_khamenei_12"} == jafari, \
        "the page groups by which midnight a method solves for, so this set is load-bearing"
    assert st["method"]["preset"] == "isna"
    assert st["method"]["midnight"] == "solar"
    assert st["prayers"] == list(PRAYER_KEYS)
    assert {e["name"] for e in st["events"]} == {"fajr-adhan", "dhuhr-nudge", "friday-tune"}


def test_the_method_list_names_both_groups_for_what_they_are(panel):
    """A dropdown where one group is called "Not Ja'fari" makes the other group the
    normal one and asks every household opening the page to place itself against that
    word before it has chosen anything. Both names here state where the night ends,
    which is the arithmetic the list is actually grouped by, and neither leans on the
    other."""
    web, _, _ = panel
    _, page = call(web.port, "/", raw=True)
    assert "Not Ja'fari" not in page, "one group is defined by the absence of the other"
    assert "Sunni (night ends at sunrise)" in page
    assert "Ja'fari (night ends at Fajr)" in page


def test_choosing_a_method_moves_the_times_on_the_page(panel):
    web, _, tmp_path = panel
    _, before = call(web.port, "/api/state")
    status, reply = call(web.port, "/api/method", {"preset": "qom"})
    assert status == 200, reply
    assert reply["method"].startswith("Qom")
    _, after = call(web.port, "/api/state")
    assert after["days"][0]["times"]["fajr"] != before["days"][0]["times"]["fajr"], \
        "the timetable follows the method, which is the whole point of the button"
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "preset: qom" in on_disk
    assert "at: fajr" in on_disk, "the events are still there afterwards"


def test_a_method_that_does_not_exist_is_named_back(panel):
    web, _, tmp_path = panel
    status, reply = call(web.port, "/api/method", {"preset": "made_up"})
    assert status == 400
    assert "made_up" in reply["error"] and "qom" in reply["error"]
    text = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "made_up" not in text


def test_the_asr_rides_with_the_method_and_an_override_survives_it(tmp_path):
    # a hand-written angle is what that person asked for; switching preset keeps
    # it, and the reply has to say so rather than let them find out at Fajr
    text = BASE.replace("method: {preset: isna, adjustments: {dhuhr: 0}}",
                        "method:\n  preset: isna\n  # notes\n  fajr_angle: 12.5\n"
                        "  adjustments: {dhuhr: 0}")
    web, _, runner = _serve(tmp_path, text)
    try:
        status, reply = call(web.port, "/api/method", {"preset": "karachi", "asr_shadow": "hanafi"})
        assert status == 200, reply
        assert reply["asr"] == "hanafi"
        assert reply["still_overridden"] == ["fajr_angle"]
        _, st = call(web.port, "/api/state")
        assert st["method"]["fajr_angle"] == 12.5
        assert st["method"]["asr"] == "hanafi"
        assert "# notes" in (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    finally:
        web.stop()
        runner.shutdown()


def test_the_page_is_told_what_the_file_overrides(tmp_path):
    # the panel reads this from state, not only from the reply to its own write:
    # a preset name that does not decide everything has to be visible before
    # anyone presses anything
    text = BASE.replace("method: {preset: isna, adjustments: {dhuhr: 0}}",
                        "method:\n  preset: isna\n  # notes\n  fajr_angle: 12.5\n"
                        "  adjustments: {dhuhr: 0}")
    web, _, runner = _serve(tmp_path, text)
    try:
        _, st = call(web.port, "/api/state")
        assert st["overridden"] == ["fajr_angle"]
        assert st["method"]["preset"] == "isna"
    finally:
        web.stop()
        runner.shutdown()


def test_the_page_has_room_for_the_three_new_answers(panel):
    """Calculation, a clip per prayer, and what is really on the LAN: the page
    needs a control for each. The group rows matter most, because a group whose
    speakers did not answer must read as unknown, not as empty."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    for heading in ("Method", "Sound", "Speakers on the network"):
        assert f"<h2>{heading}</h2>" in html, f"no {heading} section"
    for id_ in ("preset", "asr", "applymethod", "overrides", "hijridays", "hijminus",
                "hijplus", "sound", "applysound", "file", "upload", "scan", "found",
                "scansay", "uploadsay"):
        assert f'id="{id_}"' in html, f"the page has no {id_}"
    assert "unknown: they did not answer" in html
    assert "still in force" in html


def test_no_two_things_on_the_page_are_asked_for_by_the_same_name(panel):
    """Pressing look-again used to run the scan and change nothing you could see: the tag
    beside the button said a newer time, the count under it changed, and the table of
    speakers stayed exactly as it was. Two elements were called #found - the geocoder's
    answer list under Where, which comes first in the document, and the speaker table under
    Speakers on the network - and a page asks for a name by taking the first element that
    carries it, so the scan's rows went into the other card instead. The check covers the
    whole page, markup built inside the script included, because that is where a second
    name hides; a template that makes its own name is not a name to compare."""
    _, page = call(panel[0].port, "/", raw=True)
    names = re.findall(r'id="([a-zA-Z_][\w-]*)"', page)
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f"two things on the page are named {' and '.join(dupes)}"
    asked = set(re.findall(r"\$\('#([a-zA-Z_][\w-]*)'\)", page))
    missing = sorted(asked - set(names))
    assert not missing, f"the page reaches for {', '.join(missing)}, which nothing on it answers to"


def test_a_bad_asr_choice_is_refused(panel):
    web, _, _ = panel
    status, reply = call(web.port, "/api/method", {"preset": "isna", "asr_shadow": "maybe"})
    assert status == 400 and "standard or hanafi" in reply["error"]


def test_picking_a_clip_replaces_it_without_adding_another_event(panel):
    web, _, tmp_path = panel
    status, reply = call(web.port, "/api/audio", {"at": "fajr", "media": ["dua.mp3"]})
    assert status == 200, reply
    assert reply["updated_event"] == "fajr-adhan"
    _, st = call(web.port, "/api/state")
    assert [e["media"] for e in st["events"] if e["at"] == "fajr"] == [["dua.mp3"]]
    assert len(st["events"]) == 3, "an everyday clip is edited, not duplicated"


def test_a_friday_clip_is_its_own_event_and_leaves_the_day_alone(panel):
    web, _, tmp_path = panel
    status, reply = call(web.port, "/api/audio",
                         {"at": "dhuhr", "media": ["dua.mp3"], "friday": True})
    assert status == 200, reply
    assert reply["added_event"] == "dhuhr-friday"
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "days: [fri]" in on_disk
    _, st = call(web.port, "/api/state")
    dhuhr = [e for e in st["events"] if e["at"] == "dhuhr"]
    assert {e["name"] for e in dhuhr} == {"dhuhr-nudge", "dhuhr-friday"}
    daily = next(e for e in dhuhr if not e["days"])
    assert daily["media"] == ["dua.mp3"], "the weekday dhuhr clip is untouched"


def test_a_friday_clip_for_a_prayer_that_already_has_one_edits_it(panel):
    web, _, tmp_path = panel
    status, reply = call(web.port, "/api/audio",
                         {"at": "asr", "media": ["fajr.mp3"], "friday": True})
    assert status == 200, reply
    assert reply["updated_event"] == "friday-tune", "the Friday entry was found, not a second one"
    _, st = call(web.port, "/api/state")
    assert [e["name"] for e in st["events"] if e["at"] == "asr"] == ["friday-tune"]


def test_clearing_a_clip_removes_the_event_rather_than_writing_an_empty_one(panel):
    web, _, _ = panel
    status, reply = call(web.port, "/api/audio", {"at": "dhuhr", "media": []})
    assert status == 200, reply
    assert reply["removed_event"] == "dhuhr-nudge"
    _, st = call(web.port, "/api/state")
    assert "dhuhr-nudge" not in [e["name"] for e in st["events"]]
    status, reply = call(web.port, "/api/audio", {"at": "sunrise", "media": []})
    assert status == 200 and reply.get("unchanged") is True, "nothing to remove, and it says so"


def test_audio_must_be_audio_and_inside_the_media_dir(panel):
    web, _, tmp_path = panel
    status, reply = call(web.port, "/api/audio", {"at": "fajr", "media": ["notes.txt"]})
    assert status == 400 and ".mp3" in reply["error"]
    status, reply = call(web.port, "/api/audio", {"at": "fajr", "media": ["../secrets.mp3"]})
    assert status == 400 and "media_dir" in reply["error"]
    status, reply = call(web.port, "/api/audio", {"at": "teatime", "media": ["fajr.mp3"]})
    assert status == 400 and "teatime" in reply["error"]
    text = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert text.count("at: fajr") == 1, "a refused request must not touch the file at all"


def test_a_recording_uploads_if_the_bytes_agree_with_the_name(panel):
    web, _, tmp_path = panel
    status, reply = post_raw(web.port, "/api/media/upload?name=adhan-makkah.mp3",
                             b"ID3\x03\x00\x00\x00\x00\x00\x00fake mp3")
    assert status == 200, reply
    assert reply["kind"] == "mp3" and reply["uploaded"] == "adhan-makkah.mp3"
    assert "url" not in reply, "nothing here fetches a URL, so no server is advertised"
    assert (tmp_path / "media" / "adhan-makkah.mp3").exists()
    _, st = call(web.port, "/api/state")
    assert "adhan-makkah.mp3" in st["media_files"], "it shows up in the picker without a restart"


def test_a_upload_for_a_profile_that_casts_comes_back_with_a_url(tmp_path):
    # a speaker pulls the file over HTTP, so the reply has to name the address it
    # will be pulled from - that is what the page shows after an upload
    text = BASE.replace('    kind: file\n', '    kind: google_cast\n')
    text = text.replace('    host: "{out}"', '    target: "Whole-house group"')
    web, _, runner = _serve(tmp_path, text)
    try:
        status, reply = post_raw(web.port, "/api/media/upload?name=adhan.ogg",
                                 b"OggS\x00\x02fake ogg")
        assert status == 200, reply
        assert reply["url"].startswith("http://") and reply["url"].endswith("adhan.ogg")
        assert runner.media is not None, "a cast output needs the media server up"
    finally:
        web.stop()
        runner.shutdown()


def test_an_upload_never_overwrites_what_is_already_playing(panel):
    web, _, tmp_path = panel
    assert post_raw(web.port, "/api/media/upload?name=second.wav", b"RIFF\x00\x00\x00\x00WAVEfmt ")[0] == 200
    status, reply = post_raw(web.port, "/api/media/upload?name=second.wav", b"RIFF\x00\x00\x00\x00WAVEfmt ")
    assert status == 400 and "already" in reply["error"]


def test_a_file_is_believed_by_its_header_not_its_name(panel):
    web, _, tmp_path = panel
    status, reply = post_raw(web.port, "/api/media/upload?name=adhan.mp3", b"\x89PNG\r\n\x1a\n\x00\x00")
    assert status == 400 and "header" in reply["error"]
    status, reply = post_raw(web.port, "/api/media/upload?name=../../etc.mp3", b"ID3\x03fake")
    assert status == 400 and "plain file name" in reply["error"]
    status, reply = post_raw(web.port, "/api/media/upload?name=notes.txt", b"hello")
    assert status == 400 and ".txt" in reply["error"]
    assert not (tmp_path / "media" / "notes.txt").exists()


def test_a_recording_may_be_large_where_a_json_body_may_not(panel, monkeypatch):
    from muezzin import web as web_module
    web, _, tmp_path = panel
    # 300 KB of adhan is a normal thing; 300 KB of JSON is not, and the two limits
    # are deliberately different so a household can upload a real recording
    big = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"0" * (300 * 1024)
    assert post_raw(web.port, "/api/media/upload?name=long.mp3", big)[0] == 200
    assert (tmp_path / "media" / "long.mp3").stat().st_size == len(big)
    monkeypatch.setattr(web_module, "MAX_UPLOAD", 1024)
    status, reply = post_raw(web.port, "/api/media/upload?name=big.mp3", b"ID3\x03" + b"0" * 2048)
    assert status == 413 and "more than" in reply["error"]
    assert not (tmp_path / "media" / "big.mp3").exists()


def test_the_page_can_ask_for_a_recording_to_play_itself(panel):
    """The preview: the browser fetches the bytes and makes the sound out of its own
    computer, so someone can hear what an adhan sounds like before assigning it. No
    speaker on the network is asked for anything, and the file arrives whole."""
    web, _, tmp_path = panel
    status, body, ctype = get_bytes(web.port, "/api/clip?name=fajr.mp3")
    assert status == 200 and ctype == "audio/mpeg"
    assert body == (tmp_path / "media" / "fajr.mp3").read_bytes()


def test_the_preview_calls_a_file_by_what_its_bytes_are(panel):
    """An upload has to agree with its own name; a WAV someone copied into media_dir
    by hand is allowed to exist. The browser still has to be told what it is being
    handed, or it sits there silently and the user blames the recording."""
    web, _, tmp_path = panel
    (tmp_path / "media" / "liar.mp3").write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    status, _, ctype = get_bytes(web.port, "/api/clip?name=liar.mp3")
    assert status == 200 and ctype == "audio/wav"


def test_the_preview_only_answers_for_a_plain_name_in_media_dir(panel):
    """The same containment the test button has. A page may pick a file out of the
    list it was given; it does not get to name one further up the tree, and a
    refusal says so instead of bringing a traceback into the daemon's log."""
    web, _, tmp_path = panel
    (tmp_path / "private.txt").write_text("the household address\n", encoding="utf-8")
    for name in ("../private.txt", "..\\private.txt", "/etc/passwd", "C:\\private.txt"):
        status, body, _ = get_bytes(web.port, "/api/clip?name=" + urllib.parse.quote(name))
        assert status in (400, 404), f"{name} was answered with {status}"
        assert b"household" not in body
    status, body, _ = get_bytes(web.port, "/api/clip?name=nope.mp3")
    assert status == 404 and "media_dir" in body.decode()


def test_something_that_is_not_audio_is_not_handed_to_a_browser(panel):
    web, _, tmp_path = panel
    note = "a reminder about the prayer times, not a recording\n"
    (tmp_path / "media" / "notes.txt").write_text(note, encoding="utf-8")
    status, body, _ = get_bytes(web.port, "/api/clip?name=notes.txt")
    assert status == 415 and "reminder" not in body.decode()


def test_a_read_only_panel_can_still_be_listened_to(tmp_path):
    """Hearing the library changes nothing - no file, no schedule, no speaker - so a
    guest who cannot write should still be able to listen. That is the difference
    between this route and every other one the panel offers."""
    profile, _ = profile_for(tmp_path)
    runner = Runner(profile)
    web = WebPanel(runner, port=0, allow_edit=False)
    web.start()
    try:
        status, _, ctype = get_bytes(web.port, "/api/clip?name=fajr.mp3")
        assert status == 200 and ctype == "audio/mpeg"
        _, reply = call(web.port, "/api/reload", {})
        assert "read-only" in reply["error"]
    finally:
        web.stop()
        runner.shutdown()


def test_another_page_cannot_ask_for_someone_elses_recordings(panel):
    """A browser says in Sec-Fetch-Site whether a request came from this page or from
    a site someone in the house happens to be visiting. The writes are already
    guarded by that; this is the one read that hands over a file, so it is guarded
    too. curl says nothing at all and stays allowed."""
    web, _, _ = panel
    for site, wanted in (("cross-site", 403), ("same-site", 403), ("same-origin", 200), ("", 200)):
        headers = {"Sec-Fetch-Site": site} if site else {}
        status, _, _ = get_bytes(web.port, "/api/clip?name=fajr.mp3", headers)
        assert status == wanted, f"Sec-Fetch-Site: {site} answered {status}"


def test_the_preview_answers_for_a_piece_of_a_recording(panel):
    """The seek bar on the page works by the browser asking for the bytes from further
    into the file. That is only possible if the daemon answers for that piece, and a
    browser decides whether to offer a bar at all by looking at the headers of an
    ordinary request, so both halves are checked here rather than trusted to a
    browser two rooms away."""
    web, _, tmp_path = panel
    whole = (tmp_path / "media" / "fajr.mp3").read_bytes()
    # The fake recording in the fixture is eight bytes, so the piece asked for is a
    # piece of eight bytes: what is being checked is the arithmetic of the answer, not
    # the size of a real recitation.
    status, _, headers = get_all(web.port, "/api/clip?name=fajr.mp3")
    assert status == 200 and headers.get("Accept-Ranges") == "bytes"
    status, body, headers = get_all(web.port, "/api/clip?name=fajr.mp3", {"Range": "bytes=3-5"})
    assert status == 206, body
    assert body == whole[3:6]
    assert headers.get("Content-Range") == f"bytes 3-5/{len(whole)}"
    assert headers.get("Content-Length") == "3"
    # A seek to somewhere past the end of the file is what a player does when it has a
    # wrong idea about how long a clip is: answered with the file's real length, not with
    # the whole file, because a client holding a wrong idea has to be corrected.
    status, body, headers = get_all(web.port, "/api/clip?name=fajr.mp3",
                                    {"Range": f"bytes={len(whole) + 7}-"})
    assert status == 416 and headers.get("Content-Range", "").endswith(f"/{len(whole)}")
    assert b"ID3" not in body


def test_an_ask_a_browser_invented_cannot_reach_outside_media_dir(panel):
    """A header is a header, so it obeys the same containment as the name in the
    query. Nothing about the byte range changes which file this is allowed to be."""
    web, _, tmp_path = panel
    (tmp_path / "private.txt").write_text("the household address\n", encoding="utf-8")
    status, body, _ = get_all(web.port, "/api/clip?name=../private.txt", {"Range": "bytes=0-9"})
    assert status in (400, 404) and b"household" not in body


def test_the_speaker_test_can_be_stopped_from_the_page(panel):
    """A test is a recording about to come out of a real speaker, so the page has to be
    able to call it back. The ask goes to the output rather than to the thread doing
    the playing, because that thread is blocked inside the speaker until the file
    ends - which is the whole reason a test that chose the wrong recitation would
    otherwise have to be listened to to the end."""
    from muezzin import scheduler as sched

    web, _, _ = panel
    started = threading.Event()
    released = threading.Event()
    stopped = []

    def fake(paths, volume=None):
        started.set()
        released.wait(10)

    def fake_stop():
        stopped.append(True)
        released.set()
        return True

    out = next(o for o in web.runner.profile.outputs if o.kind == "file")
    web.runner.backends[out.name].play = fake
    web.runner.backends[out.name].stop = fake_stop
    thread = threading.Thread(target=lambda: call(web.port, "/api/test",
                                                  {"output": out.name, "media": ["fajr.mp3"]}))
    thread.start()
    assert started.wait(5), "the test never reached the output"
    status, reply = call(web.port, "/api/test/stop", {"output": out.name})
    assert status == 200 and reply["stopped"] == [out.name]
    assert stopped, "the output was never asked to stop"
    thread.join(10)
    assert not thread.is_alive(), "the test kept playing after being stopped"
    # And the ask that named nobody is refused rather than guessed at: a page with two
    # speakers must say which one is to go quiet.
    status, reply = call(web.port, "/api/test/stop", {})
    assert status == 400 and "which output" in reply["error"]
    status, reply = call(web.port, "/api/test/stop", {"output": "not-there"})
    assert status == 404


def test_stopping_nothing_is_an_answer_and_not_an_error(panel):
    """The page offers a Stop button whenever it has sent a test, and the test may have
    finished by the time the button is pressed. That is the reply to the question that
    was asked, so it comes back as an empty list rather than a complaint."""
    from muezzin import scheduler as sched

    web, _, _ = panel
    out = next(o for o in web.runner.profile.outputs if o.kind == "file")
    assert web.stop_test({"output": out.name})["stopped"] == []


def test_the_scheduled_call_is_not_cut_short_by_stopping_a_test(panel):
    """Stopping is about what is going on right now. It does not pause the schedule,
    disable a speaker or drop what is queued: the next adhan is still coming at its
    time, and a person who stops a test should not have to wonder whether they just
    silenced the morning."""
    web, _, _ = panel
    out = next(o for o in web.runner.profile.outputs if o.kind == "file")
    status, reply = call(web.port, "/api/test/stop", {"output": out.name})
    assert status == 200
    assert web.runner.profile.output(out.name).enabled is True, \
        "stopping a test quietly disabled the output"
    _, st = call(web.port, "/api/state")
    row = next(o for o in st["outputs"] if o["name"] == out.name)
    assert row["enabled"], "stopping a test left the output disabled"
    assert st["upcoming"], "stopping a test emptied the rest of the day"


def test_the_page_has_a_transport_and_no_way_to_move_a_computers_level(panel):
    """Three things the page has to get right that no Python assertion about audio can
    catch: the preview is labelled as this computer making the sound, the only levels
    anything on the page can move belong to speakers muezzin casts to, and the script never
    touches the level of the player making the sound. The level of a computer - the one
    running this program, or a box on the LAN - belongs to the person sitting in front of it,
    so that kind of output gets words instead of a control. The other three sliders are a
    speaker muezzin casts to, one room inside a speaker group, and what one prayer asks of
    one of those rooms, which are all the same kind of number: a fraction of that room's own
    scale. The last slider is a place inside a recording, which is filled in from the file's
    length - not a 0 to 1 thing."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    assert "/api/clip" in html and "play it here" in html
    script = html.split("<script>", 1)[1]
    assert "new Audio(" in script, "the preview has to be the browser making the sound"
    assert not re.search(r"\b\w+\.volume\s*=(?!=)", script), \
        "the page must not set the level of the browser showing it, or of any computer"
    sliders = re.findall(r'<input[^>]*type="range"[^>]*>', html)
    assert len(sliders) == 4, \
        ("one slider for a place inside a recording, one for a speaker we are casting to, "
         "one for a room inside a group we are casting to, and one for what a single prayer "
         "asks of one of those rooms")
    seek = next(s for s in sliders if 'id="seek"' in s)
    level = next(s for s in sliders if "data-level" in s)
    room = next(s for s in sliders if "data-room=" in s)
    prayer = next(s for s in sliders if "data-lv-set" in s)
    assert 'max="0"' in seek, \
        "a position bar starts with nothing on it and takes its length from the file"
    assert 'aria-label="how far into it you are"' in seek
    for slider, what in ((level, "a speaker"), (room, "a room inside one"),
                         (prayer, "a prayer's ask of one room")):
        assert 'min="0"' in slider and 'max="1"' in slider and 'step="0.05"' in slider, \
            (f"a {what} level is a fraction of that speaker's own scale, the same number "
             "`volume:` holds")
    assert "data-room-name" in room, \
        "a room is named by what it answers to on the network, not by a name typed in here"
    assert "data-lv-name" in prayer, \
        "the same holds for a prayer's own room: the name is the network's, never typed in"
    assert "takes_volume" in script and "not ours to ask" in script, \
        "the control only appears for a kind the daemon itself says can be asked for a level"
    assert 'id="hush"' in html and "pause" in html, "the preview needs a pause"
    assert 'id="halt"' in html and "stop" in html, "and a stop that is not the same button"


def test_the_test_button_of_an_output_sits_inside_the_card(panel):
    """The Outputs card is the one that had a button fall off it. A table left to itself
    grows to whatever its words need and the card around it does not grow with it, so the
    column at the end - the button that sends a recording to a real speaker - ended up
    past the edge of the card, which is the one thing in that card a person goes looking
    for. Five columns of words also do not fit in a third of the page: the card takes the
    width of the page instead, and the widths are told rather than guessed from the words,
    so each column sits under its own header and the button stays inside the border. A
    name box measured in characters is part of the same complaint - a speaker called
    whole-house lost its last letters, and a name you cannot read is a name you cannot
    rename. Nothing here runs a browser, so the page is read as text; the shape it
    actually makes was checked with a screenshot of this page in a narrow window. The rooms
    inside a group had the same accident, one slider at a time. The card had a second one, in the
    space between a phone and a desk: a told width is a percentage, and at a window only a little
    wider than a phone the card is much narrower than the one those percentages were weighed
    against, so the switch stood over the edge of its own column and on top of the slider beside
    it, while test and stop - asked to keep to one line - were one line about as wide as the
    column and ran sideways over it. A word costs nothing but a line when it breaks; a control
    costs the card. The same six columns are retold for a narrow window, because a fifth of a
    phone is not a fifth of a desktop; what a phone then looks like - and whether the controls fit
    the columns they are given - is the test below this one."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    assert '<section class="wide"><h2>Outputs</h2>' in html, \
        "a table this wide belongs to the whole page, not to one column of it"
    assert "#outputstbl { table-layout:fixed }" in html, \
        "the columns have to be told their widths, not left to size themselves by their words"
    assert "#outputstbl td:last-child { text-align:right }" in html and "white-space:nowrap" not in html, \
        "the button column is the one that must never be the one that grows, and nothing on this " \
        "page asks a row of buttons to keep to one line: a line that cannot break is as wide as " \
        "both buttons together, and it runs sideways over the column next to it"
    widths, phone = column_widths(html, "#outputstbl")
    assert len(widths) == 6, "every column is given a width"
    assert sum(widths) == 100, f"the columns add up to {sum(widths)}%"
    assert len(phone) == 6, "every column is given a width for a phone as well"
    assert sum(phone) == 100, f"the phone's columns add up to {sum(phone)}%"
    # A percentage is only a width once a window is known. The narrowest window this set of
    # widths has to serve is one pixel wider than the phone rules take over, because the card
    # is the whole page there; the columns that hold a control are weighed against the control,
    # since a control has a width it cannot go under. A word is not weighed, because a word
    # breaks where it has to and a column that breaks a word costs nothing but a line.
    desk = 621 - 44 - 32          # window, main's padding, the card's own padding
    on = desk * widths[3] / 100
    assert on >= 38 + 8, \
        f"the switch column of this card is {on:.0f}px at the narrow end of its range, and the " \
        f"switch standing in it is 38px across, plus the 8px a cell keeps for itself on the right"
    level = desk * widths[4] / 100
    assert level >= 80, f"the level column is {level:.0f}px there and the slider in it is 80px wide"
    button = desk * widths[5] / 100
    assert button >= 50 + 8, \
        f"the last column is {button:.0f}px there and stop is about 50px across: the wider the " \
        f"column, the less room the two of them need to stand on one line"
    assert "#outputstbl input[type=range] { width:80px" in html, \
        "a slider left to its own devices is wider than the column it lives in, which is " \
        "exactly how the test button ended up outside the card once already"
    roomrow = re.search(r"const roomrow=o=>(.*)", html).group(1)
    assert 'class="roomrow"' in roomrow and "colspan" not in roomrow, \
        "the rooms inside a group get rows of their own: one cell holding four rooms is how " \
        "the sliders ran past the edge of this card, and a room is a row, not a phrase"
    assert roomrow.count("<td") == 6, \
        f"a room row has {roomrow.count('<td')} cells where this table has six, so the room's " \
        "controls would not sit under the group's own"
    assert "<td></td><td></td><td><input" in roomrow, \
        "a room's slider belongs in the fifth column, under the slider of the group it is in"
    assert 'class="roomname"' in roomrow, "a room is named in the column the outputs' names are in"
    assert "word-break:break-word" not in html, \
        "that breaks a long word at the first chance it gets, mid-word, in every cell"
    assert "width:12ch" not in html, "a name box measured in characters hides the end of a name"


def test_a_phone_gets_switches_and_sliders_the_finger_can_find(panel):
    """This panel gets opened on a phone as often as on a laptop - the level of a speaker
    is a thing people fix while the speaker is making the noise - and there the switches
    and the sliders were in each other's way, for two different reasons. A switch 38px by
    20px is smaller than the pad of a thumb, and a mis-hit is worse than a miss because
    what it sends rewrites the profile. And six columns told their widths in percentages
    leave four centimetres of phone to a level column: an 80px slider, its figure, and a
    sentence about what a group's number does, all pushing at one another. So the switch's
    box grows to 44px while its track stays the size it was drawn at; the sliders grow
    taller and fill the column they are given; the figure drops onto a line under its
    slider; and the columns of both tables are retold for a phone rather than merely
    narrowed. No browser runs here either, so the arithmetic is done here instead: the
    narrow columns are weighed against the width a phone's card actually gets, and against
    the width of the control that has to sit inside them. A button is the control that cannot
    break a word to fit, so the buttons in a table row are told to fill the column they are
    in, one under the other; and a card is told it may be narrower than 320px, because below
    that a card wider than the window puts its own buttons off the screen. A column of ordinary
    words is not weighed, because a word that does not fit costs a line and nothing else; the
    size of a file is weighed, because the only other place it can break is inside the number."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    assert NARROW in html, "a phone is told something different from a wide window"
    phone = html.split(NARROW)[1]
    assert ".switch { width:44px; height:44px" in phone, \
        "the thing a thumb presses is the size of a thumb, not the size of the drawing"
    assert ".switch:before" in phone and "height:20px" in phone, \
        "the track keeps the size it was drawn at, so the target grows and the look does not"
    assert "input[type=range] { height:34px }" in phone, "a slider bar a thumb can hold"
    assert "#outputstbl input[type=range] { width:100%; min-width:0 }" in phone, \
        "the level bar fills its column instead of a fixed 80px that is wider than that column"
    assert "#outputstbl td > .tag" in phone and "display:block" in phone, \
        "the figure for a level stands under its slider rather than wedged beside it"
    assert "#outputstbl .roomnote { display:none }" in phone, \
        "the sentence about what a group's number does is said under the card, not in the row"
    assert 'class="unknown roomnote"' in html and 'class="unknown why"' in html, \
        "the row itself says which of its sentences a narrow window may leave out"
    card = 320 - 24 - 24          # what a table has to sit in: main and section paddings
    assert "main { padding:12px; grid-template-columns:minmax(0,1fr) }" in phone, \
        "the page's frame gives the tables their width back on a phone, and a card is never " \
        "asked to be wider than the window it was opened in"
    assert "section { padding:12px }" in phone, \
        "the edge a card keeps for itself is given back to the table inside it"
    assert "td > button:not(.switch)" in phone and "display:block; width:100%" in phone, \
        "a button in a column that was told its width stands on a line of its own and fills " \
        "that column, so it cannot grow past the card around it either"
    assert "padding-right:0; text-align:center" in phone, \
        "the edge a cell keeps for itself on the right is given back where the column's " \
        "whole content is a switch"
    for table, switch_column, what in (("#outputstbl", 4, "the switch of an output"),
                                       ("#libtbl", 3, "the switch of a recording")):
        wide, narrow = column_widths(html, table)
        assert len(narrow) == len(wide), \
            f"{table} retells {len(narrow)} columns where the table has {len(wide)}"
        assert sum(narrow) == 100, f"the phone's columns of {table} add up to {sum(narrow)}%"
        px = card * narrow[switch_column - 1] / 100
        assert px >= 44, f"{what} is 44px across and its column on a phone is {px:.0f}px"
    px = card * column_widths(html, "#outputstbl")[1][5] / 100
    assert px >= 38 + 14, \
        f"same as the group is what the button in a room's row says, and that column on a phone " \
        f"is {px:.0f}px: shorter than the longest word in it once the button's own padding is " \
        f"counted, and a button told to fill its column cannot make the column wider"
    px = card * column_widths(html, "#libtbl")[1][1] / 100
    assert px >= 24 + 8, \
        f"the size column of the recordings card on a phone is {px:.0f}px, and a size is two " \
        f"words with a space between them: three digits at the table's own 14px are about 24px " \
        f"across, and a cell keeps 8px of its column, so below this the number itself breaks " \
        f"and the row reads 84 / 2 KB"
    found = column_widths(html, "#foundtbl")[1]
    px = card * found[4] / 100
    assert px >= 40, \
        f"stop using is two words, and its column on a phone is {px:.0f}px - not enough for " \
        f"the longer of them, let alone for a thumb"


def test_the_page_shows_a_lamp_while_it_waits_on_the_daemon(panel):
    """Nothing on this page is instant: moving a slider means rewriting the file, and
    looking at the network takes a few seconds. So a person who moves something and sees
    nothing has no way to tell a slow ask from a dead one. The answer is a lamp rather than
    a curtain - the page stays readable and clickable while the daemon works - and the lamp
    is lit by a timer, not by the request: an ask that answers in a few tens of
    milliseconds never shows anything, which is what keeps the page from flickering every
    time anybody touches it."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    assert 'id="busy" role="status" hidden' in html and "still working" in html, \
        "no lamp, or one that is on before anything is being asked"
    assert "position:fixed" in html and "pointer-events:none" in html, \
        "the lamp sits over the page instead of in front of it: a page that is thinking can " \
        "still be read, and the next slider can still be moved"
    lamp = html.split("let waiting=0")[1].split("async function api")[0]
    delay = re.search(r"\},(\d+)\)", lamp).group(1)
    assert 200 <= int(delay) <= 800, \
        f"the lamp comes up after {delay}ms: too soon is a flicker over every ask, too late is a page that looks stuck"
    assert "setTimeout" in lamp and "clearTimeout" in lamp, \
        "a fast answer has to cancel the lamp the timer was going to light"
    body = html.split("async function api(path,body){")[1].split("\n}")[0]
    assert "begun()" in body and "} finally { ended(); }" in body, \
        "every request lights the lamp and puts it out again, including one that was refused"
    assert html.count("waiting++") == 1 and html.count("--waiting") == 1, \
        "two asks in the air are one wait to a person watching, so one counter counts them"


def test_the_speaker_scan_is_cached_and_says_when_it_ran(panel, monkeypatch):
    from muezzin import web as web_module
    web, _, _ = panel
    calls = []

    def fake(timeout=5.0, ask_members=True):
        calls.append(timeout)
        return {"speakers": [{"name": "Study speaker", "model": "Nest Mini",
                              "address": "192.168.0.23", "port": 8009, "group": False}],
                "groups": [{"name": "Whole-house group", "id": "abc", "members": ["Study speaker"],
                            "membership_known": True, "silent": []}],
                "boxes": [], "asked": 1, "silent": []}

    monkeypatch.setattr(web_module, "scan_speakers", fake)
    status, reply = call(web.port, "/api/speakers")
    assert status == 200, reply
    assert reply["found"]["groups"][0]["members"] == ["Study speaker"]
    assert reply["seen_at"]
    call(web.port, "/api/speakers")
    assert len(calls) == 1, "the page may poll it; the network should not be polled on every poll"
    call(web.port, "/api/speakers?refresh=1")
    assert len(calls) == 2, "a refresh is what the button asks for"
    assert call(web.port, "/api/speaker/add", {"target": "Study speaker"})[0] == 200
    _, reply = call(web.port, "/api/speakers")
    assert reply["in_profile"] == {"Study speaker": "study-speaker"}, \
        "the page needs to know which rows are already in the profile"


def test_a_scanned_speaker_can_be_added_and_the_name_is_taken_from_it(panel):
    from muezzin import web as web_module
    web, _, tmp_path = panel
    status, reply = call(web.port, "/api/speaker/add", {"target": "Study speaker", "volume": 0.35})
    assert status == 200, reply
    assert reply["output"] == "study-speaker"
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "target: Study speaker" in on_disk and "volume: 0.35" in on_disk
    status, reply = call(web.port, "/api/speaker/add", {"target": "Study speaker"})
    assert status == 400 and "already" in reply["error"]


def test_a_box_the_panel_cannot_drive_is_not_offered_as_an_output(panel):
    web, _, _ = panel
    # The panel writes what the loader can read. A box advertising a protocol
    # muezzin does not speak has nowhere to go, so it is refused here rather
    # than written into a profile that fails at the next prayer time.
    status, reply = call(web.port, "/api/box/add",
                         {"name": "attic-pi", "host": "192.0.2.156", "port": 9874,
                          "kind": "some_other_box"})
    assert status == 400 and "lan_box" in reply["error"]


def test_removing_a_speaker_says_which_events_it_took_with_it(two_outputs):
    web, _, tmp_path = two_outputs
    status, reply = call(web.port, "/api/output/remove", {"name": "outbox"})
    assert status == 400 and "fajr-adhan" in reply["error"], \
        "the last speaker of an event cannot be deleted out from under it"
    status, reply = call(web.port, "/api/output/remove", {"name": "second"})
    assert status == 200, reply
    assert sorted(reply["events_rewritten"]) == ["dhuhr-nudge", "friday-tune"]
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "second" not in on_disk
    _, st = call(web.port, "/api/state")
    assert [o["name"] for o in st["outputs"]] == ["outbox"]
    fajr = next(e for e in st["events"] if e["name"] == "fajr-adhan")
    assert fajr["targets"] == ["outbox"], "an event that did not use it is left alone"


def test_an_output_can_be_named_from_the_page_and_the_events_follow(two_outputs):
    """A name is not a caption: it is the word events use to point at a speaker. So the
    rename has to land in the `targets:` lists in the same write, or the profile that was
    just saved would be unreadable and the call would never go out again. The name the
    household typed is flattened to one safe word, and the reply says which word that was
    rather than quietly keeping a different one."""
    web, _, tmp_path = two_outputs
    status, reply = call(web.port, "/api/output/rename",
                         {"from": "second", "to": "Kitchen speaker"})
    assert status == 200, reply
    assert reply["renamed"] == "kitchen-speaker"
    assert sorted(reply["events_rewritten"]) == ["dhuhr-nudge", "friday-tune"]
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "name: kitchen-speaker" in on_disk
    assert "second" not in on_disk, "an event still pointed at the name that no longer exists"
    _, st = call(web.port, "/api/state")
    assert {o["name"] for o in st["outputs"]} == {"outbox", "kitchen-speaker"}
    fajr = next(e for e in st["events"] if e["name"] == "fajr-adhan")
    assert fajr["targets"] == ["outbox"], "an event that never named it is left alone"


def test_a_rename_that_would_collide_or_lead_nowhere_is_refused(two_outputs):
    """Two outputs cannot answer to one word, and renaming a speaker nobody has is a way
    of inventing a speaker. Both are refused before anything is written, so a typo in the
    box cannot take the schedule down."""
    web, _, tmp_path = two_outputs
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    for payload, why in (({"from": "second", "to": "outbox"}, "already"),
                         ({"from": "nobody", "to": "kitchen"}, "no output called nobody"),
                         ({"from": "second", "to": "   "}, "called")):
        status, reply = call(web.port, "/api/output/rename", payload)
        assert status == 400 and why in reply["error"], (payload, status, reply)
    assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before


# ---- what a speaker is asked to come out at ---------------------------------
#
# The loudness of a test used to be whatever the room happened to be left at, which
# meant two households pressing the same button heard two different things and neither
# could say why. `volume:` was already the profile's word for it and the cast backend
# already applied it to everything it plays through that output - a test included - so
# all the page has to do is write that number for the kinds it is allowed to write it
# for. A computer's own level, whether it is the machine running this program or a box
# on the LAN, stays the property of whoever is sitting at it. A speaker group is the
# third kind of answer: it is a name several speakers share, and it has no level of its
# own that anybody hears, so the number written there is what every room inside is asked
# for while a call plays - and each room is put back where it was when the call ends.

CAST_AND_PC = (BASE.replace('  - name: outbox\n    kind: file\n    host: "{out}"\n',
                            '  - name: nest\n    kind: google_cast\n'
                            '    target: "Study speaker"\n'
                            '  - name: front-room\n    kind: google_cast\n'
                            '    target: "Whole-house group"\n'
                            '  - name: outbox\n    kind: file\n    host: "{out}"\n'
                            '  - name: this-pc\n    kind: pc_speakers\n'))

# The same household with a room the profile already asks for a level, written last month,
# and a speaker since renamed in the Home app: the name in the file answers to nobody now.
CAST_WITH_A_STALE_ROOM = CAST_AND_PC.replace(
    '  - name: front-room\n    kind: google_cast\n    target: "Whole-house group"\n',
    '  - name: front-room\n    kind: google_cast\n    target: "Whole-house group"\n'
    '    members:\n      Study speakers: 0.3\n')


def one_speaker_and_one_group(timeout=5.0, ask_members=True):
    """What the network says when asked: one speaker of our own, and one group that is
    several speakers wearing one name. Faked because the honest answer about a group is a
    fact about the LAN, and a test has no LAN to ask."""
    return {"speakers": [{"name": "Study speaker", "model": "Nest Mini", "id": "study",
                          "address": "192.168.0.23", "port": 8009, "group": False}],
            "groups": [{"name": "Whole-house group", "id": "abc", "group": True,
                        "members": ["Study speaker"], "membership_known": True, "silent": []}],
            "boxes": [], "asked": 1, "silent": []}


def a_group_of(*who):
    """The same answer from the network with different speakers inside the group. What the
    rooms are called is a fact about somebody else's house, and a test that wants to tell
    two rooms apart cannot make do with one room named twice."""
    found = one_speaker_and_one_group()
    found["groups"][0]["members"] = list(who)
    found["speakers"] = [{"name": name, "model": "Nest Mini",
                          "id": name.lower().replace(" ", "-"),
                          "address": "192.168.0.23", "port": 8009, "group": False}
                         for name in who]
    return found


@pytest.fixture
def one_speaker_one_computer(tmp_path, monkeypatch):
    """One speaker muezzin casts to, one group it casts to, one folder, and the computer's
    own speakers: the four answers to "may I ask this thing for a level?"."""
    from muezzin import web as web_module
    monkeypatch.setattr(web_module, "scan_speakers", one_speaker_and_one_group)
    web, out, runner = _serve(tmp_path, CAST_AND_PC)
    try:
        yield web, out, tmp_path
    finally:
        web.stop()
        runner.shutdown()


@pytest.fixture
def a_room_somebody_renamed_since(tmp_path, monkeypatch):
    """The same household, with one `members:` line that outlived the speaker it named:
    written last month, and somebody has since renamed that speaker in the Home app. The
    page cannot invent the name back, and it must not drop the level either."""
    from muezzin import web as web_module
    monkeypatch.setattr(web_module, "scan_speakers", one_speaker_and_one_group)
    web, out, runner = _serve(tmp_path, CAST_WITH_A_STALE_ROOM)
    try:
        yield web, out, tmp_path
    finally:
        web.stop()
        runner.shutdown()


def test_a_speaker_level_lands_in_the_profile_where_the_backend_reads_it(one_speaker_one_computer):
    """The page writes the profile's own word, so the number has to be the one the
    backend will see the next time it plays - and 0 has to mean 0, not "nothing was
    written", which the cast backend would read as its default and shout."""
    web, _, tmp_path = one_speaker_one_computer
    status, reply = call(web.port, "/api/output/volume", {"name": "nest", "volume": 0.35})
    assert status == 200, reply
    assert reply["volume"] == 0.35
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "volume: 0.35" in on_disk, "written as a number, the way a person would have typed it"
    assert web.runner.profile.output("nest").volume == 0.35
    _, st = call(web.port, "/api/state")
    row = next(o for o in st["outputs"] if o["name"] == "nest")
    assert row["volume"] == 0.35, "the slider comes back where the profile put it"
    status, reply = call(web.port, "/api/output/volume", {"name": "nest", "volume": 0})
    assert status == 200 and web.runner.profile.output("nest").volume == 0.0, \
        "a speaker asked to be silent has to be asked to be silent"


def test_a_level_can_be_put_back_to_not_saying_anything(one_speaker_one_computer):
    """`volume: 0.5` and no `volume:` at all do the same thing today, but they are not
    the same sentence: one is this household's decision and the other is whatever the
    speaker's default is tomorrow. Going back to not saying anything is a thing a person
    should be able to do from the page."""
    web, _, tmp_path = one_speaker_one_computer
    call(web.port, "/api/output/volume", {"name": "nest", "volume": 0.8})
    status, reply = call(web.port, "/api/output/volume", {"name": "nest", "volume": ""})
    assert status == 200, reply
    assert reply["volume"] is None
    assert "volume: null" in (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert web.runner.profile.output("nest").volume is None
    _, st = call(web.port, "/api/state")
    row = next(o for o in st["outputs"] if o["name"] == "nest")
    assert row["volume"] is None, "the page says the default, which is what the file now means"


def test_a_computer_has_no_level_for_the_page_to_move(one_speaker_one_computer):
    """The refusal is the point of this feature as much as the slider is. A box on the
    LAN and the machine running muezzin are computers, and a level set on one of them is
    a level the person using that machine loses without being asked; the backend warns
    and ignores a `volume:` on those kinds, and the page refuses to write one in the
    first place. The same goes for a folder, which makes no sound at all."""
    web, _, tmp_path = one_speaker_one_computer
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    for name in ("this-pc", "outbox"):
        status, reply = call(web.port, "/api/output/volume", {"name": name, "volume": 0.2})
        assert status == 400 and "belongs to whoever" in reply["error"], (name, reply)
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert on_disk == before, "a refusal that still wrote a level is not a refusal"
    assert "volume" not in on_disk
    _, st = call(web.port, "/api/state")
    assert {o["name"]: o["takes_volume"] for o in st["outputs"]} == {
        "nest": True, "front-room": True, "outbox": False, "this-pc": False}, \
        "the page is told which kinds it may offer a slider for, rather than guessing"


def test_a_level_that_makes_no_sense_is_refused_before_the_speaker_is_shouted_at(one_speaker_one_computer):
    """A `volume:` of 40 loads - and a Cast device clamps it to full scale, so the house
    gets a shout at Fajr instead of the background level somebody meant. The number is
    checked here, in the same request, so the mistake never reaches the file."""
    web, _, tmp_path = one_speaker_one_computer
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    for payload, why in (({"name": "nest", "volume": 40}, "between 0 and 1"),
                         ({"name": "nest", "volume": "loud"}, "not a level"),
                         ({"name": "nobody", "volume": 0.5}, "no output called nobody"),
                         ({"name": "", "volume": 0.5}, "which output")):
        status, reply = call(web.port, "/api/output/volume", payload)
        assert status == 400 and why in reply["error"], (payload, status, reply)
    assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before


def test_a_group_row_writes_what_every_room_inside_it_will_be_asked_for(one_speaker_one_computer,
                                                                        caplog):
    """The measured reason the page used to refuse this. A level aimed at a Google Home
    group reaches its receiver, which answers with the speakers inside it and the levels
    they are at, and after the ask every one of those numbers is exactly where the Home app
    left it - four speakers, four levels, none of them moved. So for years the honest answer
    was that there was no number to write. Now the backend asks each room inside the group
    over a connection of that room's own and hands each one back when the call ends, which
    makes the number worth writing - and worth saying out loud, because beside a single
    speaker a level is that speaker's level and here it is every room's."""
    web, _, tmp_path = one_speaker_one_computer
    _, st = call(web.port, "/api/state")
    rows = {o["name"]: o for o in st["outputs"]}
    assert rows["front-room"]["target_kind"] == rows["nest"]["target_kind"] == "", \
        "nobody has looked at the network yet, and not knowing is not the same as a group"
    call(web.port, "/api/speakers")               # the look the page takes for itself
    _, st = call(web.port, "/api/state")
    rows = {o["name"]: o for o in st["outputs"]}
    assert rows["front-room"]["target_kind"] == "group"
    assert rows["nest"]["target_kind"] == "speaker", "a speaker of its own keeps its slider"
    assert rows["outbox"]["target_kind"] == "", "a folder is nobody's speaker"
    with caplog.at_level("INFO"):
        status, reply = call(web.port, "/api/output/volume",
                             {"name": "front-room", "volume": 0.4})
    assert status == 200 and reply["volume"] == 0.4, reply
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "volume: 0.4" in on_disk, "the same key the single-speaker rows write"
    assert "Whole-house group is a speaker group" in caplog.text
    assert "every room inside it" in caplog.text, "the log says what the number means here"


def test_the_page_says_what_a_group_row_s_level_does(panel):
    """Where the words live, since a number that behaves differently in two rows has to say
    so before it is pressed and not after. The row for a group's output carries a note about
    what the level does, and the card says what becomes of it, because a level moved for a
    call is a thing a person will notice in the room afterwards if they are not told."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    assert "target_kind=='group'" in html, "the row is still built from what the network said"
    assert "every room inside, each back after" in html, "the row itself says what its number is"
    assert "each room goes back to wherever its owner had left it" in html
    assert "members:" in html, "rooms at levels of their own are pointed at where they go"
    assert "a level written for a group stays unused" not in html, \
        "the sentence that was true when nothing honoured a group's level"
    assert "st.outputs.some(o=>o.takes_volume)" in html, \
        "a fresh page goes and looks at the network, because the row is only honest once "\
        "the page knows whether the name behind it is one speaker or a group"


# ---- one room inside a group, at a level of its own -------------------------
#
# A group's number is one sentence, and a prayer call is not one sentence: one room
# wanted over the call, another wanted low, and both wanted their own level back
# afterwards. The backend can already do that with a `members:` line per room; what it
# could not do before was be written from the page, which meant the only household that
# got per-room levels was the one willing to type speaker names by hand out of an mDNS
# browse. So the group's row grows a slider per room, and the names come from what the
# speakers say they belong to rather than from a box to type in.

def test_a_group_row_offers_each_room_inside_it_its_own_number(one_speaker_one_computer):
    """The list of rooms is not in the group: neither its mDNS record nor its own receiver
    says who is inside it. The last scan built the list by asking every speaker which groups
    it belongs to, and that is what the row is made of - each room with the level the profile
    asks it for, or nothing at all when the room has no line of its own and will be asked for
    the group's number instead."""
    web, _, _ = one_speaker_one_computer
    _, st = call(web.port, "/api/state")
    rows = {o["name"]: o for o in st["outputs"]}
    assert rows["front-room"]["rooms"] == [], "nobody has looked at the network yet"
    call(web.port, "/api/speakers")
    _, st = call(web.port, "/api/state")
    rows = {o["name"]: o for o in st["outputs"]}
    assert rows["front-room"]["rooms"] == [{"name": "Study speaker", "volume": None,
                                            "seen": True}]
    assert rows["front-room"]["rooms_known"] is True
    assert rows["nest"]["rooms"] == [], "a speaker of its own has no rooms inside it"
    assert rows["outbox"]["rooms"] == [], "a folder is nobody's speaker"


def test_a_room_s_level_is_written_under_the_group_that_carries_it(one_speaker_one_computer,
                                                                   caplog):
    """The write is the whole point of the feature, and it has to land where the backend
    reads it: `members:` under that output, the room's own network name, one line each. The
    profile is reloaded in the same request, so the next adhan - which may already be
    running - is asked for what the slider just said."""
    web, _, tmp_path = one_speaker_one_computer
    call(web.port, "/api/speakers")
    with caplog.at_level("INFO"):
        status, reply = call(web.port, "/api/output/room",
                             {"name": "front-room", "speaker": "Study speaker", "volume": 0.35})
    assert status == 200, reply
    assert reply["speaker"] == "Study speaker" and reply["volume"] == 0.35
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "members:" in on_disk and "Study speaker: 0.35" in on_disk, \
        "a name and a number on one line each, the way a person would have typed it"
    assert web.runner.profile.output("front-room").members == {"Study speaker": 0.35}
    _, st = call(web.port, "/api/state")
    row = next(o for o in st["outputs"] if o["name"] == "front-room")
    assert row["rooms"] == [{"name": "Study speaker", "volume": 0.35, "seen": True}], \
        "the slider comes back where the profile put it"
    assert "0.35" in caplog.text and "goes back to" in caplog.text, \
        "the log says what will happen to the room when the call ends"


def test_two_rooms_at_two_levels_and_the_group_at_a_third(one_speaker_one_computer,
                                                          monkeypatch):
    """The shape the feature exists for, seen from the profile's side: one name the schedule
    points at, three different numbers under it, and nothing written anywhere saying what
    either room was at beforehand - that is a fact the speaker is asked for the moment the
    call starts, over a connection of that room's own."""
    from muezzin import web as web_module
    web, _, tmp_path = one_speaker_one_computer
    monkeypatch.setattr(web_module, "scan_speakers",
                        lambda *args, **kw: a_group_of("Kitchen speaker", "Study speaker"))
    call(web.port, "/api/speakers")
    for room, level in (("Kitchen speaker", 0.1), ("Study speaker", 0.2)):
        status, reply = call(web.port, "/api/output/room",
                             {"name": "front-room", "speaker": room, "volume": level})
        assert status == 200, reply
    call(web.port, "/api/output/volume", {"name": "front-room", "volume": 0.5})
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "Kitchen speaker: 0.1" in on_disk and "Study speaker: 0.2" in on_disk
    assert web.runner.profile.output("front-room").volume == 0.5
    assert web.runner.profile.output("front-room").members == {
        "Kitchen speaker": 0.1, "Study speaker": 0.2}


def test_a_room_with_no_line_of_its_own_follows_the_group_again(one_speaker_one_computer):
    """There is no level that means "as it was", because what the room was at is a fact
    about the room and not a choice the profile can make in advance. So going back is
    taking the line out, and an empty `members:` block goes with it: a key left behind
    with nothing under it is the sort of thing that outlives its meaning."""
    web, _, tmp_path = one_speaker_one_computer
    call(web.port, "/api/speakers")
    call(web.port, "/api/output/room",
         {"name": "front-room", "speaker": "Study speaker", "volume": 0.35})
    status, reply = call(web.port, "/api/output/room",
                         {"name": "front-room", "speaker": "Study speaker", "volume": ""})
    assert status == 200, reply
    assert reply["volume"] is None
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "members:" not in on_disk and "Study speaker" in on_disk, \
        "the room's line goes and the name the group is made of stays"
    assert web.runner.profile.output("front-room").members == {}


def test_a_room_the_network_cannot_see_stays_on_the_row_and_says_so(a_room_somebody_renamed_since):
    """Names go stale: a speaker renamed in the Home app, a typo written last month. The
    backend warns when it plays and cannot find the name, and a page that hid the line
    would leave a room playing at a level nobody can account for - so the row keeps it and
    says it is not out there. Writing a fresh name nobody claims is refused (see the next
    test); taking such a name out never is, because that is how a typo gets undone without
    opening the file."""
    web, _, tmp_path = a_room_somebody_renamed_since
    call(web.port, "/api/speakers")
    _, st = call(web.port, "/api/state")
    row = next(o for o in st["outputs"] if o["name"] == "front-room")
    assert [r["name"] for r in row["rooms"]] == ["Study speaker", "Study speakers"]
    assert [r["seen"] for r in row["rooms"]] == [True, False]
    assert row["rooms"][1]["volume"] == 0.3, \
        "the level in the file is shown even when no speaker claims the name"
    status, reply = call(web.port, "/api/output/room",
                         {"name": "front-room", "speaker": "Study speakers", "volume": ""})
    assert status == 200, reply
    assert "members:" not in (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")


def test_a_room_that_is_not_a_room_is_refused(one_speaker_one_computer):
    """Every refusal here is a mistake that would otherwise be found out at Fajr: a level
    written for one speaker under a name the network calls one speaker is a level the
    backend ignores, and a level written for a room the group has no way of finding is a
    room that plays at whatever the Home app left it at. Both are said here, in the same
    request, with the rooms that do exist named back."""
    web, _, tmp_path = one_speaker_one_computer
    call(web.port, "/api/speakers")
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    for payload, why in (
        ({"name": "nest", "speaker": "Study speaker", "volume": 0.5},
         "one speaker and not a group"),
        ({"name": "front-room", "speaker": "Kitchen speaker", "volume": 0.5},
         "no room called Kitchen speaker"),
        ({"name": "front-room", "speaker": "Study speaker", "volume": 3}, "between 0 and 1"),
        ({"name": "front-room", "speaker": "Study speaker", "volume": "loud"}, "not a level"),
        ({"name": "front-room", "speaker": "", "volume": 0.5}, "which room"),
        ({"name": "outbox", "speaker": "Study speaker", "volume": 0.5}, "belongs to whoever"),
    ):
        status, reply = call(web.port, "/api/output/room", payload)
        assert status == 400 and why in reply["error"], (payload, status, reply)
    assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before, \
        "a refusal that still wrote a level is not a refusal"


def test_the_page_says_what_a_rooms_level_does_and_where_it_goes(panel):
    """Where the words live again: a room's slider is a different promise from the group's,
    because it is only in force while a call is playing and the room is left holding
    whatever its owner had it at afterwards. And the fine print has to point at the line
    the page writes, since the point of the sliders is that nobody has to write it."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    assert 'class="roomrow"' in html, \
        "a group's rooms get rows of their own under the group's row, in the table's columns"
    assert "no speaker would say which rooms are inside" in html, \
        "and when the scan could not say what a group holds, the group's own row says that"
    assert "same as the group" in html, "a room with no level of its own says what it follows"
    assert "data-room-name" in html, "the room is named by the network, not typed in here"
    assert "no speaker by that name out there" in html, \
        "a level written for a speaker nobody claims says so on the row"
    assert "back to its own level afterwards" in html, \
        "the room is told what happens to it when the call ends"
    assert "one members: line per room into the profile" in html, \
        "and where the number lands, for whoever reads the file afterwards"


# ---- one prayer, its own rooms, its own numbers -----------------------------
#
# A group's number is one decision, made once, for every time the group is played - and a
# house is not the same house at five in the morning and at two in the afternoon. The
# kitchen wants waking for Fajr; the study wants nothing much for dhuhr. The backend could
# already read a `members:` block under an event, but nothing could write one, so each
# prayer's row carries the line saying what that prayer asks and opens, on request, one
# slider per room that prayer reaches and nothing more.

# The household with the group's standing number written down last month, plus a morning
# prayer that already asks more of every room it plays through than the house usually does.
A_LOUD_MORNING = (CAST_AND_PC
                  .replace('  - name: front-room\n    kind: google_cast\n'
                           '    target: "Whole-house group"\n',
                           '  - name: front-room\n    kind: google_cast\n'
                           '    target: "Whole-house group"\n    volume: 0.2\n')
                  .replace("    media: [fajr.mp3]\n", "    media: [fajr.mp3]\n    volume: 0.5\n"))

# The same house with the morning prayer pointed at a folder instead of a speaker.
A_PRAYER_IN_A_FOLDER = CAST_AND_PC.replace(
    "    media: [fajr.mp3]\n", "    media: [fajr.mp3]\n    targets: [outbox]\n")


# The same house, and a morning prayer with one room's number written under it for a
# speaker that has since been renamed in the Home app: the line is still in the file, it is
# still the number this call will ask for, and nobody out there answers to that name.
A_PRAYER_WITH_A_STALE_ROOM = A_LOUD_MORNING.replace(
    "    media: [fajr.mp3]\n    volume: 0.5\n",
    "    media: [fajr.mp3]\n    volume: 0.5\n    members:\n      Study speakers: 0.7\n")


@pytest.fixture
def a_house_tuned_for_the_morning(tmp_path, monkeypatch):
    """Three rooms the scan can name, the group's own number in the file, and one prayer with
    a number of its own. Three rooms because a test that wants to say "only the room you moved
    got a line" cannot do it with one, and because the study is here both as a speaker of its
    own and as a room of the group, which is the one case where the drawer has to offer a
    speaker once and not twice."""
    from muezzin import web as web_module
    monkeypatch.setattr(web_module, "scan_speakers", lambda *a, **kw: a_group_of(
        "Kitchen speaker", "Tabby speaker", "Study speaker"))
    web, out, runner = _serve(tmp_path, A_LOUD_MORNING)
    try:
        yield web, out, tmp_path
    finally:
        web.stop()
        runner.shutdown()


@pytest.fixture
def a_prayer_with_no_speaker_to_ask(tmp_path):
    """A prayer whose only output is a folder on disk: nothing behind it to ask, and the
    page has to know that without being told by a person who tried."""
    web, out, runner = _serve(tmp_path, A_PRAYER_IN_A_FOLDER)
    try:
        yield web, out, tmp_path
    finally:
        web.stop()
        runner.shutdown()


@pytest.fixture
def a_prayer_whose_room_was_renamed(tmp_path, monkeypatch):
    """The same house as the tuned morning, with the kitchen's number already in the file
    under a name the speakers no longer answer to - which is what a rename in the Home app
    leaves behind, and the state a person has to be able to undo from the page."""
    from muezzin import web as web_module
    monkeypatch.setattr(web_module, "scan_speakers", lambda *a, **kw: a_group_of(
        "Kitchen speaker", "Tabby speaker", "Study speaker"))
    web, out, runner = _serve(tmp_path, A_PRAYER_WITH_A_STALE_ROOM)
    try:
        yield web, out, tmp_path
    finally:
        web.stop()
        runner.shutdown()


def _rows(web, at):
    """One prayer's rooms as the page sees them, keyed by who they are."""
    _, st = call(web.port, "/api/state")
    ev = next(e for e in st["events"] if e["at"] == at)
    return {(r["name"], r["output"]): r for r in ev["levels"]}, ev


def test_a_prayer_offers_only_the_rooms_it_reaches(a_house_tuned_for_the_morning):
    """The rooms a prayer can be tuned for are not every speaker on the network: they are
    the rooms of the outputs this prayer plays through, each with two numbers. One is what
    the room is asked for if this prayer says nothing about it, which is the house's own
    number and the reason an untuned prayer is a line of text and not four sliders; the
    other is what it will actually be asked for, tonight, with this prayer in the way."""
    web, _, _ = a_house_tuned_for_the_morning
    call(web.port, "/api/speakers")
    rows, ev = _rows(web, "fajr")
    assert sorted(rows) == [("Kitchen speaker", "front-room"), ("Study speaker", "nest"),
                            ("Tabby speaker", "front-room")], \
        "the group spelled out as the rooms the scan named, and the one speaker as itself"
    assert ("Study speaker", "front-room") not in rows, \
        ("the study reaches this prayer twice over, as a speaker and as a room of the group, "
         "and a drawer with two sliders writing one line is a drawer that lies about one")
    assert ev["volume"] == 0.5 and ev["members"] == {}, "the prayer speaks, but of all rooms at once"
    assert all(r["written"] is None for r in rows.values()), "nothing tuned yet"
    assert rows[("Kitchen speaker", "front-room")]["usual"] == 0.5, \
        "the number the room is asked for when the prayer says nothing is the prayer's own"
    assert rows[("Kitchen speaker", "front-room")]["tonight"] == 0.5
    assert rows[("Study speaker", "nest")]["group"] is False, \
        "one speaker is not a group of one: the name written is the name in target:"
    _, dhuhr = _rows(web, "dhuhr")
    rooms = [r for r in dhuhr["levels"] if r["output"] == "front-room"]
    assert [r["tonight"] for r in rooms] == [0.2] * len(rooms), \
        "a prayer with nothing to say about level falls back to the group's standing number"


def test_a_prayer_s_level_is_written_under_the_prayer_and_nowhere_else(a_house_tuned_for_the_morning,
                                                                      caplog):
    """The line has to sit where the backend reads it, which is one level deeper than the
    group's: same word, same shape, under the event. And only the rooms that were moved get
    a line - a prayer that leaves the study alone has nothing to say about the study, and a
    profile filled with lines spelling out what was not changed is a profile nobody maintains."""
    web, _, tmp_path = a_house_tuned_for_the_morning
    call(web.port, "/api/speakers")
    with caplog.at_level("INFO"):
        status, reply = call(web.port, "/api/event/room",
                             {"at": "fajr", "friday": False, "speaker": "Kitchen speaker",
                              "volume": 0.6})
    assert status == 200, reply
    assert reply["volume"] == 0.6 and reply["speaker"] == "Kitchen speaker"
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    inside = on_disk.split("  - name: fajr-adhan")[1].split("  - name: dhuhr-nudge")[0]
    assert re.search(r"^    members:\n      Kitchen speaker: 0\.6\s*$", inside, re.M), \
        "one line, under the prayer that asked for it, at the depth the prayer's fields sit at"
    assert on_disk.count("members:") == 1, "the group's own line was not touched on the way past it"
    assert "Tabby speaker" not in on_disk, \
        "the rooms left alone stay unmentioned: their levels are facts about the house"
    assert web.runner.profile.output("front-room").members == {}
    assert next(e for e in web.runner.profile.events if e.at == "fajr").members == \
        {"Kitchen speaker": 0.6}
    rows, _ = _rows(web, "fajr")
    assert rows[("Kitchen speaker", "front-room")]["written"] == 0.6
    assert rows[("Kitchen speaker", "front-room")]["tonight"] == 0.6, "the ask this call will make"
    assert rows[("Tabby speaker", "front-room")]["tonight"] == 0.5, \
        "the room nobody named follows the prayer's own number, not the group's"
    assert "for this prayer alone" in caplog.text and "goes back to" in caplog.text, \
        "the log has to say which prayer, and that the room is handed its old level back"


def test_the_log_says_which_kind_of_speaker_keeps_its_level(tmp_path, monkeypatch, caplog):
    """Two of these rooms are on loan and one is not. A room of a group is asked for a level
    over a connection this program opened for the call, so it is handed back the number it was
    at when the call ends; a speaker the profile points at directly has a level of its own, and
    asking it for another one is what that output's `volume:` has always done - it stays put
    afterwards. Same slider, two different promises, and the person who moved it is owed the
    difference. The study is kept out of the scanned group here on purpose: the house where a
    speaker is inside the group as well is the other case, where the borrowing wins."""
    from muezzin import web as web_module
    found = one_speaker_and_one_group()
    found["groups"][0]["members"] = ["Kitchen speaker", "Tabby speaker"]
    monkeypatch.setattr(web_module, "scan_speakers", lambda *a, **kw: found)
    web, out, runner = _serve(tmp_path, A_LOUD_MORNING)
    try:
        call(web.port, "/api/speakers")
        with caplog.at_level("INFO"):
            for room, level in (("Kitchen speaker", 0.6), ("Study speaker", 0.45)):
                status, reply = call(web.port, "/api/event/room",
                                     {"at": "fajr", "friday": False, "speaker": room,
                                      "volume": level})
                assert status == 200, reply
    finally:
        web.stop()
        runner.shutdown()
    said = [r.getMessage() for r in caplog.records if "for this prayer alone" in r.getMessage()]
    assert len(said) == 2, said
    assert "goes back to the level it was at when the call ends" in said[0], \
        "a borrowed room gets its own number back: " + said[0]
    assert "keeps that level after the call" in said[1], \
        "a speaker of its own is left where it was asked to be: " + said[1]
    assert "Study speaker: 0.45" in (tmp_path / "muezzin.yaml").read_text(encoding="utf-8"), \
        "and the line is written the same either way: the difference is what happens next"


def test_a_prayer_that_says_nothing_of_its_own_leaves_nothing_behind(a_house_tuned_for_the_morning):
    """Undoing a prayer's level is taking the line out, and an emptied `members:` key goes
    with it: the same bargain as a room on the Outputs card, for the same reason. Where a
    speaker was left sitting is a fact about that speaker, and no number written in a
    profile can claim to know it in advance."""
    web, _, tmp_path = a_house_tuned_for_the_morning
    call(web.port, "/api/speakers")
    call(web.port, "/api/event/room",
         {"at": "fajr", "friday": False, "speaker": "Kitchen speaker", "volume": 0.6})
    status, reply = call(web.port, "/api/event/room",
                         {"at": "fajr", "friday": False, "speaker": "Kitchen speaker",
                          "volume": ""})
    assert status == 200, reply
    assert reply["volume"] is None
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "members:" not in on_disk, "the emptied block is not left outliving its meaning"
    assert next(e for e in web.runner.profile.events if e.at == "fajr").members == {}
    rows, _ = _rows(web, "fajr")
    assert rows[("Kitchen speaker", "front-room")]["written"] is None
    assert rows[("Kitchen speaker", "front-room")]["tonight"] == 0.5


def test_a_friday_prayer_and_the_everyday_one_are_two_lines(a_house_tuned_for_the_morning):
    """The day-scope is part of which entry a number belongs to, not a detail of it: a
    kitchen tuned for Friday's asr is not a kitchen tuned for Tuesday's, and there is no
    everyday asr in this profile to write the number into instead."""
    web, _, tmp_path = a_house_tuned_for_the_morning
    call(web.port, "/api/speakers")
    status, reply = call(web.port, "/api/event/room",
                         {"at": "asr", "friday": True, "speaker": "Kitchen speaker",
                          "volume": 0.45})
    assert status == 200, reply
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "    members:\n      Kitchen speaker: 0.45" in on_disk.split("  - name: friday-tune")[1]
    assert "  - name: fajr-adhan" in on_disk.split("    members:")[0], \
        "the Friday entry is the one below the line, not the one above it"
    assert next(e for e in web.runner.profile.events
                if any(str(d).lower().startswith("fri") for d in (e.days or ()))).members == \
        {"Kitchen speaker": 0.45}
    assert next(e for e in web.runner.profile.events if e.at == "fajr").members == {}
    status, reply = call(web.port, "/api/event/room",
                         {"at": "asr", "friday": False, "speaker": "Kitchen speaker",
                          "volume": 0.45})
    assert status == 400 and "no prayer at asr" in reply["error"], \
        "there is no everyday asr here, and the number does not go looking for one"


def test_a_name_the_speakers_are_not_claiming_is_refused_for_a_prayer_too(a_house_tuned_for_the_morning):
    """The same guard as a room on a group's row, for the same reason: a name typed while
    the speakers are answering is a line the backend will only mention as a warning at Fajr,
    by which time the kitchen is playing at whatever the Home app left it at. The names that
    do exist are said back, because that is the fix."""
    web, _, tmp_path = a_house_tuned_for_the_morning
    call(web.port, "/api/speakers")
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    for payload, why in (
        ({"at": "fajr", "speaker": "Bedroom speaker", "volume": 0.5},
         "not a speaker this prayer plays through"),
        ({"at": "fajr", "speaker": "Kitchen speaker", "volume": 3}, "between 0 and 1"),
        ({"at": "fajr", "speaker": "Kitchen speaker", "volume": "loud"}, "not a level"),
        ({"at": "fajr", "speaker": "", "volume": 0.5}, "which room"),
        ({"at": "", "speaker": "Kitchen speaker", "volume": 0.5}, "which prayer"),
        ({"at": "maghrib", "speaker": "Kitchen speaker", "volume": 0.5}, "no prayer at maghrib"),
    ):
        status, reply = call(web.port, "/api/event/room", payload)
        assert status == 400 and why in reply["error"], (payload, status, reply)
    status, reply = call(web.port, "/api/event/room",
                         {"at": "fajr", "speaker": "Bedroom speaker", "volume": 0.5})
    assert "Kitchen speaker" in reply["error"], "the names that do exist, named back"
    assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before, \
        "a refusal that still wrote a level is not a refusal"


def test_a_group_that_would_not_name_its_rooms_does_not_get_the_other_groups_answer(tmp_path,
                                                                                    monkeypatch):
    """The other half of the guard: a refusal about a room name needs every output this
    prayer plays through to have answered about its rooms. What one group says about
    itself says nothing about what a different group that would not say contains, and a
    name typed at that one may be perfectly real - the backend is the place that finds
    out, with a warning in the morning's log, rather than the page turning one group's
    silence into a verdict about another's."""
    from muezzin import web as web_module

    def two_groups(*a, **kw):
        found = a_group_of("Kitchen speaker", "Tabby speaker", "Study speaker")
        found["groups"].append({"name": "Upstairs group", "id": "xyz", "group": True,
                                "members": [], "membership_known": False, "silent": []})
        return found

    monkeypatch.setattr(web_module, "scan_speakers", two_groups)
    text = A_LOUD_MORNING.replace(
        '  - name: nest\n',
        '  - name: upstairs\n    kind: google_cast\n    target: "Upstairs group"\n'
        '  - name: nest\n')
    web, _, runner = _serve(tmp_path, text)
    try:
        call(web.port, "/api/speakers")
        status, reply = call(web.port, "/api/event/room",
                             {"at": "fajr", "friday": False, "speaker": "Hall speaker",
                              "volume": 0.35})
        assert status == 200, reply
        on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
        assert "      Hall speaker: 0.35" in on_disk, \
            "a name typed while one group kept silent is written, not judged"
        assert next(e for e in web.runner.profile.events
                    if e.at == "fajr").members == {"Hall speaker": 0.35}
    finally:
        web.stop()
        runner.shutdown()


def test_a_prayer_in_the_file_the_running_daemon_has_not_loaded_says_so(a_house_tuned_for_the_morning):
    """The file on disk and the profile in the running daemon can get out of step - a line
    added by an editor outside the page, before the reload lands - and a number asked of a
    prayer only the file knows has to be answered with exactly that, rather than with a
    complaint about outputs that were never pointed at a prayer the daemon has not loaded."""
    web, _, tmp_path = a_house_tuned_for_the_morning
    path = tmp_path / "muezzin.yaml"
    on_disk = path.read_text(encoding="utf-8")
    path.write_text(on_disk.replace(
        "    media: [fajr.mp3]\n    volume: 0.5\n",
        "    media: [fajr.mp3]\n    volume: 0.5\n"
        "  - name: isha-adhan\n    at: isha\n    media: [fajr.mp3]\n"), encoding="utf-8")
    status, reply = call(web.port, "/api/event/room",
                         {"at": "isha", "friday": False, "speaker": "Kitchen speaker",
                          "volume": 0.5})
    assert status == 400 and "has not loaded it" in reply["error"], reply
    assert "plays through nothing" not in reply["error"], \
        "the outputs are not the problem: the daemon never saw this prayer"


def test_a_prayer_pointed_at_a_folder_has_no_levels_to_give(a_prayer_with_no_speaker_to_ask):
    """A prayer that plays through a folder, or through the computer's own speakers, has no
    rooms: the level of a computer belongs to whoever is sitting at it. The row says so
    instead of offering sliders, and the write is refused rather than writing a line the
    backend will never read."""
    web, _, tmp_path = a_prayer_with_no_speaker_to_ask
    rows, ev = _rows(web, "fajr")
    assert rows == {} and ev["levels"] == [], "a folder has no rooms and none are invented"
    status, reply = call(web.port, "/api/event/room",
                         {"at": "fajr", "speaker": "Kitchen speaker", "volume": 0.5})
    assert status == 400 and "nothing muezzin can ask for a level" in reply["error"], reply
    assert "members:" not in (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")


def test_a_name_the_speakers_no_longer_answer_to_is_listed_and_undoable(a_prayer_whose_room_was_renamed):
    """A prayer's `members:` line outlives the speaker it named: renamed in the Home app,
    moved off the network, asleep. The line is still in the file and still changes what gets
    asked, so the drawer lists it as itself, says nobody out there answers to it, and lets it
    be taken out here instead of sending somebody into the YAML to find it."""
    web, _, tmp_path = a_prayer_whose_room_was_renamed
    call(web.port, "/api/speakers")
    rows, ev = _rows(web, "fajr")
    assert sorted(rows) == [("Kitchen speaker", "front-room"), ("Study speaker", "nest"),
                            ("Study speakers", ""), ("Tabby speaker", "front-room")], \
        "the name nobody claims is listed as itself, not hidden because the scan moved on"
    stale = rows[("Study speakers", "")]
    assert stale["seen"] is False and stale["written"] == 0.7
    assert stale["tonight"] == 0.7, "and it is still the number this call will ask for"
    assert all(r["seen"] for r in rows.values() if r["name"] != "Study speakers")
    status, reply = call(web.port, "/api/event/room",
                         {"at": "fajr", "friday": False, "speaker": "Study speakers",
                          "volume": ""})
    assert status == 200, ("taking a stale name out is never refused", reply)
    assert "members:" not in (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    rows, ev = _rows(web, "fajr")
    assert ev["members"] == {}, "the profile in memory is what the page said it was"
    assert ("Study speakers", "") not in rows, "and the line leaves the drawer with the file"


def test_the_page_gives_a_prayer_its_own_collapsible_line(panel):
    """The rooms are four sliders and a prayer has two of them, which is how the Sound card
    used to be a wall. So a prayer's row carries one line that says what that prayer asks -
    as usual, or the rooms that were tuned, or how many - and the sliders only appear when
    that line is pressed. The words have to be in the page either way: a person deciding
    whether to press it needs to know what is behind it, and that the number there outranks
    the one the Outputs card holds is the whole reason the line is here and not there."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    assert 'class="lvrow"' in html, "the sliders live in a row of their own under the prayer"
    assert "levels: as usual" in html, "a prayer with nothing of its own to say says it in words"
    assert "rooms tuned" in html, "and once there are too many to spell out, it counts them"
    assert "data-lv-name" in html, "the room is named by the network, not typed in here"
    assert "same as usual" in html, "and taking the line out is a button, not an errand into the file"
    assert "not a speaker this prayer plays through" in html, \
        "a name that outlived its place in this prayer stays where it can be undone"
    assert "no level for it to ask" in html, \
        "a prayer that reaches no speaker muezzin casts to says that, instead of an empty box"
    assert "number written here outranks the one the Outputs card holds" in html, \
        "where the number wins from, said on the card that writes it"
    assert "back to its own level when the call ends" in html, \
        "a room of a group is on loan for the length of one call, and the slider says so"
    assert "keeps that level after the call" in html, \
        "and a speaker the profile points at directly is not on loan: that level outlives the call"
    assert "dataset.open" in html, \
        "which prayer is open is kept on the table, so the next poll cannot shut it in a hand"

# ---- the folder of recordings, which is the library -------------------------
#
# There is no list of recordings anywhere but on disk: media_dir is the library, and a
# recording exists in a profile only as a name in an event's playlist or in the hold
# list. So the page works on those names, and the tests below are about what a name is
# allowed to do: be held out of the random drawing, be added to the end of a playlist,
# and - the one with no undo - be deleted, which only happens once nothing plays it.

def test_the_folder_listing_says_who_plays_each_recording(panel):
    """Three questions get asked of the folder: how big is it, is anything playing it, and is
    it held back from the drawing. The page shows the first and the third, and answers the
    second with the column that changes it - the event a recording gets put on - rather than
    with a column of words that could only agree with it or fall behind it. The answer still
    carries the names, because the guard in front of the one action with no undo has to say
    which event is in the way, and it reads that same list. A recording two events share is
    one row with both names on it, because the file is one file - deleting it would take two
    prayers down."""
    web, _, _ = panel
    _, st = call(web.port, "/api/state")
    rows = {r["name"]: r for r in st["media_library"]}
    assert sorted(rows) == ["dua.mp3", "fajr.mp3"]
    assert rows["fajr.mp3"]["named_by"] == ["fajr-adhan"]
    assert rows["dua.mp3"]["named_by"] == ["dhuhr-nudge", "friday-tune"]
    assert all(r["bytes"] == 8 for r in rows.values()), "the size is read from the file"
    assert all(not r["excluded"] and not r["missing"] for r in rows.values())
    assert st["media_files"] == ["dua.mp3", "fajr.mp3"], \
        "the clip pickers still get a plain list of names"


def test_a_hold_whose_file_is_gone_is_listed_and_can_be_let_go(tmp_path):
    """A name under `library: exclude:` with no file behind it is a line in the profile
    that means nothing, and it stays there for years unless the page can see it. Leaving
    such a name off the listing would strand it where only a text editor can reach it."""
    profile, _ = profile_for(tmp_path, BASE + "\nlibrary:\n  exclude: [gone.mp3, dua.mp3]\n")
    runner = Runner(profile)
    web = WebPanel(runner, port=0)
    web.start()
    try:
        _, st = call(web.port, "/api/state")
        rows = {r["name"]: r for r in st["media_library"]}
        assert rows["gone.mp3"]["missing"] and rows["gone.mp3"]["excluded"]
        assert rows["gone.mp3"]["bytes"] is None, "there are no bytes to report"
        assert rows["dua.mp3"]["excluded"] and not rows["dua.mp3"]["missing"]
        status, reply = call(web.port, "/api/library/hold",
                             {"name": "gone.mp3", "excluded": False})
        assert status == 200, reply
        text = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
        assert "gone.mp3" not in text and "dua.mp3" in text
    finally:
        web.stop()
        runner.shutdown()


def test_holding_a_recording_out_of_the_drawing_lands_in_the_profile(panel):
    """The hold has to be a line in the file, because the drawing reads the file: a
    checkbox that lived only in the page would be forgotten the next time an event drew
    at random, which is the next morning. Letting go leaves an empty list rather than a
    key with nothing under it, which is what a person would have written by hand."""
    web, _, tmp_path = panel
    status, reply = call(web.port, "/api/library/hold", {"name": "dua.mp3", "excluded": True})
    assert status == 200, reply
    text = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "exclude: [dua.mp3]" in text, "a hold is a line in the profile, not page state"
    assert reply["held_back"] == ["dua.mp3"]
    status, reply = call(web.port, "/api/library/hold", {"name": "fajr.mp3", "excluded": True})
    assert status == 200 and reply["held_back"] == ["dua.mp3", "fajr.mp3"], \
        "the second name joins the list instead of replacing the first"
    _, st = call(web.port, "/api/state")
    assert {n: r["excluded"] for n, r in
            ((r["name"], r) for r in st["media_library"])} == {"dua.mp3": True, "fajr.mp3": True}
    assert st["media_files"] == ["dua.mp3", "fajr.mp3"], "nothing was deleted or moved"
    status, reply = call(web.port, "/api/library/hold", {"name": "dua.mp3", "excluded": False})
    assert status == 200 and reply["held_back"] == ["fajr.mp3"]
    status, reply = call(web.port, "/api/library/hold", {"name": "dua.mp3", "excluded": False})
    assert status == 200 and reply.get("unchanged") is True, \
        "pressing a switch that is already where you want it writes nothing"
    assert "exclude: [fajr.mp3]" in (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")


def test_a_hold_from_the_page_reaches_the_daemon_that_is_running(panel):
    """The whole point of writing the hold into the profile is that the daemon drawing
    at random reads the same profile, so the switch counts from the next fire, not from
    the next restart. Nothing here asks for a reload."""
    web, _, _ = panel
    for name in ("fajr.mp3", "dua.mp3"):
        assert call(web.port, "/api/library/hold", {"name": name, "excluded": True})[0] == 200
    assert web.runner.profile.random_picks(2) == [], \
        "the daemon already running knows the hold list"
    assert web.runner.profile.library() == ["dua.mp3", "fajr.mp3"], \
        "held back is not the same as gone: the folder still has both"


def test_a_hold_cannot_invent_a_recording_or_a_path(panel):
    """A hold is a name in the folder, and the pool it comes out of is the folder: a name
    that is not there is a line explaining nothing, and a path is a way of asking about
    files the media server will not serve anyway. Both are refused, and nothing is written."""
    web, _, tmp_path = panel
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    for payload, why in (({"name": "nope.mp3", "excluded": True}, "there is no nope.mp3"),
                         ({"name": "../outside.mp3", "excluded": True}, "no path in it"),
                         ({"name": "sub/dir.mp3", "excluded": True}, "no path in it"),
                         ({"name": "", "excluded": True}, "plain file name")):
        status, reply = call(web.port, "/api/library/hold", payload)
        assert status == 400 and why in reply["error"], (payload, status, reply)
    assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before


def test_a_recording_an_event_still_plays_refuses_to_be_deleted(panel):
    """Deleting a recording is the one thing on this page with no undo, so the guard sits
    in front of it: an event that still holds the name would fire at its minute into a
    file that is not there. The refusal says which events, in the words the row next to
    them shows, because the fix is a different clip and the page has to say for what."""
    web, _, tmp_path = panel
    status, reply = call(web.port, "/api/library/delete", {"name": "dua.mp3"})
    assert status == 400, reply
    assert "dhuhr-nudge" in reply["error"] and "friday-tune" in reply["error"], \
        "every event holding the name is named, not just the first"
    assert (tmp_path / "media" / "dua.mp3").is_file(), "refused means nothing was deleted"
    _, st = call(web.port, "/api/state")
    assert "dua.mp3" in st["media_files"]


def test_a_recording_nothing_plays_can_be_deleted_and_the_listing_follows(panel):
    """Once no event holds the name, the folder is the only place the recording lives, and
    one delete takes it out of the folder, out of the state and off the page. The daemon
    is not restarted to notice: the listing is the folder."""
    web, _, tmp_path = panel
    status, reply = post_raw(web.port, "/api/media/upload?name=spare.mp3", b"ID3\x03fake")
    assert status == 200, reply
    status, reply = call(web.port, "/api/library/delete", {"name": "spare.mp3"})
    assert status == 200 and reply["deleted"] == "spare.mp3", reply
    assert not (tmp_path / "media" / "spare.mp3").exists()
    _, st = call(web.port, "/api/state")
    assert st["media_files"] == ["dua.mp3", "fajr.mp3"]
    assert [r["name"] for r in st["media_library"]] == ["dua.mp3", "fajr.mp3"]


def test_deleting_a_recording_lets_its_hold_go_with_it(panel):
    """A hold is a name, and a name with no file behind it can never mean anything again.
    Leaving it in the profile would be a line about a recording that does not exist, with
    nothing left to explain why it was ever written."""
    web, _, tmp_path = panel
    status, _ = post_raw(web.port, "/api/media/upload?name=spare.mp3", b"ID3\x03fake")
    assert status == 200
    assert call(web.port, "/api/library/hold",
                {"name": "spare.mp3", "excluded": True})[0] == 200
    text = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "exclude: [spare.mp3]" in text, text
    status, reply = call(web.port, "/api/library/delete", {"name": "spare.mp3"})
    assert status == 200 and reply["was_held_back"] is True, reply
    assert "exclude: []" in (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")


def test_putting_a_recording_on_an_event_adds_it_after_what_it_already_plays(panel):
    """The clip boxes in the Sound card choose what a prayer starts with; this adds to the
    end of the playlist, which is the difference between changing the adhan and asking for
    a dua after it. Named files play in the order they are written, so the reply says the
    order out loud rather than leaving the file to be read."""
    web, _, tmp_path = panel
    status, reply = call(web.port, "/api/library/insert",
                         {"name": "dua.mp3", "event": "fajr-adhan"})
    assert status == 200, reply
    assert reply["playlist"] == ["fajr.mp3", "dua.mp3"], "the order is the order it plays in"
    assert "media: [fajr.mp3, dua.mp3]" in (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    _, st = call(web.port, "/api/state")
    assert next(e for e in st["events"] if e["name"] == "fajr-adhan")["media"] == \
        ["fajr.mp3", "dua.mp3"]
    row = next(r for r in st["media_library"] if r["name"] == "dua.mp3")
    assert row["named_by"] == ["fajr-adhan", "dhuhr-nudge", "friday-tune"], \
        "who plays it is read off the events, in the order the file writes them"
    status, reply = call(web.port, "/api/library/insert",
                         {"name": "dua.mp3", "event": "fajr-adhan"})
    assert status == 400 and "already plays" in reply["error"], reply


def test_an_insert_that_leads_nowhere_is_refused_before_anything_is_written(panel):
    """An event name typed into the box, a recording that is not in the folder and a
    recording that is not audio are all the same mistake: the request cannot be carried
    out, so the file stays as it was. A `volume:`-style audio check matters because the
    loader lets a playlist name anything, and a text file reaches a speaker at 5 am."""
    web, _, tmp_path = panel
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    (tmp_path / "media" / "notes.txt").write_text("not audio at all", encoding="utf-8")
    for payload, why in (({"name": "dua.mp3", "event": "nope"}, "no event called nope"),
                         ({"name": "dua.mp3", "event": "   "}, "which event"),
                         ({"name": "gone.mp3", "event": "fajr-adhan"}, "there is no gone.mp3"),
                         ({"name": "../outside.mp3", "event": "fajr-adhan"}, "no path in it"),
                         ({"name": "notes.txt", "event": "fajr-adhan"}, "not audio")):
        status, reply = call(web.port, "/api/library/insert", payload)
        assert status == 400 and why in reply["error"], (payload, status, reply)
    assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before
    (tmp_path / "media" / "notes.txt").unlink()


def test_the_recordings_card_is_a_table_that_fits_its_card(panel):
    """The Outputs card is the one that had a button fall outside it, and this card has the
    same shape - names nobody controls, then the buttons - so it is built the same way on
    purpose. A recording is called whatever whoever put it in the folder called it, and a
    table left to size itself lets that name push the delete button past the border. Four
    columns, not five: which events hold a recording's name used to be said twice, once as a
    column of words and once by the Event column whose dropdown is the event the recording
    gets put on - and a column that can only agree with its neighbour or fall behind it is a
    fifth of the card spent repeating itself, when the delete underneath already says which
    event is in the way. The switch column is weighed at both ends of its range, because a
    percentage is a width only against a window: the phone's, and the narrowest desk window
    this set serves."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    assert '<section class="wide"><h2>Recordings in the folder</h2>' in html, \
        "four columns of names take the width of the page, not one column of it"
    assert "#libtbl { table-layout:fixed }" in html, \
        "the columns are told their widths instead of growing to their words"
    widths, phone = column_widths(html, "#libtbl")
    assert len(widths) == 4, "every column is given a width"
    assert sum(widths) == 100, f"the columns add up to {sum(widths)}%"
    assert len(phone) == 4, "every column is given a width for a phone as well"
    assert sum(phone) == 100, f"the phone's columns add up to {sum(phone)}%"
    assert "<th>name</th><th>size</th><th>Random</th><th>Event</th>" in html, \
        "the two columns a person works with are called what they are for: the random drawing, " \
        "and the event the recording goes on"
    assert "<th>played by</th>" not in html and "<th>in the drawing</th>" not in html, \
        "the column of words that said which events play a recording is gone, because the " \
        "Event column is where that is done, and the daemon names the event that is in the way " \
        "of a delete that would leave one behind"
    assert "<td colspan=4>nothing in" in html, \
        "the row that says the folder is empty spans the four columns this table has"
    desk = 621 - 44 - 32          # the narrowest window this set of widths serves
    px = desk * widths[2] / 100
    assert px >= 38 + 8, \
        f"the switch column of this card is {px:.0f}px at the narrow end of its range, and the " \
        f"switch standing in it is 38px across, plus the 8px a cell keeps on its right"
    assert "#libtbl td { overflow-wrap:break-word }" in html, \
        "a long name breaks at the edge of its own cell rather than leaving the card"
    assert "#libtbl th:nth-child(3), #libtbl td:nth-child(3) { text-align:center }" in html and \
        "#libtbl th:last-child, #libtbl td:last-child { text-align:center }" in html, \
        "the switch and the buttons stand in the middle of the columns they were given: a " \
        "control is one small thing in a column much wider than itself, and buttons that begin " \
        "wherever the longest word in the row leaves them read as a list that lost its edge"
    assert 'id="library"' in html and 'data-hold="' in html and 'data-rm="' in html, \
        "a row is worked on by its name, which is what the profile holds"
    assert "sure? gone for good" in html, "the button with no undo asks once before it acts"
    assert "'.switch[data-name]'" in html, \
        "the on/off switch of an output and the switch of a recording look alike and " \
        "must not share a handler"


def test_the_speakers_card_is_a_table_that_fits_its_card(panel):
    """The Outputs card lost its test button to the edge of the card, and the Recordings card
    was built the same way on purpose. The Speakers card was neither: it was the one table on
    the page left to size itself, because on a desk its rows are short. On a phone they are
    not, and this is the card with the worst words to hold - a name the person typed into the
    speaker itself, an address that is one unbroken word with no space in it anywhere, and the
    speaker's maker's own phrase for what the thing is. The table grew wider than the card
    around it, and the last column, the use button, sat outside the border. So this card's
    columns are told their widths too, on a desk and on a phone, and on a phone the address
    gives most of its width to the buttons: an address read across three lines still says
    which box it is, while a button that fell off the card says nothing to anybody."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    assert '<table id="foundtbl">' in html, \
        "the speaker table needs a name of its own before it can be told its columns"
    assert "#foundtbl { table-layout:fixed }" in html, \
        "the columns are told their widths instead of growing to their words"
    widths, phone = column_widths(html, "#foundtbl")
    assert len(widths) == 5, "every column is given a width"
    assert sum(widths) == 100, f"the columns add up to {sum(widths)}%"
    assert len(phone) == 5, "every column is given a width for a phone as well"
    assert sum(phone) == 100, f"the phone's columns add up to {sum(phone)}%"
    assert phone[4] > phone[2], \
        f"the button column of a phone row is {phone[4]}% and the address column {phone[2]}%: " \
        f"the words of the speaker's maker give way to the thing a person presses"
    assert "#foundtbl td { overflow-wrap:break-word }" in html, \
        "192.168.1.40:8006 is one word the width of a card, and it breaks at its own edge"
    assert '<span class="known">' in html and "stop using</button>" in html, \
        "a row says which output the box is already in use as, then offers to stop it; with no " \
        "cell on this page told to keep its words on one line, both of those take the room they " \
        "need inside the card"
    assert 'id="found"' in html and 'colspan=5' in html, \
        "the table got a name of its own to be told, and the rows it builds still answer to found"


def test_the_events_card_is_the_timetable_and_opens_on_today(panel):
    """The list the daemon sends covers today and the two days after it, which on a house
    with five calls a day is fourteen lines in a card that gets asked two things: what
    happens next, and what tomorrow holds. So the card draws one day at a time. The day is
    named once, in a strip above the table, with an arrow each side of it, and the rows under
    it carry a clock instead of a date because the date has already been said. The keyboard's
    left and right keys walk the same walk, and give it up while the cursor is inside
    something being typed into. The whole list is one press away for anybody who wants the wall.
    This card is the timetable now: the card that spelled out each day's prayer times drew the
    same minutes twice, and it is gone - which is why the card is called Events and not Next
    events, and why it opens on the day the household is standing in rather than on the first
    line of the list, which can be an evening that is already over."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    assert "<section><h2>Events</h2>" in html, \
        "a card that holds the whole planned fortnight is not called Next anything"
    assert "Timetable" not in html and 'id="days"' not in html, \
        "the second copy of the same minutes is gone, and with it the box it was drawn in"
    assert "st.days.map" not in html, \
        "the day blocks were built by walking the day list; nothing walks it that way now"
    assert '<div class="daynav">' in html and 'id="upprev"' in html and 'id="upnext"' in html, \
        "a day of the list can only be folded away if the page says which day it is showing"
    assert 'aria-label="the day before"' in html and 'aria-label="the day after"' in html, \
        "an arrow is a picture, so the word for it has to be there for a reader"
    assert 'id="upday"' in html and 'id="upalldays"' in html, \
        "the day being shown is named, and every day of it is one press away"
    assert ">all the days</button>" in html and "'just this day'" in html, \
        "the button says what pressing it does, in both directions"
    assert "let upday=null, upall=false" in html, \
        "which day is showing is remembered, not asked of the clock: this page redraws " \
        "itself every few seconds, and a card that jumped back to today mid-read is worse " \
        "than the wall it replaced"
    assert "(st.days&&st.days[0]&&st.days[0].date)||''" in html, \
        "today is the day the daemon calls today, in the profile's timezone, and not the " \
        "date whatever the phone happens to be set to"
    assert "if(upday===null || !by[upday]) upday=upToday(order)" in html, \
        "the card opens on today, not on the first line of the list the daemon sent"
    assert "for(const day of order) if(day>=d) return day;" in html, \
        "late at night today has no calls left in it, and then the day to open on is the " \
        "next one that has any"
    assert "'#refresh').onclick=()=>act(()=>{ upday=null;" in html, \
        "refresh is the one gesture that starts the card over on today, and act() loads " \
        "once afterwards rather than the handler loading a second time"
    assert "e.when.slice(-5)" in html and "when.slice(0,-6)" in html, \
        "the date of the day comes out of every row and into the strip above the table, " \
        "which is what lets the first column be a clock"
    assert "' (today)'" in html and "upMarks(upday)" in html, \
        "the strip says when the day it names is today, and carries that day's occasions, " \
        "which is where the pills went when the day blocks did"
    assert "'ArrowLeft'" in html and "'ArrowRight'" in html, \
        "the two keys a hand reaches for on its own walk the day the way the arrows do"
    assert "tag==='INPUT'||tag==='SELECT'||tag==='TEXTAREA'" in html, \
        "an arrow key inside the YAML box, a name being renamed or a dropdown of an event " \
        "belongs to that control and not to this card"
    assert "#upprev, #upnext { min-width:38px }" in html, \
        "an arrow is wider than the character it is drawn with, so a finger or a mouse can find it"
    _, _, narrow = html.partition(NARROW)
    assert "#upprev, #upnext { min-width:44px" in narrow, \
        "on a phone the arrows are as big as everything else a finger aims at"
    assert ".daynav { display:flex" in html and "flex-wrap:wrap" in html, \
        "the name of a day beside four controls is wider than a phone card, and the strip " \
        "wraps under it instead of pushing an arrow out of the card"
    widths, phone = column_widths(html, "#uptbl")
    desk = 621 - 44 - 32
    px = desk * widths[0] / 100
    assert px >= 38 + 8, \
        f"the when column is {px:.0f}px at the narrowest window the desktop rules serve, and " \
        f"a clock at this page's own 14px is about 38px across with 8px of the column kept " \
        f"back by the cell"
    assert "<td colspan=4>nothing scheduled in the next two days" in html, \
        "a quiet schedule is still said inside the table rather than leaving it blank"
    # The card cuts a row's date off the end of `when` by counting characters, and it works
    # out which group of rows is today by comparing that group's date with the daemon's, which
    # is only safe while the daemon sends one shape and hands the days over in order. So both
    # are pinned here, at the end the card reads from.
    _, st = call(web.port, "/api/state")
    assert st["upcoming"], "there is nothing here to check the shape of"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", st["days"][0]["date"]), st["days"][0]["date"]
    dates = [e["date"] for e in st["upcoming"]]
    assert dates == sorted(dates), "the card walks the days in order, so an arrow is one day"
    for e in st["upcoming"]:
        assert re.fullmatch(r"\w{3} \d{2} \w{3} \d{2}:\d{2}", e["when"]), \
            f"the card reads the clock off the end of {e['when']!r}, so the shape has to hold"
        assert e["when"][-6] == " " and e["when"][4:6] == e["date"][8:10], \
            f"{e['when']!r} and the date it is filed under, {e['date']}, do not agree"


def test_no_table_the_page_draws_is_left_to_size_itself(panel):
    """Every card that draws a table got told its columns, one at a time, each after a button
    fell outside the border of the card it was drawn in. This check covers the lot at once,
    because the page keeps building new rows out of words it did not choose: a file name, a
    name typed into a speaker, an address with no space in it, a place name off somebody
    else's map, the list of clips a call will play. A table that sizes itself to those words
    leans the far side of the row - nearly always the buttons - over the card. Not one table is
    left unsized now: the days used to draw their own, out of a prayer's name and the minute it
    falls at, and that card is gone - the Events card is the timetable, told column by column
    like everything else on the page."""
    web, _, _ = panel
    _, html = call(web.port, "/", raw=True)
    assert '<table id="hitstbl">' in html, \
        "the list of places that answered a search builds a table with no name to be told"
    for table, columns in (("#uptbl", 4), ("#outputstbl", 6), ("#soundtbl", 4),
                           ("#libtbl", 4), ("#foundtbl", 5)):
        assert f"{table} {{ table-layout:fixed }}" in html, \
            f"{table} still sizes itself to its words"
        widths, phone = column_widths(html, table)
        assert len(widths) == columns, f"{table} tells {len(widths)} widths for {columns} columns"
        assert sum(widths) == 100, f"the columns of {table} add up to {sum(widths)}%"
        assert len(phone) == columns, f"{table} is not retold for a phone"
        assert sum(phone) == 100, f"the phone's columns of {table} add up to {sum(phone)}%"
        assert f"{table} td {{ overflow-wrap:break-word }}" in html, \
            f"a long word in {table} breaks at the edge of its own cell"
    # The answers of a search have no header row, so their cells are what gets told.
    widths, phone = column_widths(html, "#hitstbl", "td")
    assert len(widths) == 4 and sum(widths) == 100, f"an answer row tells {widths}"
    assert len(phone) == 4 and sum(phone) == 100, f"a phone's answer row tells {phone}"
    assert "#hitstbl { table-layout:fixed }" in html and "#hitstbl td { overflow-wrap:break-word }" in html
    assert "<table>" not in html, \
        "every table on the page now carries a name to be told its columns; the one that " \
        "sized itself belonged to the day blocks, and they are gone"
    assert "#soundtbl select { width:100% }" in html, \
        "a select fills the column it was given instead of asking the table for the width of " \
        "the longest name it offers"
    assert "#foundtbl td > button, #hitstbl td > button" in html, \
        "the buttons of a row stand one under the other and fill their column, so a control " \
        "that cannot break a word to fit never grows past the card"


def test_the_hijri_knob_moves_the_date_the_page_shows(panel):
    web, _, tmp_path = panel
    status, reply = call(web.port, "/api/hijri", {"days": -1})
    assert status == 200, reply
    assert reply["today"]["hijri"], "the new date comes back, not just a stored number"
    _, st = call(web.port, "/api/state")
    assert st["hijri_offset"] == -1
    assert "hijri_offset: -1" in (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    status, reply = call(web.port, "/api/hijri", {"days": 9})
    assert status == 400 and "-3" in reply["error"]


def test_a_read_only_panel_cannot_press_any_of_the_new_buttons(tmp_path):
    profile, _ = profile_for(tmp_path)
    runner = Runner(profile)
    web = WebPanel(runner, port=0, allow_edit=False)
    web.start()
    try:
        for path, body in (("/api/method", {"preset": "qom"}),
                           ("/api/audio", {"at": "fajr", "media": ["dua.mp3"]}),
                           ("/api/speaker/add", {"target": "Study speaker"}),
                           ("/api/output/remove", {"name": "outbox"}),
                           ("/api/hijri", {"days": 1})):
            status, reply = call(web.port, path, body)
            assert status == 403, (path, reply)
        assert post_raw(web.port, "/api/media/upload?name=x.mp3", b"ID3\x03fake")[0] == 403
        assert not (tmp_path / "media" / "x.mp3").exists()
    finally:
        web.stop()
        runner.shutdown()


def test_the_page_offers_exactly_the_recordings_the_daemon_accepts(panel):
    """One answer to "what counts as a recording", which three places need it.

    That list of suffixes decides which files in the folder are the library, which
    names an event is allowed to carry and which upload the daemon will take. The
    page needs it too, as the `accept` list of its file picker, and the web module
    used to carry its own copy of it - which is how the two could come to disagree,
    a file you can see in the library turning into one the page refuses to add, or
    the other way round, with nothing in between to notice. So the copy is gone and
    this is what keeps it gone; and because the page's copy is HTML text rather than
    the set itself, it is compared by what it lists rather than by identity.
    """
    web, _, _ = panel
    assert WEB_AUDIO_SUFFIXES is AUDIO_SUFFIXES, "the web module grew its own copy again"
    _, html = call(web.port, "/", raw=True)
    accept = re.search(r'<input type="file" id="file" accept="([^"]*)"', html).group(1)
    offered = {part.strip() for part in accept.split(",") if part.startswith(".")}
    assert offered == set(AUDIO_SUFFIXES), (
        f"the file picker and the daemon disagree about "
        f"{sorted(offered ^ set(AUDIO_SUFFIXES))}")


# ---- who the page answers to, and in what order it says no ------------------
#
# There is no password on this port, so the two things standing between a stranger
# on the wifi and the schedule your Fajr goes out on are: which name in the Host
# header the page will work under, and what it refuses to read off the socket.


def raw_status(port, request: bytes) -> str:
    """Send bytes no browser would send, and get the status line back."""
    import socket

    with socket.create_connection(("127.0.0.1", port), timeout=15) as sock:
        sock.sendall(request)
        reply = b""
        while len(reply) < 4096:
            chunk = sock.recv(512)
            if not chunk:
                break
            reply += chunk
            if b"\r\n\r\n" in reply:
                break
    return (reply.decode("latin-1").split("\r\n", 1)[0]
            if reply else "the page hung up without answering")


def test_the_page_works_under_its_own_names_and_no_others(panel):
    """A page that only checked the IP would answer a browser that was told - by
    somebody else's DNS - that evil.example is your LAN address, and would hand
    that page your schedule and your speakers. The Host header says which box the
    browser believes it is talking to, which is the only way to see that trick."""
    web, _, _ = panel
    assert call(web.port, "/api/state")[0] == 200
    for imposter in ("evil.example", "evil.example:8020", "192.168.0.5", ""):
        status, reply = call(web.port, "/api/state", headers={"Host": imposter})
        assert status == 403, (imposter, reply)
        assert "its own address" in reply["error"]


def test_a_name_you_named_when_starting_the_daemon_is_believed(tmp_path):
    """`muezzin daemon --allow-host azan.local` is how a household that serves the
    page under a name - or through a reverse proxy - keeps working."""
    profile, _ = profile_for(tmp_path)
    runner = Runner(profile)
    web = WebPanel(runner, port=0, allow_hosts=("azan.local",))
    web.start()
    try:
        assert call(web.port, "/api/state", headers={"Host": "azan.local:8020"})[0] == 200
        assert call(web.port, "/api/state", headers={"Host": "azan.local"})[0] == 200
    finally:
        web.stop()
        runner.shutdown()


def test_a_write_from_a_name_the_page_does_not_answer_to_is_refused_before_the_body_is_read(panel):
    """The order is the point: a request that is refused must be refused without
    the page first holding a 400 KB body in memory or acting on what is in it."""
    web, _, tmp_path = panel
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    status, reply = call(web.port, "/api/method", {"preset": "qom"},
                         headers={"Host": "evil.example"})
    assert status == 403 and "its own address" in reply["error"]
    assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before
    _, st = call(web.port, "/api/state")
    assert "preset: isna" in st["config_text"], "nothing was changed by the refused write"


def test_a_refused_write_still_arrives_as_a_reason(panel):
    """Refused is not the same as hung up on. A body that this side has no intention
    of using is still read off the socket and thrown away - never interpreted, never
    kept - because a socket closed in front of a client that is still sending
    reaches the browser as "network error" instead of the reason it was refused."""
    web, _, _ = panel
    import socket
    # bigger than any socket buffer, so the client is genuinely still sending when
    # the answer goes out; a small body fits and the race is invisible
    body = b"-" * (4 * 1024 * 1024)
    for headers, reason in (
            (b"Host: evil.example\r\n", b"its own address"),
            # the Host has to be a real one here, or the name check answers first and
            # the origin check is never reached
            (f"Host: 127.0.0.1:{web.port}\r\nOrigin: http://evil.example\r\n".encode(),
             b"its own origin")):
        with socket.create_connection(("127.0.0.1", web.port), timeout=15) as sock:
            sock.sendall(b"POST /api/config HTTP/1.1\r\n" + headers +
                         b"Content-Type: application/json\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\n\r\n")
            sock.sendall(body)
            reply = b""
            while len(reply) < 4096:
                chunk = sock.recv(512)
                if not chunk:
                    break
                reply += chunk
                if reason in reply:
                    break
        first = reply.split(b"\r\n", 1)[0]
        assert b"403" in first, first
        assert reason in reply, "the reason the write was refused, not a reset"


def test_a_chunked_body_is_answered_and_not_reassembled(panel):
    """The page speaks HTTP/1.0 with a length, and a chunked body read as though
    it were not chunked ends the request early and leaves the rest of it to be
    parsed as a second one. So chunked gets a 501, on purpose."""
    web, _, _ = panel
    line = raw_status(web.port, b"POST /api/method HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                                b"Content-Type: application/json\r\nTransfer-Encoding: chunked"
                                b"\r\n\r\n2\r\n{}\r\n0\r\n\r\n")
    assert "501" in line, line


def test_a_content_length_that_is_not_a_number_is_refused(panel):
    web, _, _ = panel
    line = raw_status(web.port, b"POST /api/method HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                                b"Content-Type: application/json\r\nContent-Length: -5"
                                b"\r\n\r\n")
    assert "400" in line, line
    assert call(web.port, "/api/state")[0] == 200, "and the page carries on afterwards"


def test_a_read_only_panel_throws_a_body_away_instead_of_acting_on_it(tmp_path):
    """Read-only has to be decided before the page starts looking at the body, and
    the body still has to be read: leaving it on the connection means the next
    request on it, which a browser sends without waiting, starts in the middle of
    the last one's file."""
    profile, _ = profile_for(tmp_path)
    runner = Runner(profile)
    web = WebPanel(runner, port=0, allow_edit=False)
    web.start()
    try:
        before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
        body = json.dumps({"text": "x" * 100000}).encode("utf-8")
        line = raw_status(
            web.port,
            b"POST /api/config HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json"
            + b"\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        assert "403" in line, line
        assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before
        assert call(web.port, "/api/state")[0] == 200, "still serving after the refused write"
    finally:
        web.stop()
        runner.shutdown()


def test_yaml_that_multiplies_itself_is_refused_before_it_is_parsed(panel):
    """PyYAML expands an alias into a copy with no limit, so a two kilobyte
    document of nested anchors is enough to reach a Pi's memory ceiling before the
    loader can object to anything. The page refuses the shape, and says what to do
    instead, rather than discovering the size too late."""
    web, _, tmp_path = panel
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    bomb = "l0: &l0 [" + ",".join(["x"] * 20) + "]\n"
    bomb += "".join("l%d: &l%d [" % (i, i) + ",".join(["*l%d" % (i - 1)] * 10) + "]\n"
                    for i in range(1, 8))
    status, reply = call(web.port, "/api/config", {"text": bomb})
    assert status == 400 and "alias" in reply["error"], reply
    assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before

    # an asterisk that is only an asterisk must not cost you the save button
    prose = before.replace("media_dir:", "# *this* and &that are only notes\nmedia_dir:")
    assert call(web.port, "/api/config", {"text": prose})[0] == 200


def test_two_editors_and_a_button_never_write_the_file_at_the_same_time(panel):
    """A save from the text box and a press of the method button are each a read,
    an edit and a write of one file. Read-modify-write without one lock across all
    three is how the second writer wins and the first person's change vanishes."""
    web, _, tmp_path = panel
    path = tmp_path / "muezzin.yaml"
    web.lock.acquire()          # as if a save were halfway through
    done = threading.Event()
    threading.Thread(target=lambda: (web.set_method({"preset": "qom"}), done.set()),
                     daemon=True).start()
    assert not done.wait(0.4), "the button wrote the file while another edit held it"
    web.lock.release()
    assert done.wait(10), "and it went ahead as soon as the file was free"
    assert "preset: qom" in path.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.webtmp"))


def test_the_position_the_page_hands_back_is_the_position_on_disk(panel):
    """This used to round the position to two decimals on its way to the browser, on the
    reasoning that an open page on the wifi should not print the house's exact address.
    That reasoning did not survive the reply it was written into, which carries the whole
    profile - exact address included - and it broke something else: the Where boxes are
    filled from these two numbers, so pressing write-it without touching anything moved
    the house by up to a kilometre. Shortening is the header line's job, where a person is
    reading a label rather than editing a value."""
    web, _, _ = panel
    _, st = call(web.port, "/api/state")
    assert st["location"]["latitude"] == 40.7128
    assert st["location"]["longitude"] == -74.006
    assert "40.7128" in st["config_text"], "the profile the daemon runs on is untouched"
    _, page = call(web.port, "/", raw=True)
    assert "location.latitude.toFixed(2)" in page, "the header lost its own shortening"


def test_pressing_write_it_without_touching_the_boxes_moves_nothing(panel, tmp_path):
    """The likeliest way a household finishes setting its position is to press the button
    and leave the two boxes as they came. So whatever the page was handed has to be what
    it hands back: a reply that had shortened the numbers on the way out would write the
    house a kilometre from where it is, with nothing said about it, and every time in the
    profile would follow the new spot. Read back through the loader rather than by eye,
    because a location may be written as a block or on one line and both have to survive.
    """
    def place(path):
        loc = load_profile(path).location
        return (loc.latitude, loc.longitude, loc.timezone)

    web, _, _ = panel
    _, st = call(web.port, "/api/state")
    path = tmp_path / "muezzin.yaml"
    before = place(path)
    status, _ = call(web.port, "/api/location", {
        "latitude": st["location"]["latitude"],
        "longitude": st["location"]["longitude"],
        "timezone": st["location"]["timezone"]})
    assert status == 200, status
    after = place(path)
    assert after == before, f"write-it moved the house: {before} -> {after}"


def test_a_scan_that_is_still_going_on_says_so_instead_of_making_you_wait(panel, monkeypatch):
    """A scan is ten seconds of mDNS and some HTTPS. The page polls, so a second
    poll while one is under way must not queue a second broadcast on the network
    nor leave the browser staring at a request that is doing nothing."""
    from muezzin import web as web_module

    web, _, _ = panel
    started, gate = threading.Event(), threading.Event()

    def slow_scan(timeout=5.0, ask_members=True):
        started.set()
        gate.wait(8)
        return {"speakers": [], "groups": [], "boxes": [], "asked": 0, "silent": []}

    monkeypatch.setattr(web_module, "scan_speakers", slow_scan)
    first = threading.Thread(target=lambda: call(web.port, "/api/speakers?refresh=1"), daemon=True)
    first.start()
    assert started.wait(3), "the first refresh did not start a scan"
    started_at = time.time()
    status, reply = call(web.port, "/api/speakers?refresh=1")
    spent = time.time() - started_at
    gate.set()
    first.join(10)
    assert status == 200, reply
    assert reply.get("scanning") is True, "the page needs to know to ask again shortly"
    assert spent < 1.0, "the second poll waited for the first instead of answering from the cache"


def test_a_box_is_not_added_on_an_address_or_port_that_makes_no_sense(panel):
    """`kind: lan_box` writes a host into the file, so the same rules that guard a
    hand-typed profile guard the button: a hostname with a path in it is not a
    host, and a port is not a suggestion."""
    web, _, tmp_path = panel
    before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    for bad in ({"name": "porch", "host": "http://192.168.0.25", "port": 8090},
                {"name": "porch", "host": "192.168.0.25", "port": "not a port"},
                {"name": "porch", "host": "192.168.0.25", "port": 0},
                {"name": "porch", "host": "192.168.0.25", "port": 70000},
                {"name": "porch", "host": "192.168.0.25 /api", "port": 8090}):
        status, reply = call(web.port, "/api/box/add", bad)
        assert status == 400, (bad, reply)
    assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before
    status, reply = call(web.port, "/api/box/add", {"name": "porch", "host": "192.168.0.25",
                                                    "port": 8090})
    assert status == 200, reply
    on_disk = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
    assert "porch" in on_disk and re.search(r"host:\s*'?\"?192\.168\.0\.25", on_disk)


def test_the_page_works_on_a_profile_that_has_no_speakers_yet(tmp_path):
    """`muezzin init` hands over an outputs list with nothing in it, and the page
    is the first thing a new install points a browser at. So the timetable has to
    render over an empty list, and "use" has to be able to write the first entry
    onto a list that has no entries in it - the most common edit this program
    will ever be asked for, and the one every starter profile sits on.
    """
    profile, _ = profile_for(tmp_path, STARTER.replace("http_port: 8010", "http_port: 0"))
    runner = Runner(profile)
    web = WebPanel(runner, port=0)
    web.start()
    try:
        status, state = call(web.port, "/api/state")
        assert status == 200, state
        assert state["outputs"] == [], "the page shows an empty list, not a crash"
        assert len(state["events"]) == 5, "the five adhans are there before any speaker is"
        assert all(not e["targets"] for e in state["upcoming"]), \
            "an untargeted event with no outputs resolves to nothing, quietly"
        # a brand new install reads this page, not the daemon's log
        assert any("No speakers" in n for n in state["notices"]), state["notices"]
        assert any("New York" in n for n in state["notices"]), state["notices"]
        status, page = call(web.port, "/", raw=True)
        assert status == 200 and page.startswith("<!doctype html")
        assert 'id="notices"' in page, "the page has somewhere to put those words"
        assert '.notice' in page, "and a style that makes them look like a warning"
        status, reply = call(web.port, "/api/speaker/add", {"target": "Landing group"})
        assert status == 200, reply
        assert reply["output"] == "landing-group"
        added = load_profile(tmp_path / "muezzin.yaml")
        assert [o.name for o in added.outputs] == ["landing-group"]
        assert added.targets_for(added.events[0]) == added.outputs, \
            "the adhans reach the speaker the moment it exists"
        _, state = call(web.port, "/api/state")
        assert not any("No speakers" in n for n in state["notices"]), \
            "the warning goes away once the thing it warned about is fixed"
    finally:
        web.stop()
        runner.shutdown()


def test_a_profile_that_chose_its_own_city_is_not_lectured(tmp_path):
    """The band has to earn its space on the page: a household with a speaker of its
    own and coordinates it typed should see nothing where it would have been, or the
    page nags about what is fine and stops being read. The profile moves city because
    the placeholder check is about those three exact values, not about New York."""
    text = (BASE.replace("latitude: 40.7128, longitude: -74.006",
                         "latitude: 33.5131, longitude: -111.9051")
                .replace("timezone: America/New_York", "timezone: America/Phoenix"))
    profile, _ = profile_for(tmp_path, text)
    runner = Runner(profile)
    web = WebPanel(runner, port=0)
    web.start()
    try:
        _, state = call(web.port, "/api/state")
        assert state["outputs"], "the fixture needs a speaker for this to mean anything"
        assert state["notices"] == [], state["notices"]
    finally:
        web.stop()
        runner.shutdown()


def test_switching_every_speaker_off_says_so_on_the_page(panel):
    """Whether an output is on lives in the running daemon and never appears in the
    file, so a house that has gone quiet by switching things off would otherwise be
    silent with no trace of why. This is the one kind of quiet worth announcing."""
    web, _, _ = panel
    _, state = call(web.port, "/api/state")
    for name in [o["name"] for o in state["outputs"]]:
        status, reply = call(web.port, "/api/output", {"name": name, "enabled": False})
        assert status == 200, reply
    _, state = call(web.port, "/api/state")
    assert any("switched off" in n for n in state["notices"]), state["notices"]
    assert not any("No speakers" in n for n in state["notices"]), \
        "configured but off is a different problem from having nothing at all"


# Three questions about a place, and they are not three versions of one question:
# whether a pair of numbers is sane is arithmetic this machine can do for itself; what
# a place is called is a single request to somebody else, made only because someone
# pressed a button; and making those numbers the profile's location is a write. The
# tests keep them apart because the promises are different. The first two work with the
# cable unplugged and on a locked panel; the third touches the file, and only once the
# clock name it was given is one this machine actually has.

LOCATED = BASE.replace(
    "location: {latitude: 40.7128, longitude: -74.006, timezone: America/New_York}\n",
    "location:\n"
    "  latitude: 40.7128            # your latitude, north positive\n"
    "  longitude: -74.006           # your longitude, east positive\n"
    "  timezone: America/New_York   # IANA name: DST is handled by the tz database\n")

MAPPED = BASE.replace("media_dir: media\n", "media_dir: media\nmap_tiles: osm\n")
# The map is on now without anyone being asked to turn it on, so what a test has to
# reach for is the line that puts it back: a household that wants nothing leaving the
# house writes this, and everything except the pictures keeps working.
UNMAPPED = BASE.replace("media_dir: media\n", "media_dir: media\nmap_tiles: off\n")

# Two answers shaped like the lookup's own rows: one carries a time zone in its extra
# tags, the other does not. Qom rather than anyone's home address, because a fixture
# that repeats a real household is the sort of thing that gets published by accident.
WHERE_ANSWER = json.dumps([
    {"place_id": 1, "lat": "34.6416", "lon": "50.8851", "display_name": "Qom, Iran",
     "extratags": {"timezone": "Asia/Tehran"}},
    {"place_id": 2, "lat": "34.65", "lon": "50.87", "display_name": "Qom Province, Iran"},
]).encode("utf-8")

# A row in the open Atlantic with nothing to borrow a clock from, which is the case
# that has to say "I do not know" rather than guess at the nearest thing.
SOLO_ANSWER = json.dumps([
    {"place_id": 3, "lat": "-30.5", "lon": "-21.5",
     "display_name": "Mid-Atlantic, somewhere"},
]).encode("utf-8")

# A square of the map, as bytes. The PNG header is spelled out as numbers so that nothing
# here depends on how an escape sequence happens to be read.
PNG = (bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
       + b"a square of somebody's map")


def test_checking_a_set_of_numbers_asks_nobody_anything(panel, monkeypatch):
    """The most common reason to look at coordinates is that they are wrong, and the
    person who typed them should find that out without a stranger being involved. This
    is arithmetic against the table the program carries, so it also works at 3 a.m. with
    the internet down, which is roughly when a mis-set location gets noticed."""
    def nobody_should_be_asked(*args, **kwargs):
        raise AssertionError("checking numbers must not touch the network")

    monkeypatch.setattr(geocode, "_open", nobody_should_be_asked)
    web, _, _ = panel
    status, st = call(web.port, "/api/near?lat=42.1292&lon=-80.0851")
    assert status == 200, st
    assert st["near"][0]["name"] == "Erie, Pennsylvania", st["near"]
    assert st["near"][0]["km"] < 5.0
    assert 0.0 <= st["near"][0]["bearing"] < 360.0
    assert st["timezone"] == "America/New_York", st["zone_note"]
    assert "far_note" not in st, "nothing is wrong with these numbers"


def test_numbers_a_long_way_from_any_familiar_name_are_called_out(panel):
    """A lat/long copied from the wrong row of a spreadsheet is not a place, and the
    page should say so in the plainest possible words rather than compute a beautiful
    set of times for the South Atlantic. Refusing to lend a clock is part of it: a zone
    four thousand kilometres away is a wrong answer, not a near miss."""
    web, _, _ = panel
    status, st = call(web.port, "/api/near?lat=-30.0&lon=-20.0")
    assert status == 200, st
    assert st["near"][0]["km"] > geocode.FAR_KM
    assert "transposed" in st["far_note"], st["far_note"]
    assert "timezone" not in st, st
    assert "near enough" in st["zone_note"], st["zone_note"]


def test_a_number_that_cannot_be_a_place_comes_back_with_a_reason(panel):
    """91 degrees north does not exist, and silently arithmetic-ing on it would produce
    times for somewhere the person has never been."""
    web, _, _ = panel
    status, st = call(web.port, "/api/near?lat=91&lon=-80.0851")
    assert status == 400 and "-90 to 90" in st["error"], st
    for query in ("lat=&lon=", "lat=42.1&lon=banana", "lat=42.1"):
        status, st = call(web.port, f"/api/near?{query}")
        assert status == 400 and "latitude" in st["error"], (query, st)


def test_finding_a_place_sends_the_words_once_and_names_who_was_asked(tmp_path,
                                                                      monkeypatch):
    """The one request in this program that leaves the network, so the test pins down
    all four of the promises at once: one press is one request, no key is involved, the
    answering machine is named on the page, and nothing at all is written down."""
    asks = []

    def answer(url, accept="application/json"):
        asks.append(url)
        return WHERE_ANSWER

    monkeypatch.setattr(geocode, "_open", answer)
    web, out, _ = _serve(tmp_path)
    try:
        _, before = call(web.port, "/api/state")
        status, st = call(web.port, "/api/geocode", {"q": "Qom, Iran"})
        assert status == 200, st
        assert len(asks) == 1, asks
        assert "nominatim.openstreetmap.org" in asks[0], asks
        assert "key=" not in asks[0], "a lookup that needs a key is one users cannot run"
        assert "Qom" in asks[0]
        assert st["provider"] == "nominatim.openstreetmap.org"
        assert st["credit"] == geocode.MAP_CREDIT
        assert st["hits"][0]["latitude"] == 34.6416
        _, after = call(web.port, "/api/state")
        assert after["config_text"] == before["config_text"], \
            "looking a place up writes nothing to the profile"
    finally:
        web.stop()
        web.runner.shutdown()


def test_a_hit_with_no_zone_of_its_own_says_where_its_clock_came_from(tmp_path,
                                                                      monkeypatch):
    """Neither the lookup nor a map tells you which clock a place keeps. Borrowing the
    zone of a city next door is usually right and is nearly always what people want, but
    it has to be labelled as a borrow, because a household near a border - Nijmegen,
    Erie, Baarle - is exactly where the guess is wrong."""
    monkeypatch.setattr(geocode, "_open", lambda url, accept="application/json":
                        WHERE_ANSWER)
    web, _, _ = _serve(tmp_path)
    try:
        _, st = call(web.port, "/api/geocode", {"q": "Qom"})
        assert st["hits"][1]["timezone"] == "Asia/Tehran"
        assert "borrowed" in st["hits"][1]["note"], st["hits"][1]
        assert "named this zone" in st["hits"][0]["note"], st["hits"][0]
    finally:
        web.runner.shutdown()


def test_a_place_with_no_clock_to_borrow_admits_it(tmp_path, monkeypatch):
    monkeypatch.setattr(geocode, "_open", lambda url, accept="application/json":
                        SOLO_ANSWER)
    web, _, _ = _serve(tmp_path)
    try:
        _, st = call(web.port, "/api/geocode", {"latitude": -30.5, "longitude": -21.5})
        assert st["hits"][0]["timezone"] is None, st
        assert "no time zone" in st["hits"][0]["note"], st["hits"][0]["note"]
    finally:
        web.runner.shutdown()


def test_a_find_that_was_given_neither_words_nor_numbers_is_refused(panel):
    web, _, _ = panel
    status, st = call(web.port, "/api/geocode", {})
    assert status == 400 and "type a street or a postal code" in st["error"], st


def test_the_postal_code_arrives_with_the_words_and_costs_nothing_extra(panel, monkeypatch):
    """The second box exists because the first one, on its own, is the question that most
    often answers with several streets and none of them the door asked for. Measured on the
    public lookup: the words plus a code, with no town named, answered with one row carrying
    the house number; the same words naming a town answered with five stretches of street.
    The code joins that one request rather than starting another, and it is still the only
    thing that leaves the house."""
    asks: list[str] = []

    def listening(url: str, accept: str = "application/json") -> bytes:
        asks.append(url)
        return b"[]"

    monkeypatch.setattr(geocode, "_open", listening)
    web, _, _ = panel
    status, st = call(web.port, "/api/geocode", {"q": "2456 w 12th st",
                                                 "postcode": "16508"})
    assert status == 200 and st["hits"] == [], st
    assert len(asks) == 1, "a code is not a second question"
    assert "q=2456+w+12th+st%2C+16508" in asks[0]
    status, st = call(web.port, "/api/geocode", {"postcode": "16508"})
    assert status == 200, st
    assert "q=16508" in asks[-1], "a code on its own is a coarse but honest question"
    assert len(asks) == 2, "one ask per press of the button, and no more"


def test_a_read_only_panel_can_still_ask_what_its_numbers_mean(tmp_path, monkeypatch):
    """--read-only is about not changing the household's settings, not about being blind.
    A lookup changes nothing here, so a locked panel keeps it; writing the location is
    still refused, which is the half of the section that actually edits the file."""
    monkeypatch.setattr(geocode, "_open", lambda url, accept="application/json":
                        WHERE_ANSWER)
    profile, _ = profile_for(tmp_path)
    runner = Runner(profile)
    web = WebPanel(runner, port=0, allow_edit=False)
    web.start()
    try:
        status, st = call(web.port, "/api/near?lat=42.1292&lon=-80.0851")
        assert status == 200, st
        status, st = call(web.port, "/api/geocode", {"q": "Qom, Iran"})
        assert status == 200 and st["hits"], st
        status, st = call(web.port, "/api/location", {"latitude": 42.1292,
                                                      "longitude": -80.0851,
                                                      "timezone": "America/New_York"})
        assert status == 403 and "read-only" in st["error"], st
    finally:
        web.stop()
        runner.shutdown()


def test_writing_a_location_keeps_the_comments_and_the_shape_of_the_file(tmp_path):
    """The location block is the one part of a starter profile every new household has
    to change, so how that write looks afterwards is what the file is judged by. The
    notes beside the three lines are the explanation of what each one does, and the
    comment column is what makes them readable: a write that left them ragged would look
    like something had been vandalised."""
    web, _, _ = _serve(tmp_path, LOCATED)
    try:
        status, st = call(web.port, "/api/location", {"latitude": 34.6416,
                                                      "longitude": 50.8851,
                                                      "timezone": "Asia/Tehran"})
        assert status == 200, st
        assert st["location"] == {"latitude": 34.6416, "longitude": 50.8851,
                                 "timezone": "Asia/Tehran"}, st
        text = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
        assert "latitude: 34.6416" in text and "timezone: Asia/Tehran" in text
        assert text.count("#") == LOCATED.count("#"), "a comment was lost"
        columns = {line.index("#") for line in text.splitlines()
                   if line.strip().startswith(("latitude:", "longitude:", "timezone:"))}
        assert len(columns) == 1, f"the notes came back ragged: {columns}"
        assert not any("placeholder" in n for n in st["notices"]), st["notices"]
    finally:
        web.runner.shutdown()


def test_a_block_written_as_one_line_stays_a_block_written_as_one_line(tmp_path):
    """Somebody who wrote their location on one line should not come back to find the
    daemon reformatted it: the file is theirs to read, and a diff that moves lines is a
    diff that hides the one line that changed."""
    web, _, _ = _serve(tmp_path)
    try:
        status, st = call(web.port, "/api/location", {"latitude": 34.6416,
                                                      "longitude": 50.8851,
                                                      "timezone": "Asia/Tehran"})
        assert status == 200, st
        lines = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8").splitlines()
        assert any(line.startswith("location: {") for line in lines), lines
    finally:
        web.runner.shutdown()


def test_a_zone_this_machine_has_no_clock_for_is_refused_before_the_file_moves(tmp_path):
    """A time zone name the tz database does not have is not a slightly wrong guess but
    a profile that will not load, and the worst moment to discover that is the next
    restart - which in a house that only hears the adhan twice a day might be weeks
    away. So it is refused here, in words, while the file is still what it was."""
    web, _, _ = _serve(tmp_path, LOCATED)
    try:
        before = (tmp_path / "muezzin.yaml").read_text(encoding="utf-8")
        status, st = call(web.port, "/api/location", {"latitude": 34.6416,
                                                      "longitude": 50.8851,
                                                      "timezone": "Mars/Phobos"})
        assert status == 400 and "would not load" in st["error"], st
        assert (tmp_path / "muezzin.yaml").read_text(encoding="utf-8") == before
        for zone in ("", "   "):
            status, st = call(web.port, "/api/location", {"latitude": 34.6416,
                                                          "longitude": 50.8851,
                                                          "timezone": zone})
            assert status == 400 and "time zone" in st["error"], (zone, st)
    finally:
        web.runner.shutdown()


def test_the_page_is_told_who_it_may_ask_and_whose_map_it_shows(panel):
    """The page has to name the machine that will receive the typed words before the
    button is pressed, rather than after; and if a map appears, whose map it is belongs
    on the page as much as in a document."""
    web, _, _ = panel
    _, st = call(web.port, "/api/state")
    assert st["geocoder"] == geocode.provider() == "nominatim.openstreetmap.org"
    assert st["map_tiles"] == "osm", "the map is the default, not a thing to discover"
    assert st["map_credit"] == geocode.MAP_CREDIT
    _, page = call(web.port, "/", raw=True)
    assert "map_tiles: off" in page, "the page does not say how to stop the map"
    assert "tile.openstreetmap.org" in page, "the page does not say who the map comes from"
    assert "Where" in page


def test_the_page_never_asks_anyone_to_hold_a_key(panel):
    """Every lookup that needs a key is a lookup a user cannot run: they would have to
    register a card with a vendor to set where they live. The page is where that promise
    is kept, so the guard lives with the page."""
    web, _, _ = panel
    _, page = call(web.port, "/", raw=True)
    lowered = page.lower()
    for forbidden in ("api key", "apikey", "key=", "iaza"):
        assert forbidden not in lowered, forbidden


def test_the_map_is_there_without_anyone_having_to_dig_for_it(panel, monkeypatch):
    """Where the numbers point is the first thing a household needs to get right, and a
    helper that only appears once someone has found the right line to write in a file is
    a helper most people never meet. So the squares come by default, fetched here and
    kept here, with the stopping place written next to them on the page."""
    asks = []
    monkeypatch.setattr(geocode, "_open",
                        lambda url, accept="application/json": asks.append((url, accept)) or PNG)
    web, _, _ = panel
    status, body, ctype = get_bytes(web.port, "/api/tile?z=12&x=1&y=1")
    assert status == 200 and ctype == "image/png", (status, body[:60], ctype)
    assert asks == [(geocode.tile_url(12, 1, 1), "image/png")], asks
    _, page = call(web.port, "/", raw=True)
    assert "click it to point" in page, "nothing on the page says the map can be pointed at"


def test_one_line_keeps_every_request_inside_the_house(tmp_path, monkeypatch):
    """The map is the default, and the way out of it has to be one honest line rather
    than an archaeology dig: with it, the position is still drawn, from the numbers alone,
    and this daemon asks nobody for a picture."""
    asks = []
    monkeypatch.setattr(geocode, "_open",
                        lambda url, accept="application/json": asks.append((url, accept)) or PNG)
    web, _, _ = _serve(tmp_path, UNMAPPED)
    try:
        status, body, _ = get_bytes(web.port, "/api/tile?z=12&x=1&y=1")
        assert status == 403 and b"map_tiles: off" in body, (status, body)
        assert asks == [], "a profile that said off still went out for a picture"
    finally:
        web.runner.shutdown()


def test_a_map_square_is_brought_once_and_then_kept_for_the_house(tmp_path, monkeypatch):
    """The daemon fetches the square rather than letting nine browser screens do it, and
    keeps it: the same nine squares should not be asked for again every time somebody
    opens the page, and the picture has to arrive as bytes with a picture's header, not
    as a base64 string inside JSON."""
    asks = []

    def answer(url, accept="application/json"):
        asks.append((url, accept))
        return PNG

    monkeypatch.setattr(geocode, "_open", answer)
    web, _, _ = _serve(tmp_path, MAPPED)
    try:
        status, body, ctype = get_bytes(web.port, "/api/tile?z=12&x=1&y=1")
        assert status == 200 and body == PNG, (status, body[:40])
        assert ctype == "image/png", ctype
        assert asks == [(geocode.tile_url(12, 1, 1), "image/png")], asks
        assert len(list((tmp_path / "muezzin-tiles").rglob("*.png"))) == 1
        status, body, _ = get_bytes(web.port, "/api/tile?z=12&x=1&y=1")
        assert status == 200 and body == PNG
        assert len(asks) == 1, "the second request should have come off the disk"
    finally:
        web.runner.shutdown()


def test_a_pixel_of_the_map_turns_back_into_the_numbers_it_came_from(panel):
    """Clicking the map is the page turning one of its own squares back into degrees, in
    JavaScript, which no test in this file can run. So the same arithmetic is written here
    once, in Python, and the page is checked to carry the two halves of it it depends on.
    A factor of two lost from the vertical formula - the usual mistake, since the tan
    half-angle and the sinh form differ only by that factor - puts every household's mark
    on the wrong patch of ground, and nothing else here would notice."""

    def forward(lat, lon, z):
        n = 2.0 ** z
        return (n * (lon + 180) / 360,
                n * (1 - math.log(math.tan(math.pi / 4 + lat * math.pi / 360)) / math.pi) / 2)

    def back(u, v, z):
        n = 2.0 ** z
        return ((360 / math.pi) * math.atan(math.exp(math.pi * (1 - 2 * v / n))) - 90,
                u * 360 / n - 180)

    for lat, lon, z in ((42.1295, -80.0853, 12), (51.5072, -0.1276, 15),
                        (-33.8688, 151.2093, 9), (35.6895, 139.6917, 17)):
        x, y = forward(lat, lon, z)
        la, lo = back(x, y, z)
        assert abs(la - lat) < 1e-9 and abs(lo - lon) < 1e-9, (lat, lon, la, lo)
        # a click in the middle of the square the point is in reads back as that point,
        # loosely: one square of the map is the tolerance here, and how wide that is
        # depends on the zoom rather than on a number picked for one case.
        wide = 360.0 / 2.0 ** z
        la, lo = back(math.floor(x) + 0.5, math.floor(y) + 0.5, z)
        assert abs(la - lat) < wide and abs(lo - lon) < wide, (lat, lon, z, la, lo)

    _, page = call(panel[0].port, "/", raw=True)
    assert "Math.log(Math.tan(Math.PI/4" in page, "the page lost the forward formula"
    assert "Math.atan(Math.exp(" in page, "the page lost the way back from a pixel"
    # the click divides the width the box was really drawn at by the number of squares
    # across it, so the mark's position and a click's are the same arithmetic in opposite
    # directions, and neither depends on a square happening to be 256 px on this screen.
    assert "MG/r.width" in page and "MG/r.height" in page


def test_the_shape_of_a_map_view_comes_from_one_number(panel):
    """A view is MG squares across and MG down, and three parts of the page have to agree
    about that number: the grid the browser is told to draw, where the mark is put on it,
    and the arithmetic that turns a pixel of a click back into degrees. They used to be
    written out separately, and the squares were floated into whatever width the window gave
    them, so a complete view came out ragged with a hole in the corner that looked exactly
    like squares nobody had fetched. Nothing here runs JavaScript, so the page is read as
    text, and 3 times 3 is also the count the README promises the tile server per view."""
    _, page = call(panel[0].port, "/", raw=True)
    assert page.count("const MG=3;") == 1, "a view needs one number for its shape"
    assert "for(let dy=0;dy<MG;dy++)for(let dx=0;dx<MG;dx++){" in page
    assert "repeat('+MG+',var(--sq))" in page, "the grid is told the same number"
    assert "display:inline-grid" in page, "the box must be exactly as wide as its squares"
    assert "float:left" not in page, "floated squares wrap to whatever room the window gives"
    assert "q.x0=q.x-rad" in page and "Math.max(0,q.x0+dx)" in page
    assert "MQ.x0+(ev.clientX-r.left)*MG/r.width" in page
    assert "(q.fx-q.x0)*100/MG" in page, "the mark is a share of the box, not a pixel count"
    assert "px;top:" not in page, "a mark in pixels is a whole square off once the squares " \
                                  "are drawn smaller than they were served"


def test_a_place_that_was_found_can_be_looked_at_before_it_is_written(panel):
    """Pressing find-it used to leave one door, and it was the door that writes: somebody
    searching for a place expected the map to go there, and instead nothing seemed to happen
    because the only button moved the profile. So a hit now offers look-there, which does
    what a click on the map does - mark, view, dial and the two boxes move, the nearby towns
    coming from arithmetic the daemon does for itself - while use-this stays the one button
    a found place reaches the file through. The number of times the write endpoint appears
    in the page is pinned so that no third door opens by accident."""
    _, page = call(panel[0].port, "/", raw=True)
    assert "async function look(f){" in page
    assert 'data-look="' in page and ">look there</button>" in page
    assert "api('/api/near?lat='+encodeURIComponent(f.latitude)" in page, \
        "a look asks the daemon for its own arithmetic, not a stranger"
    assert page.count("MP={latitude:W.latitude,longitude:W.longitude};") == 2, \
        "a found place and a typed place become the view the same way"
    assert page.count("/api/location") == 2, "write-these and use-this, and no third door"
    assert "Looking costs nothing and writes nothing" in page, \
        "the page says which button is the one with consequences"


def test_a_look_up_that_found_nothing_answers_where_the_words_were_typed(panel):
    """The only sign that the geocoder had nothing to say was a banner at the top of a long
    page, so somebody who pressed find-it on a street address saw a list that stayed empty
    and took it for a broken panel. The list answers for itself now, and it names the reason
    that measuring turned up: a whole address is one hard question, because a street is
    filed under the place it sits in rather than under the town name people put in a posting
    address. This corrects what the first version of this note blamed, which was house
    numbers - the numbers are in the data, and it is the town that stops the answer. The
    note waits for an answered look-up, so it can never be read as the answer to a question
    that was never asked."""
    _, page = call(panel[0].port, "/", raw=True)
    assert "let W=null, FH=[], FQ='', TA='', MP=null," in page
    assert "box.innerHTML=FQ?" in page, "the answer appears where the words went in"
    assert "Nothing came back for those words. A whole address" in page
    assert "rather than the town name" in page, "and the note says which word is the trouble"
    assert "FQ=q; FH=j.hits||[]; showFound();" in page, \
        "a look-up that was never answered leaves no answer behind"
    assert "The postal code answers where the name of a town stops the answer" in page, \
        "and the code box is offered as the other way in, not only the shorter words"


def test_the_page_gives_the_postal_code_its_own_box_and_says_what_it_is_for(panel):
    """The second box is the whole usability change, so the page has to say what it measured:
    a code answers where a town's name is the thing that stops the answer; a code alone finds
    a whole code area, and one code can exist in two countries; and when the answer is a
    street rather than a door, the click on the map is the house number. The tolerance is
    stated because the fallback of using a street without clicking is worth saying out loud:
    measuring a shift of a kilometre in the saved position moved no prayer time by a whole
    second, which is why the click matters for finding the right street and not for the
    arithmetic afterwards."""
    _, page = call(panel[0].port, "/", raw=True)
    assert '<label>postal code <input id="zip"' in page
    assert "const q=$('#place').value.trim(), zp=$('#zip').value.trim();" in page
    assert "if(!q&&!zp) throw new Error('type a street or a postal code first');" in page
    assert "const j=await api('/api/geocode',{q:q,postcode:zp});" in page
    assert "the street in one box and the code in the other" in page
    assert "the town is the word to leave out" in page
    assert "one code can" in page and "exist in two countries" in page
    assert ("the click is the house number, and a mark a kilometre off moves a prayer time"
            in page)
    assert "the street writes a point on it, and a kilometre is worth under a second" in page


def test_an_answer_that_was_empty_offers_the_same_words_without_the_town(panel,
                                                                        monkeypatch):
    """Measuring said the offer belongs only to an empty answer: a line that already answers
    is beaten by a shorter one, so the whole line "1600 pennsylvania ave nw washington dc"
    answers with the White House while the same words with the town taken off answer with
    avenues in Florida and Texas. So the panel offers the cut only when nothing came back,
    shows the exact words it means to send, and sends nothing until the button carrying them
    is pressed - which is the same button, so a second ask stays a decision somebody made."""
    web, _, _ = panel
    monkeypatch.setattr(geocode, "_open",
                        lambda url, accept="application/json": b"[]")
    status, res = call(web.port, "/api/geocode",
                       {"q": "109 garden cove ct orlando, florida"})
    assert status == 200 and res["hits"] == []
    assert res["try_again"] == "109 garden cove ct", "the offer names the words it suggests"
    named = json.dumps([{"display_name": "1200, Peach Street, Erie, Pennsylvania",
                         "lat": "42.1023456", "lon": "-80.0654321",
                         "extratags": {"timezone": "America/New_York"}}]).encode()
    monkeypatch.setattr(geocode, "_open",
                        lambda url, accept="application/json": named)
    status, res = call(web.port, "/api/geocode", {"q": "1200 Peach Street, Erie, PA"})
    assert status == 200 and res["hits"], "the line that works still works"
    assert res["try_again"] == "", "a line that already answers is never cut down"
    _, page = call(web.port, "/", raw=True)
    assert "TA=j.try_again||'';" in page, "an answered look-up clears the offer away"
    assert '<button id="tryagain">ask with those' in page
    assert "$('#place').value=TA; $('#findit').click();" in page, \
        "the offer goes through the same button, so it cannot ask on its own"
    assert "same name in another town answers just as happily, and that is not your street" \
        in page, "and the offer says why to read the labels"


def test_an_answer_that_is_not_a_picture_is_not_shown_as_one(tmp_path, monkeypatch):
    """This origin would be serving the bytes, so a login page or a captive portal from
    somewhere else would arrive at the browser looking like it came from the daemon. The
    header is checked before anything is kept or shown."""
    monkeypatch.setattr(geocode, "_open",
                        lambda url, accept="application/json": b"<html>hello</html>")
    web, _, _ = _serve(tmp_path, MAPPED)
    try:
        status, body, _ = get_bytes(web.port, "/api/tile?z=12&x=1&y=1")
        assert status == 502 and b"not a picture" in body, (status, body)
        folder = tmp_path / "muezzin-tiles"
        kept = list(folder.rglob("*.png")) if folder.exists() else []
        assert kept == [], f"an answer that is not a picture was kept: {kept}"
    finally:
        web.runner.shutdown()


def test_a_square_off_the_edge_of_the_map_is_refused(tmp_path, monkeypatch):
    """Zoom 30 has no squares in it, and asking the map server for one is a way of
    finding out what a public server does with nonsense at somebody else's expense."""
    monkeypatch.setattr(geocode, "_open",
                        lambda url, accept="application/json": PNG)
    web, _, _ = _serve(tmp_path, MAPPED)
    try:
        for query in ("z=30&x=1&y=1", "z=3&x=999&y=0", "z=abc&x=1&y=1"):
            status, body, _ = get_bytes(web.port, f"/api/tile?{query}")
            assert status == 400, (query, status, body[:80])
    finally:
        web.runner.shutdown()


def test_a_map_square_is_not_handed_to_a_page_that_is_not_this_one(tmp_path,
                                                                   monkeypatch):
    """The square route hands over bytes, so it is the one route where a foreign page
    could read an answer through this origin. Same guard as the recordings."""
    monkeypatch.setattr(geocode, "_open",
                        lambda url, accept="application/json": PNG)
    web, _, _ = _serve(tmp_path, MAPPED)
    try:
        status, body, _ = get_bytes(web.port, "/api/tile?z=12&x=1&y=1",
                                    headers={"Sec-Fetch-Site": "cross-site"})
        assert status == 403, (status, body[:80])
    finally:
        web.runner.shutdown()


def test_a_map_that_cannot_be_reached_costs_nobody_the_times(tmp_path, monkeypatch):
    """The map is the one part of the page that depends on a stranger, and the times are
    the reason the page exists. So an unreachable tile server is a grey square with a
    reason, and nothing else on the page changes."""
    def refused(url, accept="application/json"):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(geocode, "TILE_RETRY_WAIT", 0.0)
    monkeypatch.setattr(geocode, "_open", refused)
    web, _, _ = _serve(tmp_path, MAPPED)
    try:
        status, body, _ = get_bytes(web.port, "/api/tile?z=12&x=1&y=1")
        assert status == 502 and b"courtesy" in body, (status, body)
        _, st = call(web.port, "/api/state")
        assert st["upcoming"], "the times went down with the map"
    finally:
        web.runner.shutdown()


# Nine squares per view, one public server, and a household that notices a hole in the
# middle of its map long before it notices anything else on the page. The distinction the
# panel keeps hold of is the one between a square that did not arrive and a square that
# arrived with nothing in it: the first is marked and can be asked for again, the second
# is a picture of a lake.

def test_the_squares_of_one_view_go_out_one_at_a_time(tmp_path, monkeypatch):
    """A browser sends all nine at once, and the tile layer asks to be treated like one
    person browsing, which is about one request a second. Being polite here is also what
    makes the view come back complete: the empty squares are what a server answers when
    it is asked for nine at the same instant."""
    clock: list[float] = []

    def timed(url, accept="application/json"):
        clock.append(time.monotonic())
        return PNG

    monkeypatch.setattr(geocode, "_open", timed)
    web, _, _ = _serve(tmp_path, MAPPED)
    try:
        web.tile_spacing = 0.4      # the rule itself, without the suite waiting on it
        threads = [threading.Thread(target=get_bytes,
                                    args=(web.port, f"/api/tile?z=12&x={1000 + n}&y=1517"))
                   for n in range(3)]
        for one in threads:
            one.start()
        for one in threads:
            one.join()
        assert len(clock) == 3, f"the page should have asked for three squares: {clock}"
        gaps = [later - sooner for sooner, later in zip(clock, clock[1:])]
        assert all(gap >= 0.35 for gap in gaps), f"the asks went out together: {gaps}"
    finally:
        web.runner.shutdown()


def test_the_page_says_what_a_dim_square_means_and_how_to_ask_again(panel):
    """A square that did not arrive has to be legible as that, rather than as a pale
    patch of ground: the mark says which, and the button is the way to fix it without
    reloading the whole page."""
    web, _, _ = panel
    _, page = call(web.port, "/", raw=True)
    assert "i.style.opacity=.15" in page, "a square that did not arrive is invisible"
    assert 'id="zagain"' in page and "try those again" in page, "no way to ask again"
    assert "MAPTAG=''" in page, "the retry has to clear the memo that stops the asking"


