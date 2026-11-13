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
"""
from __future__ import annotations

import ctypes
import itertools
import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("muezzin.localplay")

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


def play_file(path: Path, volume: float | None = None,
              player: list[str] | None = None) -> str:
    """Play one file on this machine's default output, blocking until it ends.

    Returns the name of the player used, so a caller can put it in a log line or
    in a status a person reads. ``player`` replaces the choice with a command
    list, which is how ``muezzin box --player`` works and how the tests watch a
    playback without needing a speaker.
    """
    if player is None:
        name, cmd = candidate()
    else:
        name, cmd = Path(str(player[0])).name, [str(part) for part in player]
    if not cmd and name != WINMM:
        raise LocalPlaybackError(f"no player found on this machine. {install_advice()}")
    if name == WINMM:
        _play_winmm(Path(path), volume)
    else:
        _play_command(name, cmd, Path(path), volume)
    return name


def _play_command(name: str, cmd: list[str], path: Path, volume: float | None) -> None:
    if volume is not None and name != WINMM:
        # Named out loud rather than ignored: a volume in the profile that
        # reaches a Cast speaker and not this machine is a confusing silence.
        log.info("volume %s asked for, but muezzin does not set it for %s; "
                 "use this machine's own volume", volume, name)
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


def _play_winmm(path: Path, volume: float | None) -> None:
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
        want = None if volume is None else int(max(0.0, min(1.0, float(volume))) * 1000)
        # setvolume is the one part of this that a Windows audio path may not
        # implement - measured here, the driver answers "cannot recognize the
        # specified command" - and silence because a knob was refused is the wrong
        # way to miss an adhan. So the level is best effort: when it does not land,
        # this machine plays at its own level with a line in the log saying so.
        if want is not None and not run(f"setvolume {alias} {want}", required=False):
            log.warning("this Windows audio path will not take a volume; playing "
                        "%s at the machine's own level rather than at %s", path.name, volume)
        run(f"play {alias} wait")
    finally:
        # close what was opened even when playing failed, or the alias and the file
        # handle are left behind on a machine that plays all day
        run(f"close {alias}", required=False)
