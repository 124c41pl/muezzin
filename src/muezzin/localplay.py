"""How one machine makes a sound.

Local playback is the one part of muezzin that cannot be written once. Windows,
macOS and Linux each already ship something that can play a file, and none of
them ship the same thing. So this module holds the entire difference between the
three, and everything else - the machine's own speakers, or a box on the LAN
being driven by a daemon somewhere else - asks this one question instead of
carrying its own copy of the answer.

Nothing is downloaded or bundled. Each choice is what the operating system
already provides or what its package manager is one command away from, and when
none of them are present the answer is a refusal that names what to install, not
a guess.

A machine's own level is not part of this question. Nothing in here changes the
volume of a computer: that belongs to the person who owns the machine, and a
program that moves the sound while nobody is looking is a surprise, not a
feature. A level is set only on a speaker muezzin is casting to, so the
`volume:` knob in a profile means that speaker and nothing else.
"""
from __future__ import annotations

import ctypes
import itertools
import logging
import shutil
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger("muezzin.localplay")

# the built-in Windows path: not a command line, so it is reported by name
WINMM = "winmm"

# a stream that stalls must not hold a speaker for the rest of the day
PLAY_SECONDS = 10 * 60


class LocalPlaybackError(RuntimeError):
    """Nothing here can play a local file, or the player refused this one."""


class Stopped(RuntimeError):
    """The playback ended because somebody asked it to, not because the file ran out.

    This is its own answer rather than a failure, and rather than silence: a test
    someone cut short should come back as "stopped" in the log and on the page, not
    as a speaker that broke. Anything above this layer that catches it reports it that
    way and moves on.
    """


class _Handle:
    """One player that is going right now, and the one call that ends it."""

    __slots__ = ("stop_with", "asked")

    def __init__(self, stop_with):
        self.stop_with = stop_with
        # Set when stop_all() reaches this player. The thread that is sitting inside
        # the player needs it to tell a stopped playback from one that finished: both
        # end with the player going away, and only one of them was asked to.
        self.asked = False


# What is going on this machine right now. Playback here blocks: the thread that
# called play_file() sits inside it until the file ends, and the only thing that can
# end it early is some other thread reaching the player - which is what an ask to
# stop a test, or a box being told to go quiet, turns into.
_playing: list["_Handle"] = []
_playing_lock = threading.Lock()


def _track(handle: _Handle) -> None:
    with _playing_lock:
        _playing.append(handle)


def _untrack(handle: _Handle) -> None:
    with _playing_lock:
        try:
            _playing.remove(handle)
        except ValueError:
            # stop_all() took it out of the list a moment before this; the player
            # finished on its own terms, which is the good outcome either way.
            pass


def stop_all() -> int:
    """End whatever this machine is playing, and say how many things were told to.

    Nothing to stop is not an error and returns 0: the caller asked whether anything
    was still going, and no is the answer to that. A player that had already finished
    between the ask and this call is the same answer, so its complaints are logged
    rather than raised.
    """
    with _playing_lock:
        going = list(_playing)
        del _playing[:]
    stopped = 0
    for handle in going:
        handle.asked = True
        try:
            handle.stop_with()
            stopped += 1
        except OSError as exc:
            log.info("asking the local player to stop said: %s", exc)
    return stopped


def candidate() -> tuple[str, list[str]]:
    """The player this machine would use, as (name, command line).

    An empty command with the name ``winmm`` means "no command line: use the
    built-in path". The name ``none`` means nothing on this machine would work,
    and install_advice() says what is missing.
    """
    if sys.platform == "win32":
        return WINMM, []
    if sys.platform == "darwin":
        # afplay is part of macOS itself, so a Mac needs nothing installed.
        if shutil.which("afplay"):
            return "afplay", ["afplay"]
        return "none", []
    # Which of these exists is a distro question rather than a code question, so
    # the order is by how little it needs and how well it handles mp3.
    for name, cmd in (
        ("mpg123", ["mpg123", "-q"]),                      # mp3 and wav, tiny
        ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]),
        ("cvlc", ["cvlc", "--play-and-exit"]),
        ("paplay", ["paplay"]),                            # wav only
        ("aplay", ["aplay", "-q"]),                        # wav only
    ):
        if shutil.which(name):
            return name, cmd
    return "none", []


def install_advice() -> str:
    """What to do when candidate() found nothing, in the words a person needs."""
    if sys.platform == "win32":
        return "winmm comes with Windows, so this should not happen here."
    if sys.platform == "darwin":
        return ("afplay is part of macOS; if it is not on PATH this machine's "
                "installation is broken in a way muezzin cannot work around.")
    return ("install something that plays a file from the command line - on Debian "
            "and Raspberry Pi OS that is `sudo apt install mpg123`, on Fedora "
            "`sudo dnf install mpg123`. Any of mpg123, ffplay, cvlc, paplay or aplay "
            "works, and --player can point at any command that takes a file argument.")


def play_file(path: Path, player: list[str] | None = None, sink=None) -> str:
    """Play one file on this machine's default output, blocking until it ends.

    Returns the name of the player used, so a caller can put it in a log line or
    in a status a person reads. ``player`` replaces the choice with a command
    list, which is how ``muezzin box --player`` works and how the tests watch a
    playback without needing a speaker.

    Raises Stopped if stop_all() ended it, and LocalPlaybackError if nothing on this
    machine would play the file or the player refused it.

    There is no volume argument, on purpose. This plays at whatever level the
    machine running it is already set to, because that level is the machine
    owner's to set and nobody else's to change.
    """
    if player is None:
        name, cmd = candidate()
    else:
        name, cmd = Path(str(player[0])).name, [str(part) for part in player]
    if not cmd and name != WINMM:
        raise LocalPlaybackError(f"no player found on this machine. {install_advice()}")
    if name == WINMM:
        _play_winmm(Path(path))
    else:
        _play_command(name, cmd, Path(path))
    return name


def _play_command(name: str, cmd: list[str], path: Path) -> None:
    try:
        proc = subprocess.Popen(cmd + [str(path)])
    except FileNotFoundError as exc:
        raise LocalPlaybackError(f"{name} is not on this machine: {exc}") from exc
    # Registered before anything is waited on, because the ask to stop can arrive the
    # moment the player starts: a process that is not in the list is a process nobody
    # can reach.
    handle = _Handle(proc.terminate)
    _track(handle)
    try:
        try:
            proc.wait(timeout=PLAY_SECONDS)
        except subprocess.TimeoutExpired:
            # The same ending a stop gives, and the line after it says why.
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            raise LocalPlaybackError(
                f"{name} was still playing {path.name} after {PLAY_SECONDS}s") from None
    finally:
        _untrack(handle)
    if handle.asked:
        # A player that was told to stop usually exits with a nonzero code, which is
        # not a refusal: the ask came from this same process a moment ago.
        raise Stopped(f"{name} stopped playing {path.name} when asked to")
    if proc.returncode != 0:
        # the player wrote its own reason to its stderr, which is this process's
        # stderr, so the exit code is enough here to name the failure
        raise LocalPlaybackError(f"{name} refused {path.name} (exit {proc.returncode})")


# one MCI alias per open, so two outputs on the same machine - a daemon playing
# on its own speakers and a box it is also driving - cannot collide
_aliases = itertools.count(1)


def _play_winmm(path: Path) -> None:
    try:
        winmm = ctypes.windll.winmm
    except AttributeError as exc:      # not a Windows machine
        raise LocalPlaybackError(f"winmm is not available here. {install_advice()}") from exc
    alias = f"muezzin{next(_aliases)}"
    buf = ctypes.create_unicode_buffer(512)
    err = ctypes.create_unicode_buffer(512)

    def run(command: str, required: bool = True) -> bool:
        rc = winmm.mciSendStringW(command, buf, 512, 0)
        if rc == 0:
            return True
        if not required:
            return False
        winmm.mciGetErrorStringW(rc, err, 512)
        raise LocalPlaybackError(f"MCI '{command.split()[0]}' failed ({rc}): {err.value}")

    try:
        run(f'open "{path}" type mpegvideo alias {alias}')
        # Registered so an ask to stop can reach it. MCI's own stop command is what
        # releases a waiting `play`, so nothing has to reach the thread that is
        # sitting inside it; the flag below is how that thread learns why it came back.
        handle = _Handle(lambda: run(f"stop {alias}", required=False))
        _track(handle)
        try:
            # No setvolume: the level this machine plays at is that machine's own
            # business, and MCI's level call is a thing a driver may not implement
            # anyway. Whatever is playing is playing because someone chose it.
            run(f"play {alias} wait")
        finally:
            _untrack(handle)
    finally:
        # close what was opened even when playing failed, or the alias and the file
        # handle are left behind on a machine that plays all day
        run(f"close {alias}", required=False)
    if handle.asked:
        raise Stopped(f"winmm stopped playing {path.name} when asked to")
