"""Web panel tests: what the page is allowed to read, and - more importantly -
what it is allowed to write. A config edit that fails validation must never
reach the file the daemon reads, and a disabled output must stay silent."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request

import pytest

from muezzin.cli import STARTER
from muezzin.config import load_profile
from muezzin.scheduler import PRAYER_KEYS, Runner
from muezzin.web import WebPanel, _fmt

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
    assert st["method"]["midnight"] == "jafari (sunset to fajr)"
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


def test_the_state_names_the_methods_the_page_can_offer(panel):
    web, _, _ = panel
    _, st = call(web.port, "/api/state")
    names = {p["name"] for p in st["presets"]}
    assert {"isna", "qom", "tehran", "shia_ithna_ashari"} <= names
    jafari = {p["name"] for p in st["presets"] if p["shia"]}
    assert {"qom", "tehran", "shia_ithna_ashari", "qom_khamenei_12"} == jafari, \
        "the page groups by which midnight a school uses, so this set is load-bearing"
    assert st["method"]["preset"] == "isna"
    assert st["prayers"] == list(PRAYER_KEYS)
    assert {e["name"] for e in st["events"]} == {"fajr-adhan", "dhuhr-nudge", "friday-tune"}


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


def test_a_box_that_runs_another_app_is_not_offered_as_an_output(panel):
    web, _, _ = panel
    status, reply = call(web.port, "/api/box/add",
                         {"name": "raspberrypi", "host": "192.0.2.156", "port": 9874,
                          "kind": "smart_azan_pi"})
    assert status == 400 and "does not speak" in reply["error"]


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


def test_the_page_shows_where_you_are_to_a_metre_not_a_millimetre(panel):
    """The state reply goes to a page that anyone on the wifi can open, and six
    decimal places of position is a front door with a number on it. The file keeps
    what it had; only what is handed to the browser is rounded."""
    web, _, _ = panel
    _, st = call(web.port, "/api/state")
    assert st["location"]["latitude"] == 40.71
    assert st["location"]["longitude"] == -74.01
    assert "40.7128" in st["config_text"], "the profile the daemon runs on is untouched"


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
        status, reply = call(web.port, "/api/speaker/add", {"target": "Landing group"})
        assert status == 200, reply
        assert reply["output"] == "landing-group"
        added = load_profile(tmp_path / "muezzin.yaml")
        assert [o.name for o in added.outputs] == ["landing-group"]
        assert added.targets_for(added.events[0]) == added.outputs, \
            "the adhans reach the speaker the moment it exists"
        status, page = call(web.port, "/", raw=True)
        assert status == 200 and page.startswith("<!doctype html")
    finally:
        web.stop()
        runner.shutdown()

