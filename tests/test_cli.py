"""Command-line behaviour: a table a person can read, and a mistake they can act
on rather than a stack trace."""
from __future__ import annotations

import errno
import socket

import pytest

from muezzin import cli, net, web
from muezzin.cli import STARTER, _fmt, main, panel_address, starter_warnings
from muezzin.config import load_profile


def test_a_time_that_rounds_up_carries_its_day_marker():
    """Times are deliberately not wrapped into one day, and the table marks that
    with +1. 23.9999 rounds to a whole hour, so it lands in tomorrow - and the
    marker has to follow the clock over, or the row says today at midnight."""
    assert _fmt(None) == "  --  "
    assert _fmt(5.0) == "05:00"
    assert _fmt(5.9999) == "06:00"
    assert _fmt(23.9999) == "00:00+1"
    assert _fmt(24.9999) == "01:00+1"
    assert _fmt(-0.0001) == "00:00-1"


def test_a_profile_that_is_not_readable_yaml_says_so(tmp_path, capsys):
    path = tmp_path / "muezzin.yaml"
    path.write_text("location: {latitude: 40.7, longitude: -74.0\n", encoding="utf-8")
    assert main(["times", "-c", str(path)]) == 2
    err = capsys.readouterr().err
    assert "not readable YAML" in err
    assert "Traceback" not in err, "a half-written file should not print a stack trace"


def test_a_config_option_pointed_at_a_directory_says_so(tmp_path, capsys):
    assert main(["times", "-c", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert err.strip() and "Traceback" not in err, "the user needs a sentence, not a trace"


def test_a_missing_profile_tells_the_user_to_start_one(tmp_path, capsys):
    assert main(["times", "-c", str(tmp_path / "nope.yaml")]) == 2
    assert "muezzin init" in capsys.readouterr().err


def test_the_starter_names_no_speaker_the_reader_does_not_own(tmp_path, capsys):
    """The example profile shows four kinds of output because it is
    documentation. The file handed to a new user must name none of them: an
    output pointed at somebody else's speaker fails at every prayer, and the
    person who installed us five minutes ago has not seen a device list yet."""
    path = tmp_path / "muezzin.yaml"
    assert main(["init", "-c", str(path)]) == 0
    profile = load_profile(path)
    assert profile.outputs == [], "a starter may not name a device"
    assert len(profile.events) >= 5, "and it should still describe the five prayers"
    live = [ln for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    assert not [ln for ln in live if "target:" in ln], "a live target is a stranger's speaker"
    assert (path.parent / "media").is_dir()
    assert "no speakers are configured" in capsys.readouterr().out


def test_the_starter_can_name_a_media_folder_that_is_not_next_to_it(tmp_path, capsys):
    """The starter's `media_dir: media` is relative to the profile, which is right
    for a folder you move around and wrong for a container, where the audio is
    mounted at a fixed path outside the config volume. Without a way to name the
    mount, every pulled image ships a profile whose library is an empty directory,
    and the person who copied four recordings into ./media is shown a list with
    nothing in it and no error anywhere to explain it."""
    path = tmp_path / "config" / "muezzin.yaml"
    media = tmp_path / "sounds"
    assert main(["init", "-c", str(path), "--media-dir", str(media)]) == 0
    assert media.is_dir(), "init makes the folder it just promised"
    assert load_profile(path).media_dir == media.resolve(), "and the profile means the same folder"
    text = path.read_text(encoding="utf-8")
    assert "media_dir: media\n" not in text, "the relative default is gone, not shadowed"
    assert "# drop your adhan recordings in here" in text, "the comment that says what it is for stays"
    assert str(media) in capsys.readouterr().out, "the message names the folder it made"


def test_the_starter_says_out_loud_what_is_still_missing(tmp_path):
    """The two mistakes a starter makes easy both produce no error at all: a
    city nobody chose, and a schedule with nowhere to play."""
    path = tmp_path / "muezzin.yaml"
    main(["init", "-c", str(path)])
    notes = starter_warnings(load_profile(path))
    assert any("New York" in n for n in notes), notes
    assert any("no speakers" in n for n in notes), notes

    text = path.read_text(encoding="utf-8")
    text = text.replace("latitude: 40.7128", "latitude: 25.7123")
    text = text.replace("longitude: -74.006", "longitude: 51.0753")
    text = text.replace("timezone: America/New_York", "timezone: Asia/Tehran")
    # uncomment the shape as written, then take out the one field this kind of
    # output does not use: a commented example that cannot be uncommented as it
    # stands is a commented example that teaches nothing
    text = text.replace("  # - name: house-group", "  - name: house-group")
    text = text.replace("  #   kind: google_cast", "    kind: pc_speakers")
    text = text.replace("\n  #   target: Whole-house group", "")
    text = text.replace("  #   volume: 0.5", "    volume: 0.5")
    path.write_text(text, encoding="utf-8")
    set_up = load_profile(path)
    assert [o.name for o in set_up.outputs] == ["house-group"], "the shape uncomments cleanly"
    assert starter_warnings(set_up) == [], "a set-up profile gets lectured to nobody"


def test_the_starter_notes_reach_somebody_who_only_ran_the_table(tmp_path, capsys):
    """`times` is the first command a nervous user types, so the notes belong in
    its output - while the table on stdout stays a table that can be piped."""
    path = tmp_path / "muezzin.yaml"
    main(["init", "-c", str(path)])
    assert main(["times", "-c", str(path)]) == 0
    captured = capsys.readouterr()
    assert "New York" in captured.err and "no speakers" in captured.err
    assert "fajr" in captured.out
    assert "note:" not in captured.out, "the notes are not part of the table"


def test_the_table_shows_the_minutes_the_clocks_will_actually_show(tmp_path, capsys):
    """Santiago springs forward at midnight, so the midnight belonging to 2026-09-05
    falls inside an hour that no clock there showed. The row prints the reading that
    morning really had, which is the same moment the page and the daemon point at."""
    path = tmp_path / "muezzin.yaml"
    text = STARTER.replace("latitude: 40.7128", "latitude: -33.45")
    text = text.replace("longitude: -74.006", "longitude: -70.66")
    text = text.replace("timezone: America/New_York", "timezone: America/Santiago")
    path.write_text(text, encoding="utf-8")
    assert main(["times", "-c", str(path), "-d", "2026-09-05"]) == 0
    rows = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("2026-09-05")]
    assert rows, "no row for the date that was asked for"
    assert "01:41+1" in rows[0], f"the table printed {rows[0]!r}, which is not a clock reading"


def test_a_profile_that_changed_one_number_is_not_lectured(tmp_path):
    """The location note fires on the starter's exact placeholder triple, not on
    New York. A household that typed its own latitude - even in New York, and
    even leaving the timezone alone - has already told us what it needs."""
    path = tmp_path / "muezzin.yaml"
    path.write_text(STARTER.replace("latitude: 40.7128", "latitude: 40.7306"),
                    encoding="utf-8")
    notes = starter_warnings(load_profile(path))
    assert not [n for n in notes if "New York" in n], notes
    assert any("no speakers" in n for n in notes)


def test_a_starter_with_everything_switched_off_says_so(tmp_path):
    """Disabling every output is a thing the page lets you do, and the schedule
    then goes quiet with no other clue why."""
    path = tmp_path / "muezzin.yaml"
    path.write_text(STARTER.replace("  # - name: house-group", "  - name: pc")
                    .replace("  #   kind: google_cast", "    kind: pc_speakers")
                    .replace("  #   target: Whole-house group", "    enabled: false")
                    .replace("  #   volume: 0.5", ""), encoding="utf-8")
    notes = starter_warnings(load_profile(path))
    assert any("disabled" in n for n in notes), notes


SPEAKERS = """
location: {latitude: 40.7128, longitude: -74.006, timezone: America/New_York}
method: {preset: isna}
media_dir: media
outputs:
  - name: study
    kind: google_cast
    target: Study speaker
  - name: porch
    kind: google_cast
    target: Porch speaker
    lead_seconds: 0
events:
  - name: fajr-adhan
    at: fajr
    media: [fajr.mp3]
"""


def test_next_says_the_sound_starts_a_few_seconds_early(tmp_path, capsys):
    """`next` is the command people trust, so it promises the same number the
    daemon keeps: the time stays the computed one, and the note says the recording
    reaches a speaker that has to be found on the network a little before it —
    twelve seconds for a Cast speaker, now that a group's rooms are asked for their
    levels as part of the same hand-off. A speaker told `lead_seconds: 0` gets no
    note, because it starts on the minute."""
    path = tmp_path / "muezzin.yaml"
    path.write_text(SPEAKERS, encoding="utf-8")
    assert main(["next", "-c", str(path)]) == 0
    rows = [ln for ln in capsys.readouterr().out.splitlines() if "fajr-adhan" in ln]
    assert len(rows) >= 2, rows
    assert "(played 12 s early)" in rows[0], rows[0]
    assert "-> study, porch" in rows[0], "the slowest of the two is what gets paid for"
    quiet = SPEAKERS.replace("  - name: study\n    kind: google_cast\n    target: Study speaker\n", "")
    path.write_text(quiet, encoding="utf-8")
    assert main(["next", "-c", str(path)]) == 0
    line = [ln for ln in capsys.readouterr().out.splitlines() if "fajr-adhan" in ln][0]
    assert "early" not in line, line


def test_next_says_which_rows_draw_from_the_library(tmp_path, capsys):
    """A row that draws from the media folder cannot name its recordings, because the
    drawing does not happen until the event fires. An empty bracket would read as a
    broken event, so `next` says how many it will draw - and names the recordings an
    event promises outright when it does both at once."""
    path = tmp_path / "muezzin.yaml"
    both = SPEAKERS.replace("    media: [fajr.mp3]", "    media: [fajr.mp3]\n    random: 3")
    path.write_text(both, encoding="utf-8")
    assert main(["next", "-c", str(path)]) == 0
    line = [ln for ln in capsys.readouterr().out.splitlines() if "fajr-adhan" in ln][0]
    assert "[fajr.mp3 + 3 at random]" in line, line
    path.write_text(SPEAKERS.replace("    media: [fajr.mp3]", "    random: 2"),
                    encoding="utf-8")
    assert main(["next", "-c", str(path)]) == 0
    line = [ln for ln in capsys.readouterr().out.splitlines() if "fajr-adhan" in ln][0]
    assert "[2 at random]" in line, line


def test_the_log_line_names_an_address_a_phone_can_reach():
    """The interface this process can see is the container's own, so the address the
    media server found inside a container is usually 127.0.0.1 - and the one line in
    the log whose whole job is "open this" then points a phone at a page that is not
    there. A real address gets the line on its own; a loopback one carries the
    correction and the port to use instead."""
    on_a_lan = panel_address("192.168.0.9", 8020, False)
    assert on_a_lan == "http://192.168.0.9:8020", "nothing to explain about a usable address"
    inside = panel_address("127.0.0.1", 8020, True)
    assert inside.startswith("http://127.0.0.1:8020 (read-only)"), inside
    second = inside.split("\n", 1)[1]
    assert "8020" in second and "your network" in second, "the port to dial from elsewhere"
    assert "container" in second, second


# ---- ports from the environment ---------------------------------------------
#
# The reason these exist is the second container. An image arrives with its
# arguments already written, so a person who already has muezzin on 8020 and wants
# a second one on the same machine has one knob left: the environment. What the
# tests below pin down is which of the two ways to say a port wins, and what a
# wrong one costs - because both answers are invisible until somebody's page is on
# a port they never chose.

def _starter(tmp_path):
    path = tmp_path / "muezzin.yaml"
    assert main(["init", "-c", str(path)]) == 0
    return path


def test_the_environment_moves_the_page_when_the_flag_names_no_number(tmp_path, monkeypatch):
    """`--web` bare means "the page runs, you pick the port", and the container's
    default command says exactly that. So MUEZZIN_WEB_PORT is the whole change
    needed to run a second daemon beside the first."""
    path = _starter(tmp_path)
    seen = {}
    monkeypatch.setattr(cli, "cmd_daemon", lambda *a, **k: seen.update(web=a[1]) or 0)
    monkeypatch.setenv("MUEZZIN_WEB_PORT", "8080")
    assert main(["daemon", "-c", str(path), "--web"]) == 0
    assert seen["web"] == 8080, "the container could not move off a port its neighbour has"


def test_a_port_said_out_loud_on_the_command_line_beats_the_environment(tmp_path, monkeypatch):
    """The other way round would be a compose file whose own `command:` is quietly
    overruled by a variable inherited from a shell profile or a CI runner."""
    path = _starter(tmp_path)
    seen = {}
    monkeypatch.setattr(cli, "cmd_daemon", lambda *a, **k: seen.update(web=a[1]) or 0)
    monkeypatch.setenv("MUEZZIN_WEB_PORT", "8080")
    assert main(["daemon", "-c", str(path), "--web", "9000"]) == 0
    assert seen["web"] == 9000, "an argument the person typed lost to a variable they did not"


def test_the_environment_names_a_port_but_never_opens_the_page(tmp_path, monkeypatch):
    """A variable chooses a number; the flag decides whether there is a page at all.
    The page has no login, so a variable set somewhere upstream must not be able to
    start one inside a container that was asked only to play."""
    path = _starter(tmp_path)
    seen = {}
    monkeypatch.setattr(cli, "cmd_daemon", lambda *a, **k: seen.update(web=a[1]) or 0)
    monkeypatch.setenv("MUEZZIN_WEB_PORT", "8080")
    assert main(["daemon", "-c", str(path)]) == 0
    assert seen["web"] is None, "an unauthenticated page appeared out of an environment variable"


def test_zero_in_the_variable_means_a_free_port_not_the_default(tmp_path, monkeypatch):
    """0 is an answer, not an absence, and it is the answer for whoever would rather
    not keep a port ledger for the two daemons on one machine. A parser that tested
    the variable for truthiness would quietly answer 8020 instead."""
    path = _starter(tmp_path)
    seen = {}
    monkeypatch.setattr(cli, "cmd_daemon", lambda *a, **k: seen.update(web=a[1]) or 0)
    monkeypatch.setattr(cli, "cmd_web", lambda *a, **k: seen.update(port=a[1]) or 0)
    monkeypatch.setenv("MUEZZIN_WEB_PORT", "0")
    assert main(["daemon", "-c", str(path), "--web"]) == 0
    assert seen["web"] == 0, "the variable said take a free port; the parser said 8020"
    assert main(["web", "-c", str(path)]) == 0
    assert seen["port"] == 0


def test_the_page_only_command_takes_its_port_from_the_environment(tmp_path, monkeypatch):
    """`muezzin web` carries a default rather than a flag, so the variable has to be
    read where that default is built."""
    path = _starter(tmp_path)
    seen = {}
    monkeypatch.setattr(cli, "cmd_web", lambda *a, **k: seen.update(port=a[1]) or 0)
    monkeypatch.setenv("MUEZZIN_WEB_PORT", "8080")
    assert main(["web", "-c", str(path)]) == 0
    assert seen["port"] == 8080


def test_two_boxes_on_one_machine_each_get_their_own_port(tmp_path, monkeypatch):
    """Boxes announce the port they answer on, so a moved port is not a lost
    speaker: discovery finds it either way. What has to differ is the port, and the
    name, and both are per-container choices."""
    seen = {}
    monkeypatch.setattr(cli, "cmd_box", lambda *a, **k: seen.update(port=a[1]) or 0)
    monkeypatch.delenv("MUEZZIN_BOX_PORT", raising=False)
    assert main(["box", "--name", "attic-box"]) == 0
    assert seen["port"] == 8090, "the ordinary default, so nothing changes for one box"
    monkeypatch.setenv("MUEZZIN_BOX_PORT", "8123")
    assert main(["box", "--name", "hall-box"]) == 0
    assert seen["port"] == 8123


def test_a_port_that_is_not_a_port_names_the_variable_it_came_out_of(tmp_path, capsys, monkeypatch):
    """Found at the socket this mistake is an OSError about an address family, with
    nothing in it naming what was typed; the value came from a box on a keyboard
    somewhere, so the message has to say so."""
    path = _starter(tmp_path)
    for wrong in ("eighty", "70000", "80.5"):
        monkeypatch.setenv("MUEZZIN_WEB_PORT", wrong)
        assert main(["times", "-c", str(path)]) == 2, wrong
        err = capsys.readouterr().err
        assert "MUEZZIN_WEB_PORT" in err and wrong in err, err
        assert "Traceback" not in err, err


# ---- the port somebody else already has ---------------------------------------

def _fake_clash(code: int) -> OSError:
    exc = OSError(f"a clash, as the operating system would report it (errno {code})")
    exc.errno = code
    return exc


@pytest.mark.parametrize("code", [errno.EADDRINUSE, errno.EACCES])
def test_a_port_this_machine_cannot_use_names_the_knob_that_moves_it(capsys, code):
    """"[Errno 98] Address already in use" is a true sentence that tells a person
    running a second muezzin nothing they can act on: this program has two ports,
    and neither of them is named in the operating system's message."""
    assert cli._port_busy(_fake_clash(code), "the control panel", 8020,
                          "MUEZZIN_WEB_PORT", "`--port <port>`") == 2
    err = capsys.readouterr().err
    assert "the control panel could not start on port 8020" in err, err
    assert "MUEZZIN_WEB_PORT" in err and "--port" in err, "the two places to say another port"
    assert "0" in err, "and the answer for whoever does not want a port ledger"
    if code == errno.EACCES:
        assert "1024" in err, "a privileged port needs a different sentence than a taken one"


def test_a_startup_error_that_is_not_a_port_clash_keeps_its_traceback():
    """A media folder that went missing is an OSError too, and dressing it up as a
    port problem would send a person to change a port that was never the trouble."""
    missing = FileNotFoundError(2, "No such file or directory")
    with pytest.raises(FileNotFoundError):
        cli._port_busy(missing, "the media server", 8010, "MUEZZIN_HTTP_PORT", "`http_port:`")


def test_the_second_container_on_a_machine_is_told_what_it_clashed_into(tmp_path, capsys,
                                                                       monkeypatch):
    """The real thing: hold a port, then ask muezzin's own servers for it.

    Checked through the panel rather than the scheduler because `daemon` would
    otherwise sit in run_forever. A platform whose sockets let the second bind
    through anyway has a different problem to solve, and the test above is what
    pins the wording, so this one says so out loud instead of failing.
    """
    held = socket.socket()
    held.bind(("0.0.0.0", 0))
    held.listen(1)
    port = held.getsockname()[1]
    try:
        probe = net.LANServer(("0.0.0.0", port), lambda *a: None)
    except OSError:
        probe = None
    else:
        probe.server_close()
        pytest.skip("this platform let a second server bind a listening port")
    finally:
        held.close()

    held = socket.socket()
    held.bind(("0.0.0.0", port))
    held.listen(1)
    path = _starter(tmp_path)
    monkeypatch.setenv("MUEZZIN_HTTP_PORT", "0")       # so the clash is the page's
    monkeypatch.setattr(web.WebPanel, "serve_forever", lambda self: None)
    try:
        assert main(["web", "-c", str(path), "--port", str(port)]) == 2
    finally:
        held.close()
    err = capsys.readouterr().err
    assert "control panel" in err and "MUEZZIN_WEB_PORT" in err, err
    assert "Traceback" not in err, "two containers on one machine is a normal day, not a crash"
