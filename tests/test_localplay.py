"""Local playback, the one part of the program that has to know which operating
system it is on.

Nothing here needs a speaker. The thing worth pinning down is the *choosing*:
which player a machine would use, what happens when it has none, and that a
player which fails produces a clean refusal instead of a stack trace. A house
should be able to run this on a Pi, a Windows PC or a Mac in a cupboard and get
the same behaviour out of whichever machine it landed on.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from muezzin import localplay
from muezzin.backends import BackendError, PcSpeakersBackend
from muezzin.box import Box

# the same stub trick the box tests use: instead of a speaker, a command that
# records what it was handed so the test can read it back. With `python -c`,
# sys.argv[0] is "-c", so argv[1] is the marker and argv[2:] is what we passed.
STUB = ("import sys,pathlib; pathlib.Path(sys.argv[1]).write_text("
        "sys.argv[2] + '|' + str(len(sys.argv) - 2))")


def pick(which: dict[str, str]):
    """Pretend this machine is a machine where exactly these commands exist."""
    return lambda name: which.get(name)


def test_windows_needs_nothing_installed(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(localplay.shutil, "which", pick({}))
    name, cmd = localplay.candidate()
    assert name == localplay.WINMM and cmd == []


def test_macos_uses_the_player_that_ships_with_it(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(localplay.shutil, "which", pick({"afplay": "/usr/bin/afplay"}))
    assert localplay.candidate() == ("afplay", ["afplay"])


def test_a_mac_without_afplay_says_so_about_macos(monkeypatch):
    """The advice has to be the advice for the machine you are actually on: a
    Linux install command on a Mac is a dead end and an insult to the reader."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(localplay.shutil, "which", pick({}))
    assert localplay.candidate() == ("none", [])
    advice = localplay.install_advice()
    assert "afplay" in advice and "apt" not in advice


def test_linux_takes_the_smallest_thing_that_plays_mp3(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(localplay.shutil,
                        "which", pick({"aplay": "/usr/bin/aplay", "mpg123": "/usr/bin/mpg123"}))
    assert localplay.candidate() == ("mpg123", ["mpg123", "-q"])


def test_a_linux_box_with_only_wav_playback_still_gets_an_answer(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(localplay.shutil, "which", pick({"paplay": "/usr/bin/paplay"}))
    assert localplay.candidate() == ("paplay", ["paplay"])


def test_a_machine_with_nothing_names_what_to_install(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(localplay.shutil, "which", pick({}))
    assert localplay.candidate() == ("none", [])
    advice = localplay.install_advice()
    assert "mpg123" in advice and "apt" in advice and "--player" in advice


def test_an_explicit_player_beats_the_guess(tmp_path):
    """--player is how a person with a player under another name gets their sound,
    and it is what the tests use in place of a speaker."""
    marker = tmp_path / "what-it-got"
    used = localplay.play_file(tmp_path / "fajr.mp3",
                               player=[sys.executable, "-c", STUB, str(marker)])
    assert used == Path(sys.executable).name
    # one file argument only, and it is the file we were asked to play
    got, extra = marker.read_text().split("|")
    assert Path(got).name == "fajr.mp3" and extra == "1"


def test_a_player_that_is_not_there_is_a_refusal_not_a_crash(tmp_path):
    with pytest.raises(localplay.LocalPlaybackError) as caught:
        localplay.play_file(tmp_path / "fajr.mp3", player=["no-such-player-anywhere"])
    assert "no-such-player-anywhere" in str(caught.value)


def test_a_player_that_refuses_the_file_says_which_exit_code(tmp_path):
    with pytest.raises(localplay.LocalPlaybackError) as caught:
        localplay.play_file(tmp_path / "fajr.mp3",
                            player=[sys.executable, "-c", "import sys; sys.exit(3)"])
    assert "exit 3" in str(caught.value)


def test_winmm_is_only_claimed_where_winmm_exists(monkeypatch, tmp_path):
    """The built-in path is chosen by platform, and the platform can be wrong in
    a test: the honest answer is a refusal, not a silent nothing."""
    monkeypatch.setattr(sys, "platform", "win32")
    if hasattr(localplay.ctypes, "windll"):
        pytest.skip("this really is Windows, where the built-in path should work")
    with pytest.raises(localplay.LocalPlaybackError) as caught:
        localplay.play_file(tmp_path / "fajr.mp3")
    assert "winmm" in str(caught.value)


def test_the_machine_speakers_report_their_name_in_the_error(tmp_path, monkeypatch):
    """An output's name is how a person finds which line of their profile to fix,
    so it has to be in the message that reaches the log."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(localplay.shutil, "which", pick({}))

    class Cfg:
        name = "attic-pc"
        volume = 0.5

    wav = tmp_path / "test-chime.wav"
    wav.write_bytes(b"RIFF")
    with pytest.raises(BackendError) as caught:
        PcSpeakersBackend(Cfg()).play([wav])
    assert "attic-pc" in str(caught.value) and "mpg123" in str(caught.value)


def test_a_box_refuses_before_it_fetches_anything(tmp_path):
    """No point pulling a recording across the house to find there is nothing to
    play it with."""
    b = Box("quiet-box", port=0)
    b.player_name, b.player_cmd = "none", []
    with pytest.raises(RuntimeError) as caught:
        b.play([], {}, None)
    assert "no player" in str(caught.value).lower()


def test_a_box_with_a_player_hands_it_one_file(tmp_path):
    marker = tmp_path / "marker"
    b = Box("stub-box", port=0)
    b.player_name, b.player_cmd = "stub", [sys.executable, "-c", STUB, str(marker)]
    b.play([], {"maghrib.mp3": base64.b64encode(b"ID3\x03audio").decode()}, 0.3)
    assert Path(marker.read_text().split("|")[0]).name == "maghrib.mp3"
    assert b.last["played"] == ["maghrib.mp3"]


def test_the_volume_honesty_line_appears_where_volume_is_not_applied(tmp_path, caplog):
    """A volume in the profile that silently does nothing is a confusing silence,
    so the log has to say where the level actually comes from."""
    marker = tmp_path / "marker"
    with caplog.at_level("INFO"):
        localplay.play_file(tmp_path / "fajr.mp3", volume=0.4,
                            player=[sys.executable, "-c", STUB, str(marker)])
    assert "does not set it" in caplog.text and "0.4" in caplog.text


class FakeWinmm:
    """Records the MCI commands this program would send, and can refuse one of
    them the way a real Windows audio path here did: `setvolume` answered 261,
    "the driver cannot recognize the specified command"."""

    def __init__(self, refuse=()):
        self.sent: list[str] = []
        self.refuse = set(refuse)

    def mciSendStringW(self, command, buf, size, hwnd):
        self.sent.append(command.split()[0])
        return 261 if command.split()[0] in self.refuse else 0

    def mciGetErrorStringW(self, rc, buf, size):
        buf.value = "The driver cannot recognize the specified command."


def use_fake_winmm(monkeypatch, refuse=()):
    winmm = FakeWinmm(refuse)
    fake_ctypes = SimpleNamespace(windll=SimpleNamespace(winmm=winmm),
                                  create_unicode_buffer=lambda size: SimpleNamespace(value=""))
    monkeypatch.setattr(localplay, "ctypes", fake_ctypes)
    monkeypatch.setattr(sys, "platform", "win32")
    return winmm


def test_a_windows_path_that_refuses_the_volume_still_plays(tmp_path, monkeypatch, caplog):
    """Missed adhan is worse than a knob that did nothing, so a refused setvolume
    is a log line and not a refusal to play."""
    winmm = use_fake_winmm(monkeypatch, refuse={"setvolume"})
    with caplog.at_level("WARNING"):
        assert localplay.play_file(tmp_path / "fajr.mp3", volume=0.2) == localplay.WINMM
    assert winmm.sent == ["open", "setvolume", "play", "close"]
    assert "own level" in caplog.text


def test_no_volume_asked_means_no_level_command_sent(tmp_path, monkeypatch):
    """Leaving the level alone is the machine's own business; sending 0 because a
    profile did not name one would be inventing silence out of an empty field."""
    winmm = use_fake_winmm(monkeypatch)
    localplay.play_file(tmp_path / "fajr.mp3")
    assert winmm.sent == ["open", "play", "close"]


def test_the_file_is_closed_even_when_playback_fails(tmp_path, monkeypatch):
    """The daemon plays all day long; every failed attempt must not leave an alias
    and a file handle behind."""
    winmm = use_fake_winmm(monkeypatch, refuse={"play"})
    with pytest.raises(localplay.LocalPlaybackError):
        localplay.play_file(tmp_path / "fajr.mp3", volume=0.5)
    assert winmm.sent == ["open", "setvolume", "play", "close"]
