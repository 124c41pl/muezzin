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
import shutil
import subprocess
import sys
from pathlib import Path

# the built-in Windows path: not a command line, so it is reported by name
WINMM = "winmm"

# a stream that stalls must not hold a speaker for the rest of the day
PLAY_SECONDS = 10 * 60


class LocalPlaybackError(RuntimeError):
    """Nothing here can play a local file, or the player refused this one."""


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


def play_file(path: Path, player: list[str] | None = None) -> str:
    """Play one file on this machine's default output, blocking until it ends.

    Returns the name of the player used, so a caller can put it in a log line or
    in a status a person reads. ``player`` replaces the choice with a command
    list, which is how ``muezzin box --player`` works and how the tests watch a
    playback without needing a speaker.

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
        subprocess.run(cmd + [str(path)], check=True, timeout=PLAY_SECONDS)
    except FileNotFoundError as exc:
        raise LocalPlaybackError(f"{name} is not on this machine: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        # the player wrote its own reason to its stderr, which is this process's
        # stderr, so the exit code is enough here to name the failure
        raise LocalPlaybackError(
            f"{name} refused {path.name} (exit {exc.returncode})") from exc
    except subprocess.TimeoutExpired as exc:
        raise LocalPlaybackError(
            f"{name} was still playing {path.name} after {PLAY_SECONDS}s") from exc


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
        # No setvolume: the level this machine plays at is that machine's own
        # business, and MCI's level call is a thing a driver may not implement
        # anyway. Whatever is playing is playing because someone chose it.
        run(f"play {alias} wait")
    finally:
        # close what was opened even when playing failed, or the alias and the file
        # handle are left behind on a machine that plays all day
        run(f"close {alias}", required=False)
