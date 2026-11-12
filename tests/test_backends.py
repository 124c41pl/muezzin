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

from muezzin.backends import BackendError, CastBackend
from muezzin.config import OutputConfig


def kitchen() -> CastBackend:
    return CastBackend(OutputConfig(name="kitchen", kind="google_cast",
                                    target="Kitchen speaker"))


def status(player_state, idle_reason=None):
    return SimpleNamespace(player_state=player_state, idle_reason=idle_reason)


def test_a_clip_the_speaker_played_to_the_end_counts_as_played():
    kitchen()._check_finished("Kitchen speaker", Path("fajr.wav"), status("IDLE", "FINISHED"))


def test_a_dead_stream_is_not_reported_as_a_played_adhan():
    """The receiver says ERROR when it cannot fetch or decode the file. Reporting
    that as success is how a wrong media URL becomes silence at 5 am."""
    with pytest.raises(BackendError, match="could not finish"):
        kitchen()._check_finished("Kitchen speaker", Path("fajr.wav"), status("IDLE", "ERROR"))


def test_a_clip_still_playing_past_the_limit_is_a_failure():
    with pytest.raises(BackendError, match="still playing"):
        kitchen()._check_finished("Kitchen speaker", Path("dua.wav"), status("PLAYING"))


def test_someone_else_taking_over_the_speaker_is_a_warning_not_an_error(caplog):
    """Interrupted means another source grabbed the speaker mid-adhan: worth a
    log line, but nothing went wrong in muezzin and the rest of the profile runs."""
    kitchen()._check_finished("Kitchen speaker", Path("fajr.wav"), status("IDLE", "CANCELINTERRUPTED"))
    assert "stopped fajr.wav early" in caplog.text


def test_a_speaker_that_reported_nothing_is_not_claimed_to_have_finished():
    """A media status of [] is what a Nest sends right after a load; the caller
    has already waited, so it is neither a success claim nor a crash."""
    kitchen()._check_finished("Kitchen speaker", Path("fajr.wav"), None)


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
        device("Kitchen speaker", id="0e5a9d4f-3f2f-4a4b-9e1c-1f3b2c8d9e0a"), []))
    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", lambda info: Asleep())
    b = kitchen()
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
        device("Kitchen speaker", id="0e5a9d4f-3f2f-4a4b-9e1c-1f3b2c8d9e0a"), []))
    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", lambda info: Speaker())
    b = kitchen()
    b.poll_seconds = 0.01
    b.max_play_seconds = 2.0
    b.media_server = SimpleNamespace(url_for=lambda p: "http://192.168.0.8:8010/" + p.name)
    b.play([clip])
    assert [c[0] for c in sent[:2]] == ["volume", "media"], sent
    assert sent[1][1:] == ("http://192.168.0.8:8010/fajr.wav", "audio/wav", "BUFFERED"), sent
    assert "quit" in sent and "disconnect" in sent, "the connection was left lying around"


def test_a_speaker_that_never_says_playing_is_reported_as_unproven(caplog):
    """A four-second chime can be over before the first poll lands, so the receiver
    never shows PLAYING to us. Claiming it played would be a guess; claiming it
    failed would be wrong just as often. Say which of the two is unknown."""
    kitchen()._check_finished("Kitchen speaker", Path("fajr.wav"), status("IDLE"), started=False)
    assert "never reported playing fajr.wav" in caplog.text
    assert "did not finish" not in caplog.text



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
            "speakers": [device("Bedroom speaker")],
            "groups": [
                device("Home group", group=True, members=["Bedroom speaker"],
                       membership_known=True, silent=[]),
                device("Quiet group", group=True, members=[], membership_known=False,
                       silent=["nobody"]),
            ],
            "boxes": [], "asked": 1, "silent": ["nobody"],
        }

    monkeypatch.setattr("muezzin.backends.scan_speakers", fake)
    assert cli.cmd_devices(1.0) == 0
    printed = capsys.readouterr().out
    assert "members: Bedroom speaker" in printed
    assert "Quiet group" in printed
    assert "members: unknown, those speakers did not answer" in printed
