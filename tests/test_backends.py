"""What a backend is allowed to claim it did.

The Cast path needs a real speaker to run, but the judgement it makes afterwards
- did the adhan actually reach the end of the file? - is plain arithmetic over
the status the speaker reported, so that judgement is what is tested here. It is
the difference between a log line and a quiet morning. So is the judgement it
makes before sending anything: whether the speaker is awake, tested against a
connection that behaves the way pychromecast behaves when other apps already
hold the speaker open.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from muezzin import backends
from muezzin.backends import BackendError, CastBackend, LanBoxBackend, PcSpeakersBackend
from muezzin.config import OutputConfig


def study() -> CastBackend:
    return CastBackend(OutputConfig(name="study", kind="google_cast",
                                    target="Study speaker"))


def status(player_state, idle_reason=None):
    return SimpleNamespace(player_state=player_state, idle_reason=idle_reason)


def test_a_clip_the_speaker_played_to_the_end_counts_as_played():
    study()._check_finished("Study speaker", Path("fajr.wav"), status("IDLE", "FINISHED"))


def test_a_dead_stream_is_not_reported_as_a_played_adhan():
    """The receiver says ERROR when it cannot fetch or decode the file. Reporting
    that as success is how a wrong media URL becomes silence at 5 am."""
    with pytest.raises(BackendError, match="could not finish"):
        study()._check_finished("Study speaker", Path("fajr.wav"), status("IDLE", "ERROR"))


def test_a_clip_still_playing_past_the_limit_is_a_failure():
    with pytest.raises(BackendError, match="still playing"):
        study()._check_finished("Study speaker", Path("dua.wav"), status("PLAYING"))


def test_someone_else_taking_over_the_speaker_is_a_warning_not_an_error(caplog):
    """Interrupted means another source grabbed the speaker mid-adhan: worth a
    log line, but nothing went wrong in muezzin and the rest of the profile runs."""
    study()._check_finished("Study speaker", Path("fajr.wav"), status("IDLE", "CANCELINTERRUPTED"))
    assert "stopped fajr.wav early" in caplog.text


def test_a_speaker_that_reported_nothing_is_not_claimed_to_have_finished():
    """A media status of [] is what a Nest sends right after a load; the caller
    has already waited, so it is neither a success claim nor a crash."""
    study()._check_finished("Study speaker", Path("fajr.wav"), None)


@pytest.mark.parametrize("name,expected", [
    ("fajr.wav", "audio/wav"),
    ("fajr.mp3", "audio/mpeg"),
    ("dua.m4a", "audio/mp4"),
    ("dua.opus", "audio/opus"),
    ("dua.flac", "audio/flac"),
    ("strange.qqq", "application/octet-stream"),
])
def test_the_type_handed_to_the_speaker_matches_the_file(name, expected):
    """A Nest decides whether to fetch a URL by the type it is told. Guess wrong
    and the adhan is refused at the speaker, which is the one failure the log
    cannot see from the daemon's side."""
    from muezzin.backends import _content_type
    assert _content_type(Path(name)) == expected


def test_a_speaker_that_never_sends_a_status_fails_cleanly(monkeypatch):
    """A Nest that has gone to sleep still answers mDNS, so a status message is
    the first honest test of whether it is there. Waiting on it forever would stop
    every later speaker in the profile behind it, and a connection left open on
    the way out leaves a receiver thread behind for every retry."""
    import pychromecast

    from muezzin import backends

    calls = []

    class Asleep:
        status = None

        def wait(self, timeout=None):
            calls.append("wait")
            return False                      # what pychromecast returns on a timeout

        def quit_app(self):
            calls.append("quit")

        def disconnect(self):
            calls.append("disconnect")

    monkeypatch.setattr(backends, "find_cast", lambda target, tries=2: (
        device("Study speaker", id="0e5a9d4f-3f2f-4a4b-9e1c-1f3b2c8d9e0a"), []))
    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", lambda info: Asleep())
    b = study()
    b.READY_SECONDS = 0.2
    with pytest.raises(BackendError, match="sent no receiver status"):
        b.play([Path("fajr.wav")])
    assert calls == ["wait", "quit", "disconnect"], "the connection was left lying around"


def test_a_speaker_the_helper_wrote_off_still_gets_the_audio(monkeypatch, tmp_path):
    """The live failure this test exists for.

    Chrome, Spotify and Steam each keep a Cast control channel permanently open to
    every speaker on this LAN, and the receiver accepts our connection and then
    drops it and reconnects. pychromecast's `wait()` reports failure in that
    situation while the speaker is perfectly willing - it answered GET_STATUS,
    took the volume and launched the media app. A daemon that trusted that verdict
    played nothing at 5 am and called a healthy speaker asleep, which is the worst
    kind of bug in this program: the adhan is quietly skipped and the log looks fine.
    """
    import pychromecast

    from muezzin import backends

    sent = []

    class Media:
        def __init__(self):
            self.polls = 0
            self.status = SimpleNamespace(player_state="IDLE", idle_reason=None)

        def play_media(self, url, ctype, stream_type=None):
            sent.append(("media", url, ctype, stream_type))

        def block_until_active(self, timeout=None):
            self.status = SimpleNamespace(player_state="PLAYING", idle_reason=None)

        def update_status(self):
            self.polls += 1
            if self.polls >= 2:               # it plays, then reports it finished
                self.status = SimpleNamespace(player_state="IDLE", idle_reason="FINISHED")

    class Speaker:
        def __init__(self):
            self.status = None
            self.media_controller = Media()

        def wait(self, timeout=None):
            self.status = SimpleNamespace(app_id=None)   # the status arrives anyway
            return False                                  # ... and the lie

        def set_volume(self, level):
            sent.append(("volume", level))

        def quit_app(self):
            sent.append("quit")

        def disconnect(self):
            sent.append("disconnect")

    clip = tmp_path / "fajr.wav"
    clip.write_bytes(b"RIFF")
    monkeypatch.setattr(backends, "find_cast", lambda target, tries=2: (
        device("Study speaker", id="0e5a9d4f-3f2f-4a4b-9e1c-1f3b2c8d9e0a"), []))
    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", lambda info: Speaker())
    b = study()
    b.poll_seconds = 0.01
    b.max_play_seconds = 2.0
    b.media_server = SimpleNamespace(url_for=lambda p: "http://192.0.2.10:8010/" + p.name)
    b.play([clip])
    assert [c[0] for c in sent[:2]] == ["volume", "media"], sent
    assert sent[0][1] == backends.DEFAULT_CAST_VOLUME, "a speaker is the one thing a level applies to"
    assert sent[1][1:] == ("http://192.0.2.10:8010/fajr.wav", "audio/wav", "BUFFERED"), sent
    assert "quit" in sent and "disconnect" in sent, "the connection was left lying around"


def test_a_speaker_that_never_says_playing_is_reported_as_unproven(caplog):
    """A four-second chime can be over before the first poll lands, so the receiver
    never shows PLAYING to us. Claiming it played would be a guess; claiming it
    failed would be wrong just as often. Say which of the two is unknown."""
    study()._check_finished("Study speaker", Path("fajr.wav"), status("IDLE"), started=False)
    assert "never reported playing fajr.wav" in caplog.text
    assert "did not finish" not in caplog.text



def test_a_computer_output_is_never_handed_a_level(tmp_path, monkeypatch, caplog):
    """pc_speakers is this machine's own speaker, so neither the profile's `volume:`
    nor an event's override may reach it. And a profile that wrote the knob anyway
    is told so once, when the output is built, rather than at the 5 am it would
    otherwise have surfaced."""
    seen = []
    monkeypatch.setattr(backends.localplay, "play_file",
                        lambda path, player=None: seen.append(path.name))
    with caplog.at_level("WARNING"):
        b = PcSpeakersBackend(OutputConfig(name="parlour", kind="pc_speakers", volume=0.2))
    assert "parlour" in caplog.text and "volume" in caplog.text and "0.2" in caplog.text
    clip = tmp_path / "fajr.mp3"
    clip.write_bytes(b"ID3")
    b.play([clip], 0.9)          # an event's level, aimed at a computer: it goes to the speaker as-is
    assert seen == ["fajr.mp3"], "playback still happens, at the machine's own level"


def test_the_level_a_speaker_is_asked_for_is_the_one_the_profile_wrote():
    """The web page now writes `volume:` for a speaker, on the promise that the test you
    can hear comes out at the level you set rather than at whatever the room happened to
    be left at. That promise is this one arithmetic, so it is pinned here: the level the
    output carries is the level the speaker is asked for when the play call carries none
    of its own, which is exactly what a test from the page sends. An event that asked for
    its own level still wins, because that is the more recent ask; and a written `0` has
    to mean silence rather than the default, because a person who wrote 0 meant it."""
    def asked(volume, per_call):
        return CastBackend(OutputConfig(name="nest", kind="google_cast",
                                        target="Nest Mini", volume=volume))._effective_volume(per_call)

    assert asked(0.35, None) == 0.35
    assert asked(0.35, 0.8) == 0.8, "an event's own `volume:` out-ranks the speaker's"
    assert asked(0.0, None) == 0.0, "the default must not talk a written silence out of it"
    assert asked(None, None) == backends.DEFAULT_CAST_VOLUME, \
        "nothing written is the default, and saying so is what the page shows"
    assert asked(40, None) == 1.0, "a level that left the page is clamped on the way to the speaker"


def test_the_box_is_told_what_to_play_and_nothing_about_its_volume(tmp_path, monkeypatch):
    """What the daemon puts on the wire for a box is media and nothing else. A box
    is somebody's computer, and a request that also moved its volume would be
    reaching into a room that is not ours."""
    bodies = []

    class Resp:
        status = 200

        def read(self):
            # What the real box answers when a recording has finished: the daemon reads
            # the word so a playback someone stopped comes back as "stopped".
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def capture(req, timeout=None):
        bodies.append(req.data)
        return Resp()

    monkeypatch.setattr(backends.urllib.request, "urlopen", capture)
    clip = tmp_path / "fajr.mp3"
    clip.write_bytes(b"ID3")
    b = LanBoxBackend(OutputConfig(name="attic-pi", kind="lan_box",
                                   host="192.0.2.156", volume=0.3))
    b.play([clip], 0.9)
    assert len(bodies) == 1, bodies
    assert b"files" in bodies[0] and b"volume" not in bodies[0], bodies[0]


def answering(body: bytes):
    """A stand-in for `urlopen` that hands back one HTTP answer with `body` in it."""
    class Resp:
        status = 200

        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False
    return lambda req, timeout=None: Resp()


def test_a_box_that_was_stopped_says_so_and_the_daemon_says_it_back(tmp_path, monkeypatch):
    """The box knows the difference between a recording that ended and a recording
    somebody put down, and that difference has to travel back: a test called out of
    the hall speaker is not a speaker that failed, and the line a person reads the
    next morning should not read like one."""
    from muezzin import localplay

    monkeypatch.setattr(backends.urllib.request, "urlopen",
                        answering(b"stopped"))
    clip = tmp_path / "fajr.mp3"
    clip.write_bytes(b"ID3")
    b = LanBoxBackend(OutputConfig(name="attic-pi", kind="lan_box", host="192.0.2.156"))
    with pytest.raises(localplay.Stopped):
        b.play([clip], 0.9)


def test_the_ask_to_stop_reaches_the_box_over_the_wire(tmp_path, monkeypatch):
    """The daemon's own thread is the one sitting in the long `/play`, so going quiet
    means a second request to the box and not a word to itself."""
    asks = []
    answer = answering(b'{"stopped": 2}')

    def capture(req, timeout=None):
        asks.append((req.full_url, req.get_method()))
        return answer(req, timeout)

    monkeypatch.setattr(backends.urllib.request, "urlopen", capture)
    b = LanBoxBackend(OutputConfig(name="attic-pi", kind="lan_box", host="192.0.2.156"))
    assert b.stop() is True
    assert asks == [("http://192.0.2.156:8090/stop", "POST")]


def test_a_box_from_before_the_stop_route_says_it_cannot_be_interrupted(tmp_path, monkeypatch):
    """A 404 from an older box is that box honestly saying it has no such route. The
    daemon reports that as "no" and says where to look, rather than raising."""
    import urllib.error

    def refuse(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, None)

    monkeypatch.setattr(backends.urllib.request, "urlopen", refuse)
    b = LanBoxBackend(OutputConfig(name="attic-pi", kind="lan_box", host="192.0.2.156"))
    assert b.stop() is False


def device(name, group=False, **extra):
    row = {"name": name, "model": "Nest Audio", "group": group, "id": name,
           "address": "192.168.0.21", "port": 8009}
    row.update(extra)
    return row


def test_the_devices_list_prints_who_is_inside_a_group(monkeypatch, capsys):
    """The command is how most people first find out that a group is not a
    speaker, so the members have to be in its output - and a group whose speakers
    would not answer must read as unknown rather than as an empty room."""
    from muezzin import cli

    def fake(timeout=5.0, ask_members=True):
        return {
            "speakers": [device("Landing speaker")],
            "groups": [
                device("Whole-house group", group=True, members=["Landing speaker"],
                       membership_known=True, silent=[]),
                device("Quiet group", group=True, members=[], membership_known=False,
                       silent=["nobody"]),
            ],
            "boxes": [], "asked": 1, "silent": ["nobody"],
        }

    monkeypatch.setattr("muezzin.backends.scan_speakers", fake)
    assert cli.cmd_devices(1.0) == 0
    printed = capsys.readouterr().out
    assert "members: Landing speaker" in printed
    assert "Quiet group" in printed
    assert "members: unknown, those speakers did not answer" in printed
