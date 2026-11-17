"""A web page for the running daemon: times, schedule, speakers, and the YAML.

This is deliberately not a management "platform". It is one page, served by the
daemon itself, that answers the four questions a setup session actually asks:
did I get the times right, what is going to fire and when, is this speaker
alive, and can I change my mind without opening an editor. The YAML stays the
source of truth - the page edits the file rather than a database, so everything
here is also what `muezzin times` and `muezzin next` would show you.

No auth: like the media server, it is a LAN tool and binds 0.0.0.0. Start it on
a trusted network, or with --read-only on a shared one. Writes are refused if a
browser sends them from another origin, which stops a page your family happens
to visit from editing the profile - it is a guard, not access control.
"""
from __future__ import annotations

import datetime as dt
import http.server
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import yaml

from . import __version__, calc, fileserve, geocode, hijri, localplay, net, yamledit
from .backends import KINDS, lead_for, scan_speakers
from .config import (AUDIO_SUFFIXES, STARTER_LATITUDE, STARTER_LONGITUDE, STARTER_TIMEZONE,
                     load_profile, uses_starter_location, valid_host)
from .page import PAGE
from .scheduler import PRAYER_KEYS, Runner, clock_hours, upcoming

log = logging.getLogger("muezzin.web")

# The page is for one household, and a port with no auth should not allocate
# whatever a client asks for, so an upload stops well short of a feature film.
MAX_UPLOAD = 64 * 1024 * 1024

# A profile is a few hundred lines of YAML, so anything bigger on the wire is not
# an edit. It also bounds what the parser is asked to hold; see the alias check
# below for why the size alone is not enough.
MAX_CONFIG_BYTES = 64 * 1024

# PyYAML expands an alias into a copy with no limit, so a couple of kilobytes of
# nested anchors is enough to reach a Pi's memory ceiling before the loader can
# object to anything. muezzin profiles do not use aliases - the comment-preserving
# editor would lose them anyway - so the shape is refused rather than parsed.
#
# An anchor or alias only counts where a value may start: after `key:`, after a
# list dash, or inside a flow list. That is what keeps an asterisk in somebody's
# comment, or in the name of a recording, from being mistaken for YAML syntax.
_VALUE_POSITION = r"(?:^[\t ]*[^:#\s][^:]*:[\t ]*|^[\t ]*-[\t ]+|\[[\t ]*|,[\t ]*)"
_ANCHOR_RE = re.compile(_VALUE_POSITION + r"&[\w-]", re.MULTILINE)
_ALIAS_RE = re.compile(_VALUE_POSITION + r"\*[\w-]", re.MULTILINE)


def _uses_aliases(text: str) -> bool:
    """Both halves of the shape that multiplies a document past its own size."""
    body = "\n".join(line.split(" #", 1)[0] for line in text.splitlines())
    return bool(_ANCHOR_RE.search(body)) and bool(_ALIAS_RE.search(body))


# What a recording has to begin with to be believed at all. The suffix is a hint
# the uploader chose; these bytes are what gets handed to a speaker.
_MAGIC = {b"fLaC": "flac", b"OggS": "ogg", b"ID3": "mp3"}


# What the panel writes into `method:` itself. Anything else in that block - an
# angle, an interval - belongs to the person who typed it, so the reply after a
# method change names those rather than letting a number go quietly.
_METHOD_OWN = ("preset", "asr_shadow", "adjustments")


def _sniff_audio(data: bytes) -> str | None:
    """Return the kind of audio the bytes look like, or None if they do not.

    Each test asks for the signature at the offset the format actually puts it
    at, which is not always 0: an mp4-family file starts with a length, and
    `ftyp` only appears at byte 4.
    """
    if data[4:8] == b"ftyp" or data[:4] == b"ftyp":
        return "m4a"                      # m4a, mp4, and most aac files
    if data[:4] == b"RIFF":
        return "wav" if data[8:12] == b"WAVE" else None
    for magic, kind in _MAGIC.items():
        if data[:len(magic)] == magic:
            return kind
    # an mp3 with no ID3 tag starts with a frame sync: 11 set bits
    if len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0:
        return "mp3"
    return None


# What to tell a browser a recording of each kind is. The file's suffix is what
# someone chose to call it; the header is what a decoder is actually being handed,
# so the header decides this - and a kind that is not here is one no browser in
# the house is likely to play, so the answer is a refusal with a reason in it.
CONTENT_TYPES = {"mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
                 "flac": "audio/flac", "m4a": "audio/mp4"}


def _slug(text: str) -> str:
    """An output name a human can read, from a device name."""
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in text.strip())
    return out.strip("-").replace("--", "-") or "output"


def _fmt(hours) -> str:
    """Decimal local hours -> 'HH:MM', keeping the day marker on times past
    midnight, because an isha at 00:24 is tomorrow and the page should say so."""
    if hours is None:
        return "--:--"
    day = ""
    if hours >= 24.0:
        day, hours = " +1", hours - 24.0
    elif hours < 0:
        day, hours = " -1", hours + 24.0
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        h, m = h + 1, 0
        if h == 24:                      # 23:59.6 rounds up into tomorrow, so mark it
            day = "" if day == " -1" else " +1"
    return f"{h % 24:02d}:{m:02d}{day}"


def _numbers(payload: dict) -> tuple[float, float]:
    """Latitude and longitude out of a request, or a reason why there are none.

    Bounded and rounded here, once, because these come from a browser and from a text
    box a person is typing into. A latitude of 91 is a slip of a finger, and letting it
    through would produce a timetable that looks normal for a place that does not exist.
    """
    try:
        latitude = float(payload["latitude"])
        longitude = float(payload["longitude"])
    except (KeyError, TypeError, ValueError):
        raise ValueError('give latitude and longitude as numbers, like "latitude": '
                         '42.1292, "longitude": -80.0851') from None
    if not (abs(latitude) <= 90.0 and abs(longitude) <= 180.0):
        raise ValueError("latitude runs -90 to 90 and longitude -180 to 180, north and "
                         "east being positive")
    return round(latitude, 6), round(longitude, 6)


def _lead_shown(seconds: float):
    """How early this speaker gets the recording, spelled the way a person reads it.

    Eight seconds is 8 on the page, not 8.0; a speaker that was told to start a
    third of a second early still gets its third.
    """
    value = float(seconds)
    return int(value) if value.is_integer() else round(value, 2)


class WebPanel:
    def __init__(self, runner: Runner, port: int = 8020, allow_edit: bool = True,
                 allow_hosts: tuple[str, ...] = ()):
        self.runner = runner
        self.port = port
        self.allow_edit = allow_edit
        # Extra names this page agrees to answer to, beyond localhost and the
        # address the media server is using. See serves_host for why the page
        # cares what name was typed at all.
        self.allow_hosts = tuple(str(h).strip() for h in allow_hosts if str(h).strip())
        self.lock = threading.RLock()   # config writes and speaker changes: one at a
                                        # time. Reentrant because a change reads the
                                        # file, edits the text, and hands it to save.
        self.saving = threading.Lock()  # one save, and one scratch file, at a time
        self.testing = threading.Lock()  # one test playback at a time
        self.scan_lock = threading.Lock()  # one speaker scan at a time
        self._scan = None                 # last scan_speakers() result, and when
        self.scan_at = None
        # Map squares: one ask out at a time, a beat apart. The browser sends the nine
        # squares of a view all at once and the public tile layer asks to be treated like
        # one person browsing, which means about one request a second. This is not
        # self.lock: a queue of pictures has nothing to do with a config write, and a
        # square held up behind a speaker scan should not hold up an edit either.
        self.tile_lock = threading.Lock()
        self.tile_spacing = geocode.TILE_SPACING
        self._tile_next = 0.0             # when the next square may be asked for
        self._httpd = None
        self._thread = None

    # ---- who is allowed to ask ---------------------------------------------

    @staticmethod
    def _bare(value) -> str:
        """An address with the brackets and port taken off: [::1]:8020 -> ::1."""
        value = str(value or "").strip().lower()
        if value.startswith("["):
            value = value[1:].split("]", 1)[0]
        elif value.count(":") == 1:
            value = value.split(":", 1)[0]
        return value.strip("[]")

    def host_names(self) -> set:
        """Every name a browser here could legitimately be asking for."""
        names = {"localhost", "127.0.0.1", "::1"}
        media = getattr(self.runner, "media", None)
        ip = getattr(media, "host_ip", None)
        if ip:
            names.add(str(ip))
        names.update(self.allow_hosts)
        return {self._bare(n) for n in names if str(n).strip()}

    def serves_host(self, header) -> bool:
        """Does the Host header name this machine, or somebody else's domain?

        This is the one defence against DNS rebinding, which is what a device
        with no password on a home network is most exposed to: a page at
        evil.com arranges for that name to resolve to 192.168.0.5, the browser
        loads our page from inside your network while still believing it is on
        evil.com, and its script reads the schedule, the speaker names and the
        latitude and longitude. Every origin check then passes, because as far as
        the browser is concerned it is all one site. The tell is the name in the
        request, which is not a name anyone in this house typed.
        """
        return self._bare(header) in self.host_names()

    @contextmanager
    def _editing(self):
        """Read the profile, change it, write it back: as one uninterruptible step.

        Without this, two people clicking on the same page at the same moment
        both read the same text, and whoever saves last quietly undoes the other
        one's change - the file would say one thing while both were told they had
        succeeded.
        """
        with self.lock:
            yield self._text()

    # ---- state -----------------------------------------------------------

    def notices(self) -> list[str]:
        """The two things that make a muezzin play nothing, said where a new
        install will actually read them.

        A fresh profile has no speakers in it, and its coordinates are the
        starter's placeholder for New York. Both are correct YAML and neither
        produces an error, so the page - which a new user opens before they ever
        see a log - has to be the one that says so.
        """
        p = self.runner.profile
        notes = []
        if uses_starter_location(p.location):
            notes.append(f"The location is still the starter's placeholder "
                         f"({STARTER_LATITUDE}, {STARTER_LONGITUDE}, {STARTER_TIMEZONE}), so "
                         f"every time on this page is New York's until you set it in the "
                         f"Where section below. A time zone labels the clock; the "
                         f"coordinates are what move the times. Checking numbers there "
                         f"asks nobody anything; finding a place by its words asks "
                         f"{geocode.provider()}, and only when you press find-it.")
        if not p.outputs:
            notes.append("No speakers are configured yet, so nothing can play: look again "
                         "below and use a speaker, or write an outputs entry in the profile.")
        elif not p.enabled_outputs():
            notes.append(f"All {len(p.outputs)} speakers in the profile are switched off, "
                         f"so nothing can play.")
        return notes

    def state(self) -> dict:
        p = self.runner.profile
        now = dt.datetime.now(dt.timezone.utc)
        local_now = now.astimezone(_zone(p.location.timezone))
        days = []
        for i in range(3):
            date = local_now.date() + dt.timedelta(days=i)
            times = calc.compute_times(p.location, date, p.params,
                                       asr_shadow=p.asr_shadow, adjustments=p.adjustments)
            # Read off the wall, not off the calculation's scale. The two are the same
            # number on an ordinary day and differ on the two days a year the zone moves
            # its own clock, and this row has to agree with the "next" list below, which
            # is built from the instants the speakers will actually sound at.
            hours = clock_hours(times, p.location.timezone)
            row = {"date": date.isoformat(),
                   "weekday": date.strftime("%a"),
                   "times": {k: _fmt(hours.get(k)) for k in PRAYER_KEYS}}
            row.update(hijri.day_info(date, p.hijri_offset))
            days.append(row)
        next_events = []
        for sev in upcoming(p, now, days=2):
            ev = sev.event
            next_events.append({"when": sev.when.strftime("%a %d %b %H:%M"),
                                "date": sev.when.date().isoformat(),
                                "name": ev.name,
                                "at": ev.at,
                                "offset_min": ev.offset_min,
                                "targets": [o.name for o in p.targets_for(ev)],
                                "media": ev.media,
                                # How many it will draw from the media folder when it
                                # fires. The drawing has no answer yet, so the page says
                                # that instead of leaving the cell blank.
                                "random": ev.random})
        text, mtime = "", None
        if p.path and Path(p.path).exists():
            # a config saved as cp1252 by a notepad must not take the whole page
            # down with it: replace the odd bytes so the times still render
            text = Path(p.path).read_text(encoding="utf-8", errors="replace")
            mtime = dt.datetime.fromtimestamp(Path(p.path).stat().st_mtime).isoformat(timespec="seconds")
        media_dir = Path(p.media_dir)
        # What is in the folder is asked of the profile, because that is the same
        # list an event drawing at random picks from and the same list the library
        # card shows. It was copied here once, which is how two answers to "what
        # recordings do we have" could have drifted apart.
        files = p.library()
        # The folder is the library, so the page needs to know what is in it beyond
        # the names. Which events point at a recording decides whether it can be
        # deleted at all - a name still in an event's playlist would fire into a
        # missing file at 5 am - and the hold list decides whether an event drawing
        # at random may pick it. The sizes are here because a 400 kB chime and a
        # 4 MB recitation are not the same thing to lose.
        named_by: dict[str, list[str]] = {}
        for ev in p.events:
            for item in ev.media:
                named_by.setdefault(item, []).append(ev.name)
        held = set(p.library_exclude)
        library = []
        for name in sorted(set(files) | held):
            try:
                size = (media_dir / name).stat().st_size
            except OSError:               # someone removed it from under us
                size = None
            library.append({"name": name, "bytes": size,
                            "excluded": name in held,
                            "named_by": named_by.get(name, []),
                            # held back by a name whose file is gone: it can be let
                            # go from here, but there is nothing to delete or play.
                            "missing": size is None})
        # Which preset the file names, read back from the file rather than
        # inferred from the numbers: a profile may set the angles by hand and
        # then the honest answer is that there is no preset in it.
        preset = yamledit.block_value(text, "method", "preset")
        return {
            "now": local_now.strftime("%Y-%m-%d %H:%M %Z"),
            "version": __version__,
            "today": hijri.day_info(local_now.date(), p.hijri_offset),
            "hijri_offset": p.hijri_offset,
            "attribution": p.attribution,
            # The position as the file holds it. Two decimals used to be sent here, on
            # the reasoning that an unauthenticated page on the LAN should not print the
            # house's exact address - but that page also serves the profile YAML, which
            # says it in full, and the Where boxes are filled from these two numbers, so
            # all the rounding achieved was that pressing write-it without touching them
            # moved the position by up to a kilometre. The header line shortens them
            # where shortening is what is wanted, and nothing else has to lose digits.
            "location": {"latitude": round(p.location.latitude, 6),
                         "longitude": round(p.location.longitude, 6),
                         "timezone": p.location.timezone, "elevation_m": p.location.elevation_m},
            # What the page may show that other people made, and who made it. off means
            # no map appears and no tile request leaves the house at all.
            "map_tiles": p.map_tiles,
            "map_credit": geocode.MAP_CREDIT,
            # Named on the page before any asking happens, so a person knows whose door
            # they are about to knock on.
            "geocoder": geocode.provider(),
            "method": {"label": p.params.label, "preset": preset,
                       "jafari": p.params.midnight_from_fajr,
                       "fajr_angle": p.params.fajr_angle,
                       "isha_angle": p.params.isha_angle,
                       "isha_interval": p.params.isha_interval,
                       "shurf_angle": p.params.shurf_angle,
                       "maghrib_angle_offset": p.params.maghrib_angle_offset,
                       # The header prints this beside the word midnight, so the pair
                       # reads "solar midnight" or "jafari midnight" and says which
                       # night the file is using without a sentence about it.
                       "midnight": "jafari" if p.params.midnight_from_fajr else "solar",
                       "asr": "hanafi" if p.asr_shadow == 2.0 else "standard",
                       "high_latitude_rule": p.params.high_latitude_rule},
            # what the file pins that a preset name would otherwise decide, so the
            # panel can say so instead of implying a dropdown did something it did not.
            "overridden": [f for f in yamledit.block_fields(text, "method")
                           if f not in _METHOD_OWN],
            "adjustments": {k: v for k, v in vars(p.adjustments).items() if v},
            "config_path": str(p.path) if p.path else None,
            "config_mtime": mtime,
            "config_text": text,
            "read_only": not self.allow_edit,
            "media_dir": str(media_dir),
            "media_files": files,
            "media_library": library,
            "media_url": (f"http://{self.runner.media.host_ip}:{self.runner.media.port}/"
                          if self.runner.media else None),
            "days": days,
            "upcoming": next_events,
            "events": [{"name": e.name, "at": e.at, "offset_min": e.offset_min,
                        "media": e.media, "random": e.random,
                        "targets": e.targets, "volume": e.volume,
                        "days": e.days} for e in p.events],
            # the picker's choices, from the same table `muezzin methods` prints. The
            # flag is the engine's own: which midnight a method solves for. The page
            # groups on it, so it cannot drift out of step with the numbers.
            "presets": [{"name": key, "label": value.label,
                         "jafari": value.midnight_from_fajr}
                        for key, value in sorted(calc.PRESETS.items())],
            "prayers": list(PRAYER_KEYS),
            "scan_at": self.scan_at,
            # what the page should say out loud before anything else: an empty
            # profile is a valid profile, and a silent one
            "notices": self.notices(),
            "max_upload": MAX_UPLOAD,
            "outputs": [{"name": o.name, "kind": o.kind, "target": o.target, "host": o.host,
                         "port": o.port, "volume": o.volume, "enabled": o.enabled,
                         # which kinds may be asked for a level at all: the answer comes
                         # from the backend class, so the page cannot offer a slider for a
                         # computer whose level belongs to the person using it
                         "takes_volume": bool(getattr(KINDS.get(o.kind), "takes_volume", False)),
                         # ... and what the LAN said that particular target is, because a
                         # speaker group is not a speaker: it is several of them, each at
                         # whatever level the Google Home app left them at, and nobody
                         # outside that app moves them together. "" means the last scan did
                         # not see the name, which the page says as itself.
                         "target_kind": (self.cast_target_kind(str(o.target or ""))
                                         if o.kind == "google_cast" else ""),
                         # how early this speaker gets handed the recording, so the
                         # first note is in the air when the printed time arrives
                         "lead": _lead_shown(lead_for(o))}
                        for o in p.outputs],
        }

    # ---- actions the page can take ---------------------------------------

    def toggle_output(self, name: str, enabled: bool) -> dict:
        with self.lock:
            self.runner.set_enabled(name, enabled)
        log.info("output %s %s", name, "enabled" if enabled else "disabled")
        return {"name": name, "enabled": enabled}

    def _inside_media_dir(self, media: list[str]) -> None:
        """The page may pick any file the daemon is willing to play, which is
        media_dir and nothing else. Without this a handcrafted request could ask
        the daemon to read - and for a `file` output to copy - any path it can see."""
        root = Path(self.runner.profile.media_dir).resolve()
        for item in media:
            p = Path(item)
            full = (p if p.is_absolute() else root / p).resolve()
            if not full.is_relative_to(root):
                raise ValueError(f"{item} is outside media_dir ({root}); "
                                 f"put the file there and pick it from the list")

    def test_play(self, name: str, media: list[str]) -> dict:
        if not media:
            raise ValueError("no media file chosen")
        self._inside_media_dir(media)
        if not self.testing.acquire(blocking=False):
            raise RuntimeError("a test is still playing; wait for it to finish")
        try:
            # deliberately not self.lock: a Cast file can take minutes, and a
            # toggle or an edit must not queue behind it. Runner serialises the
            # speakers itself, so a test cannot talk over an adhan that is due.
            self.runner.play_now(name, media)
        except localplay.Stopped:
            # The page pressed Stop, so this is the answer it wants rather than a red
            # line about a speaker that broke: the test ended, and it ended because it
            # was asked to.
            return {"played": media, "output": name, "stopped": True}
        finally:
            self.testing.release()
        return {"played": media, "output": name}

    def stop_test(self, payload: dict) -> dict:
        """End what one output is playing right now.

        A test is a recording about to come out of a real speaker in a house, so the
        page has to be able to call it back: someone pressed test on the wrong
        recitation, or a speaker is holding a stream that will not end. The ask goes to
        the output rather than to the thread that started the test, because that thread
        is sitting inside the speaker until the file finishes - which is exactly why a
        test could otherwise not be interrupted at all.

        Nothing here touches the schedule or the profile: the next adhan is still coming
        at its time, and a speaker that was asked to be quiet stays enabled. An output
        that was not playing anything answers with an empty list, which is the reply to
        the question that was asked.
        """
        name = str(payload.get("output") or "").strip()
        if not name:
            raise _Status(400, "which output should stop? one of the names in the Outputs table")
        try:
            stopped = self.runner.stop_playing(name)
        except ValueError as exc:
            raise _Status(404, str(exc)) from None
        log.info("stop asked for %s: %s", name, ", ".join(stopped) or "nothing was playing")
        return {"stopped": stopped, "output": name}

    def save_config(self, text: str) -> dict:
        """Validate before writing: load_profile rejects a typo that would
        otherwise only be heard as silence at 5 am, so a bad edit can never be
        saved into the file the daemon reads."""
        path = Path(self.runner.profile.path or "")
        if not path:
            raise ValueError("this profile has no file path to write back to")
        data = text.encode("utf-8")
        if len(data) > MAX_CONFIG_BYTES:
            raise ValueError(f"that is {len(data)} bytes of profile text, and a household "
                             f"schedule is not more than {MAX_CONFIG_BYTES} bytes")
        if _uses_aliases(text):
            # Anchors and aliases are ordinary YAML and muezzin reads them fine
            # when you put them in the file yourself; what the page refuses is to
            # feed a document full of them to the parser over a network port,
            # because PyYAML expands them without any limit while it reads.
            raise ValueError("the page will not save YAML that uses aliases (*name); "
                             "write the values out, or edit the file and press reload")
        # The lock is taken first and held across the whole change, so this is the
        # only door through which the file moves.
        with self.lock, self.saving:
            if path.exists() and b"\r\n" in path.read_bytes():
                # A browser sends LF. A profile that already uses CRLF - the
                # usual thing when it is checked out on Windows - keeps its line
                # endings, so renaming a speaker is one changed line in git
                # instead of the whole file.
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            fd, name = tempfile.mkstemp(dir=str(path.parent or "."),
                                        prefix=path.name + ".", suffix=".webtmp")
            tmp = Path(name)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)                          # no newline translation
                try:
                    load_profile(tmp)
                except (KeyError, ValueError, TypeError, yaml.YAMLError) as exc:
                    # name the file the person is editing, not our scratch copy.
                    # A YAML parse error says '<unicode string>', which tells them
                    # nothing about which of their own files to go and fix.
                    message = str(exc).replace(str(tmp), str(path))
                    raise ValueError(message.replace("<unicode string>", path.name)) from None
                if path.exists():
                    shutil.copymode(str(path), str(tmp))   # keep the file's modes
                # replace(), not write_text(): a crash or a full disk mid-write
                # must leave the old profile intact, not a half-written YAML
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)             # already gone if the move won
            # re-read from the real path, not the scratch copy we validated: the
            # daemon must end up running exactly what is on disk, with the right
            # path on it (the page reads that file back to show you the editor).
            self.runner.reload(load_profile(path))
            new = self.runner.profile
        log.info("profile reloaded from %s (%d outputs, %d events)", path,
                 len(new.outputs), len(new.events))
        return {"saved": str(path), "outputs": len(new.outputs), "events": len(new.events)}

    def reload(self) -> dict:
        path = self.runner.profile.path
        if not path:
            raise ValueError("this profile has no file path to reload")
        with self.lock:
            self.runner.reload(load_profile(path))
        return {"reloaded": str(path)}

    # ---- writing the profile from a button ---------------------------------
    #
    # Everything below builds new text and hands it to save_config, which is the
    # one door to the file: it runs the real loader over the result, refuses the
    # write if the loader is unhappy, and reloads the daemon. So a button can only
    # ever leave behind a profile that `muezzin times` would accept. And because
    # yamledit moves lines instead of re-rendering the document, the comments that
    # document the profile - the reason it is readable at all - survive the click.

    def _text(self) -> str:
        path = Path(self.runner.profile.path or "")
        if not path.exists():
            raise ValueError("this profile has no file to write back to")
        return path.read_text(encoding="utf-8", errors="replace")

    def _local_today(self) -> dt.date:
        now = dt.datetime.now(dt.timezone.utc)
        return now.astimezone(_zone(self.runner.profile.location.timezone)).date()

    def set_method(self, payload: dict) -> dict:
        """Change which table the times come from.

        Only preset and asr_shadow are written here. An angle the person set by
        hand stays set - it is what they asked for when they typed it, and
        quietly deleting a number would be worse than a stale one - so the reply
        says which knobs are still in force and the page repeats it.
        """
        preset = str(payload.get("preset") or "").strip().lower()
        if preset not in calc.PRESETS:
            raise ValueError(f"no method called {preset!r}; the page offers "
                             f"{', '.join(sorted(calc.PRESETS))}")
        edits = {"preset": preset}
        shadow = str(payload.get("asr_shadow") or "").strip().lower()
        if shadow:
            if shadow not in ("standard", "hanafi"):
                raise ValueError("asr_shadow is either standard or hanafi")
            edits["asr_shadow"] = shadow
        with self._editing() as before:
            still = [f for f in yamledit.block_fields(before, "method") if f not in _METHOD_OWN]
            saved = self.save_config(yamledit.set_in_block(before, "method", edits))

        params = self.runner.profile.params
        saved["method"] = params.label
        saved["asr"] = "hanafi" if self.runner.profile.asr_shadow == 2.0 else "standard"
        if still:
            saved["still_overridden"] = still
        return saved

    def set_hijri_offset(self, days) -> dict:
        """Nudge the tabular Hijri date. The calendar is arithmetic, the moon is
        not, so this is the one knob that lets a person agree with their own
        community about what today is called."""
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise ValueError("the offset has to be a whole number of days")
        if not -3 <= days <= 3:
            raise ValueError("keep the offset between -3 and +3 days; further than that "
                             "means the calendar you follow is not this one")
        with self._editing() as text:
            saved = self.save_config(yamledit.set_scalar(text, "hijri_offset", days))
        saved["hijri_offset"] = days
        saved["today"] = hijri.day_info(self._local_today(), days)
        return saved

    def near(self, payload: dict) -> dict:
        """What a set of numbers means, worked out from the table this program carries.

        No request leaves the machine. A person checking that they typed the right
        coordinates should not have to ask a stranger whether the numbers look right, and
        should be able to check when the internet is out.
        """
        latitude, longitude = _numbers(payload)
        near = geocode.nearest_named(latitude, longitude, 4)
        answer = {"latitude": latitude, "longitude": longitude, "near": near}
        if near and near[0]["km"] <= geocode.ZONE_NEAR_KM:
            answer["timezone"] = near[0]["timezone"]
            answer["zone_note"] = (f"the clock would be {near[0]['name']}'s, "
                                   f"{near[0]['km']:g} km away")
        else:
            answer["zone_note"] = ("no city muezzin knows is near enough to lend its "
                                   "clock: use find-it, or write the timezone line "
                                   "yourself")
        if near and near[0]["km"] > geocode.FAR_KM:
            answer["far_note"] = (f"that is {near[0]['km']:,.0f} km from "
                                  f"{near[0]['name']}, the nearest city in the table. If "
                                  "you did not mean somewhere that remote, a number has "
                                  "been transposed or copied from the wrong place.")
        return answer

    def find(self, payload: dict) -> dict:
        """Ask the lookup - the one request in this program that leaves the network.

        The page reaches here only from a button someone presses, and the button says who
        will be asked first. What was typed is not stored, not logged, and not quoted back
        if the answer is bad.
        """
        text = str(payload.get("q") or "").strip()
        postcode = str(payload.get("postcode") or "").strip()
        if text or postcode:
            hits = geocode.search(text, postcode)
        elif payload.get("latitude") is not None:
            latitude, longitude = _numbers(payload)
            hits = geocode.reverse(latitude, longitude)
        else:
            raise ValueError("type a street or a postal code, or give latitude and "
                             "longitude")
        # An empty answer is the only case an offer is worth making. Measured on the public
        # lookup: a line that already answers is beaten by the shorter one - "1600
        # pennsylvania ave nw washington dc" answers with the White House, while the same
        # words without the town answer with two avenues in Florida and Texas. So the offer
        # appears when the town is the thing that stopped the answer, and not otherwise.
        again = "" if (hits or not text) else (geocode.shorter(text) or "")
        return {"provider": geocode.provider(), "credit": geocode.MAP_CREDIT,
                "try_again": again,
                "hits": [{"label": hit.label, "latitude": hit.latitude,
                          "longitude": hit.longitude, "timezone": hit.timezone,
                          "note": hit.zone_note} for hit in hits]}

    def set_location(self, payload: dict) -> dict:
        """Write the three location lines, once each of them is known to mean something.

        The coordinates move the times and the time zone only names the clock they land
        on, so all three are checked before anything is written. A zone name this machine
        does not have is not a slightly wrong guess but a profile that will not load, and
        finding that out at the next restart is the worst time to learn it.
        """
        latitude, longitude = _numbers(payload)
        zone = str(payload.get("timezone") or "").strip()
        if not zone:
            raise ValueError("the coordinates need a time zone with them: they decide "
                             "where in the day those times land on the clock")
        if not geocode.zone_known(zone):
            raise ValueError(f"this machine does not know a time zone called {zone!r}, so "
                             "the profile would not load. Use the exact name your area "
                             "uses, like America/New_York")
        with self._editing() as text:
            saved = self.save_config(yamledit.set_in_block(text, "location", {
                "latitude": latitude, "longitude": longitude, "timezone": zone}))
        location = self.runner.profile.location
        # Full precision, the same shape /api/state sends: one shape for a location
        # across this API, so nothing that fills a box from a reply has to know which
        # digits that reply threw away.
        saved["location"] = {"latitude": round(location.latitude, 6),
                             "longitude": round(location.longitude, 6),
                             "timezone": location.timezone}
        saved["notices"] = self.notices()
        log.info("location set to %.6f, %.6f (%s)", location.latitude, location.longitude,
                 location.timezone)
        return saved

    def _tile_dir(self) -> Path:
        """Where the map squares are kept, next to the profile that asked for them."""
        profile = self.runner.profile
        base = profile.path.parent if profile.path else Path(profile.media_dir)
        return base / "muezzin-tiles"

    def tile(self, zoom, x, y) -> bytes:
        """One square of the map, for a profile that asked for a map.

        The daemon fetches it rather than the browser, for three reasons: a LAN page then
        never makes somebody's phone reach the internet on its own; the request carries
        the name of this program, which is what the tile users' policy asks of an
        application instead of a browser's default string; and each square is fetched once
        for the house instead of once per screen. What comes back is checked to be a
        picture before this origin serves it, so an error page or a hijacked answer does
        not arrive at the browser looking like it came from here.

        The asks go out one at a time, a beat apart: a view of the page is nine squares
        and a browser sends all nine at once, while the public layer asks to be treated
        like a person browsing; and a square that never came, refused or answered by a
        server too busy to answer, is a 502 with a reason in it, which the page marks as
        a square that is missing rather than as a pale patch of ground. Nothing is done
        here about how big a square ought to be, because measuring it says not to: the
        square of lake west of Erie is 103 bytes at zoom 12 and the one beside it, with
        a shoreline in it, is 4,687, so a small picture is not evidence of anything.
        """
        if self.runner.profile.map_tiles != "osm":
            raise _Status(403, "this profile keeps the map off: map_tiles: off. Put "
                               "map_tiles: osm there and the daemon will fetch the squares "
                               "itself, and say whose map they are")
        try:
            zoom, x, y = int(zoom), int(x), int(y)
        except (TypeError, ValueError):
            raise _Status(400, "the map wants whole numbers for zoom and square") from None
        try:
            geocode.tile_url(zoom, x, y)      # checked before anything is asked for
        except geocode.TileMissing as exc:
            # A square that does not exist is the page's mistake, not the map server's
            # silence, and the two deserve different statuses.
            raise _Status(400, str(exc)) from None
        try:
            target = self._tile_dir() / str(zoom) / f"{x}-{y}.png"
            if target.is_file():
                return target.read_bytes()
        except OSError:
            pass                              # a cache that will not read is not fatal
        with self.tile_lock:
            wait = self._tile_next - time.monotonic()
            if wait > 0:
                time.sleep(wait)             # the others in this view wait their turn
            self._tile_next = time.monotonic() + self.tile_spacing
            try:
                body = geocode.fetch_tile(zoom, x, y)
            except geocode.GeocodeError as exc:
                raise _Status(502, str(exc)) from None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            scratch = target.with_name(f"{x}-{y}.writing")
            scratch.write_bytes(body)
            os.replace(scratch, target)       # never a half-written square on disk
        except OSError as exc:
            # The map is a courtesy; a read-only volume or a full disk should not cost
            # anyone the picture they asked for right now.
            log.info("the map square was not kept: %s", exc)
        return body

    def _event_row(self, rows: list[dict], at: str, friday: bool) -> Optional[dict]:
        """The event entry that owns this prayer time.

        Day-scope is part of the identity, not an attribute of it: a Friday dhuhr
        and an everyday dhuhr are two different entries, and the everyday one is
        the one with no `days:` at all. Getting this wrong would write a Friday
        clip into the daily adhan.
        """
        for row in rows:
            if yamledit.entry_scalar(row, "at") != at:
                continue
            days = yamledit.entry_list(row, "days")
            in_friday = bool(days and any(d.lower().startswith("fri") for d in days))
            if in_friday == friday:
                return row
        return None

    def set_audio(self, payload: dict) -> dict:
        """Which clip plays for which prayer, including a Friday-only variant.

        Empty `media` removes the entry rather than writing an entry with nothing
        to play: the loader rejects an event with no media, so "no clip" and "an
        event with no files" are not the same statement.
        """
        at = str(payload.get("at") or "").strip().lower()
        if at not in PRAYER_KEYS:
            raise ValueError(f"{at or 'nothing'} is not one of {', '.join(PRAYER_KEYS)}")
        friday = bool(payload.get("friday"))
        media = [str(m) for m in (payload.get("media") or [])]
        for item in media:
            if Path(item).suffix.lower() not in AUDIO_SUFFIXES:
                raise ValueError(f"{item} is not audio this daemon can play "
                                 f"({', '.join(sorted(AUDIO_SUFFIXES))})")
        self._inside_media_dir(media)
        with self._editing() as text:
            row = self._event_row(yamledit.entries(text, "events"), at, friday)
            if not media:
                if row is None:
                    return {"at": at, "friday": friday, "unchanged": True}
                saved = self.save_config(yamledit.delete_entry(text, "events", row["index"]))
                saved["removed_event"] = row["name"]
                return saved
            fields: dict = {"media": media}
            for knob in ("offset_min", "volume"):
                if payload.get(knob) not in (None, ""):
                    fields[knob] = float(payload[knob]) if knob == "volume" else int(payload[knob])
            if payload.get("targets"):
                fields["targets"] = [str(t) for t in payload["targets"]]
            if row is None:
                name = f"{at}-friday" if friday else f"{at}-adhan"
                new = yamledit.append_entry(text, "events",
                                            {"name": name, "at": at}
                                            | ({"days": ["fri"]} if friday else {})
                                            | fields,
                                            comment=("Friday only: the Jumu'ah slot, or a "
                                                     "different adhan for Fridays"
                                                     if friday else None))
                saved = self.save_config(new)
                saved["added_event"] = name
            else:
                saved = self.save_config(yamledit.edit_entry(text, "events", row["index"], fields))
                saved["updated_event"] = row["name"]
        saved["at"] = at
        saved["friday"] = friday
        return saved

    # ---- working on the folder of recordings --------------------------------
    #
    # `media_dir` is the whole library: there is no second list of recordings kept in
    # step with it, which is why everything below writes the profile instead of a
    # database. Holding a recording out of the random drawing and putting one at the
    # end of a playlist are profile edits, so they go through the same door the clip
    # picker uses and a refusal from the loader stops the write. Deleting one is the
    # only call here that touches the disk, and the only edit in this app with no undo.

    def _recording_name(self, payload: dict) -> str:
        """One plain file name, as the folder lists it, with nothing else in it."""
        plain = str(payload.get("name") or "").replace("\\", "/")
        if not plain or "/" in plain or plain.startswith("."):
            raise ValueError("needs a plain file name from the list, with no path in it")
        return plain

    def _recording_path(self, name: str) -> Path:
        """The file behind that name, if the folder really has it."""
        root = Path(self.runner.profile.media_dir).resolve()
        full = (root / name).resolve()
        if not full.is_relative_to(root) or not full.is_file():
            raise ValueError(f"there is no {name} in {root} to work on")
        return full

    def hold_recording(self, payload: dict) -> dict:
        """Keep a recording out of the random drawings, or put it back in.

        A hold is not a deletion and not a mute: the file stays in the folder, and an
        event that names it in its playlist plays it whenever it is due. What changes
        is the drawing - the pick from the folder that happens when an event says
        `random: N` - which will not choose it. That is the whole reason the list
        exists: a household that has recordings it does not want heard unasked still
        wants them on hand for the prayer they choose themselves.
        """
        name = self._recording_name(payload)
        excluded = bool(payload.get("excluded"))
        with self._editing() as text:
            if excluded:
                # Nothing to hold back: the pool is the folder, so a name that is not
                # in it can never be drawn anyway. Letting it in would be a row in the
                # profile that means nothing and explains nothing.
                self._recording_path(name)
            held = [str(h) for h in (yamledit.block_list(text, "library", "exclude") or [])]
            wanted = sorted(set(held) | {name}) if excluded else [h for h in held if h != name]
            if wanted == held:
                return {"name": name, "excluded": excluded, "unchanged": True}
            if yamledit.find_block(text, "library") is None:
                text = yamledit.set_block(text, "library", [])
            saved = self.save_config(yamledit.set_in_block(text, "library", {"exclude": wanted}))
        saved["name"] = name
        saved["excluded"] = excluded
        saved["held_back"] = wanted
        return saved

    def delete_recording(self, payload: dict) -> dict:
        """Take a recording out of the folder for good.

        Because nothing undoes this, the guard sits in front of it: a recording an
        event still names would leave that event firing into a missing file, and being
        there at the right minute is the one thing this program is for. So the page is
        told to give those events something else first, in the words of the event that
        is in the way. If the file was held out of the drawings, its name leaves the
        hold list in the same breath - a name with no file behind it is a row that can
        never mean anything again, and it would outlive the recording it explained.
        """
        name = self._recording_name(payload)
        full = self._recording_path(name)
        keepers = [ev.name for ev in self.runner.profile.events if name in ev.media]
        if keepers:
            raise ValueError(f"{name} is what {', '.join(keepers)} still plays; give "
                             f"{'them' if len(keepers) > 1 else 'it'} something else "
                             f"first, or delete the event")
        with self._editing() as text:
            held = [str(h) for h in (yamledit.block_list(text, "library", "exclude") or [])]
            if name in held:
                self.save_config(yamledit.set_in_block(text, "library",
                                                       {"exclude": [h for h in held if h != name]}))
        try:
            full.unlink()
        except FileNotFoundError:
            raise ValueError(f"{name} is already gone from {full.parent}") from None
        log.info("deleted the recording %s from %s", name, full.parent)
        return {"deleted": name, "was_held_back": name in held}

    def insert_recording(self, payload: dict) -> dict:
        """Put a recording at the end of one event's playlist.

        The clip picker in the Sound card decides which recording a prayer starts
        with; this adds one after it, which is what "and then the dua as well" means.
        Named files play in the order they are written, so the end of the list is the
        end of what plays. An event that also draws at random keeps both: what it is
        given by name plays first, then the drawing.
        """
        name = self._recording_name(payload)
        event = str(payload.get("event") or "").strip()
        if not event:
            raise ValueError("which event should play it? pick one of the names in the list")
        self._recording_path(name)
        if Path(name).suffix.lower() not in AUDIO_SUFFIXES:
            raise ValueError(f"{name} is not audio this daemon can play "
                             f"({', '.join(sorted(AUDIO_SUFFIXES))})")
        with self._editing() as text:
            rows = yamledit.entries(text, "events")
            row = next((r for r in rows if r["name"] == event), None)
            if row is None:
                raise ValueError(f"no event called {event} in this profile")
            have = yamledit.entry_list(row, "media") or []
            if name in have:
                raise ValueError(f"{event} already plays {name}"
                                 + (f", after {have[0]}" if len(have) > 1 else ""))
            saved = self.save_config(yamledit.edit_entry(text, "events", row["index"],
                                                         {"media": have + [name]}))
        saved["event"] = event
        saved["name"] = name
        saved["playlist"] = have + [name]
        return saved

    def speakers(self, refresh: bool = False) -> dict:
        """What is on the network right now, groups unpacked into members.

        Cached because a scan is ten seconds of mDNS and four HTTPS round trips,
        and a page that rescans on every poll would spend its life scanning. The
        cache says when it was taken, so stale is visible rather than implied.

        A scan is a broadcast on the LAN, so two of them at once is waste, not
        speed: whoever asks second while one is already under way gets the last
        result with `scanning` set, rather than making the network do it twice.
        """
        busy = False
        if refresh or self._scan is None:
            if self.scan_lock.acquire(blocking=False):
                try:
                    self._scan = scan_speakers()
                except Exception as exc:                     # discovery is never fatal
                    log.exception("speaker scan failed")
                    raise RuntimeError(f"the speaker scan failed: {exc}") from exc
                finally:
                    self.scan_lock.release()
                self.scan_at = dt.datetime.now().strftime("%H:%M:%S")
            else:
                busy = True
        used = {}
        for out in self.runner.profile.outputs:
            if out.kind in ("google_cast", "lan_box"):
                used[str(out.target or out.host)] = out.name
        reply = {"found": self._scan or [], "seen_at": self.scan_at, "in_profile": used}
        if busy:
            reply["scanning"] = True
        return reply

    def cast_target_kind(self, target: str) -> str:
        """What the last speaker scan called a Cast target: "group", "speaker", or "".

        A group is not a speaker with more speakers behind it. Measured on a real
        LAN: ask a group for a level and its receiver replies with the speakers it
        leads and each of their levels, and not one of those numbers moves - the ask
        is accepted by a channel that has nothing to do with the four rooms. Nothing
        outside the Google Home app moves several speakers together, so a profile
        pointing at a group has no level for muezzin to write. The page has to know
        which of the two a `target:` names, or it offers a slider that writes a number
        nothing honours, which is worse than saying nothing.

        Answered from the cache, never with a scan of its own: this runs while
        building the state the page polls every few seconds, and one scan is ten
        seconds of broadcasts. "" means the last scan did not see that name, which is
        different news from being a group and keeps its own words on the page.
        """
        scan = self._scan or {}
        if any(r.get("name") == target for r in scan.get("groups", [])):
            return "group"
        if any(r.get("name") == target for r in scan.get("speakers", [])):
            return "speaker"
        return ""

    def warm_cast_scan(self) -> None:
        """Take the first speaker scan if this daemon has never taken one.

        Only for a question that cannot be answered without it, and only once:
        whether a target is a group decides whether a level can land at all, and
        finding that out is worth one scan the first time somebody asks. The answer
        then sits in the same cache the page's speaker card reads.
        """
        if self._scan is not None:
            return
        try:
            self.speakers()
        except Exception:                            # discovery is never fatal
            log.info("no speaker scan, so nobody can say whether a target is a group")

    def add_speaker(self, payload: dict) -> dict:
        """Point an output at a speaker the scan just saw.

        Playback re-resolves a Cast target by name every time it plays, so a
        speaker that was only switched on this afternoon needs no config change to
        be used; this is about telling muezzin you *want* that one.
        """
        target = str(payload.get("target") or "").strip()
        if not target:
            raise ValueError("which speaker?")
        with self._editing() as text:
            rows = yamledit.entries(text, "outputs")
            for row in rows:
                if (yamledit.entry_scalar(row, "target") or "").lower() == target.lower():
                    raise ValueError(f"{target} is already an output called {row['name']}")
            name = _slug(target)
            taken = {(yamledit.entry_scalar(r, "name") or "").lower() for r in rows}
            while name in taken:
                name = f"{name}-2"
            fields = {"name": name, "kind": "google_cast", "target": target}
            if payload.get("volume") not in (None, ""):
                fields["volume"] = float(payload["volume"])
            saved = self.save_config(yamledit.append_entry(
                text, "outputs", fields, comment=f"{target}, added from the panel's speaker scan"))
        saved["output"] = name
        return saved

    def add_box(self, payload: dict) -> dict:
        """Point an output at a box that advertises itself on the LAN."""
        host = str(payload.get("host") or "").strip()
        if not host:
            raise ValueError("which box?")
        if not valid_host(host):
            raise ValueError(f"{host!r} is not a plain hostname or IP address, and a box has "
                             "to be reached by one of those")
        # The scan reports what kind of box it found, and this writes what the
        # loader will read - so the two have to be checked against each other
        # here, not one here and one in the reply.
        kind = str(payload.get("kind") or "lan_box").strip().lower()
        if kind != "lan_box":
            raise ValueError(f"the panel adds boxes as lan_box, not {kind}")
        port = None
        if payload.get("port") not in (None, ""):
            try:
                port = int(payload["port"])
            except (TypeError, ValueError):
                raise ValueError("the box's port has to be a number")
            if not 0 < port < 65536:
                raise ValueError(f"{port} is not between 1 and 65535")
        name = _slug(str(payload.get("name") or host))
        with self._editing() as text:
            rows = yamledit.entries(text, "outputs")
            for row in rows:
                if (yamledit.entry_scalar(row, "host") or "") == host:
                    raise ValueError(f"{host} is already an output called {row['name']}")
            taken = {(yamledit.entry_scalar(r, "name") or "").lower() for r in rows}
            while name in taken:
                name = f"{name}-2"
            fields = {"name": name, "kind": "lan_box", "host": host}
            if port is not None:
                fields["port"] = port
            saved = self.save_config(yamledit.append_entry(
                text, "outputs", fields, comment=f"{name}, added from the panel's speaker scan"))
        saved["output"] = name
        return saved

    def remove_output(self, name: str) -> dict:
        """Delete an output, and say plainly which events that just orphaned.

        An event naming a target that no longer exists makes the whole profile
        unreadable - the loader refuses it, on purpose - so deleting the output
        and leaving the reference behind would take the daemon's schedule down.
        The reference is taken out in the same write, and the page reports it.
        """
        with self._editing() as text:
            rows = yamledit.entries(text, "outputs")
            row = next((r for r in rows if yamledit.entry_scalar(r, "name") == name), None)
            if row is None:
                raise ValueError(f"no output called {name} in this profile")
            orphaned = []
            for ev in yamledit.entries(text, "events"):
                targets = yamledit.entry_list(ev, "targets") or []
                if name not in targets:
                    continue
                left = [t for t in targets if t != name]
                if not left:
                    raise ValueError(f"{name} is the only speaker for the event "
                                     f"{ev['name']}; give that event another target first, "
                                     f"or delete the event")
                orphaned.append(ev["name"])
            for ev_name in orphaned:                      # indices are stable: no entry
                ev = next(r for r in yamledit.entries(text, "events") if r["name"] == ev_name)  # is added or removed
                targets = [t for t in (yamledit.entry_list(ev, "targets") or []) if t != name]
                text = yamledit.edit_entry(text, "events", ev["index"], {"targets": targets})
            saved = self.save_config(yamledit.delete_entry(text, "outputs", row["index"]))
        saved["removed_output"] = name
        saved["events_rewritten"] = orphaned
        return saved

    def rename_output(self, payload: dict) -> dict:
        """Give an output the name this house calls it by, without anyone opening a file.

        A name is not a label: it is what events point at. So one rename has to land in
        two places, the output's own `name:` and every event `targets:` list that names
        it. Changing only the first leaves an event naming a speaker that no longer
        exists, and the loader refuses such a profile - the schedule would go down for a
        word. This is the same trap as deleting an output, arrived at from the other
        side, so it is handled the same way: rewrite the references in the one write and
        tell the page which events moved.
        """
        old = str(payload.get("from") or "").strip()
        asked = str(payload.get("to") or "").strip()
        # The guard is on what was typed, not on the slug: _slug has a fallback name for
        # a word with no letters or digits in it, and silently renaming somebody's
        # speaker to `output` because their box was empty would be a surprise at Fajr.
        if not asked or not any(c.isalnum() for c in asked):
            raise ValueError("what should it be called? one word, like kitchen-box")
        new = _slug(asked)
        with self._editing() as text:
            rows = yamledit.entries(text, "outputs")
            row = next((r for r in rows if yamledit.entry_scalar(r, "name") == old), None)
            if row is None:
                raise ValueError(f"no output called {old} in this profile")
            taken = {(yamledit.entry_scalar(r, "name") or "").lower() for r in rows}
            if new.lower() in taken:
                raise ValueError(f"there is already an output called {new}")
            moved = [ev["name"] for ev in yamledit.entries(text, "events")
                     if old in (yamledit.entry_list(ev, "targets") or [])]
            for ev_name in moved:                          # indices stay put: nothing is
                ev = next(r for r in yamledit.entries(text, "events") if r["name"] == ev_name)
                targets = [new if t == old else t          # added or removed, so an
                           for t in (yamledit.entry_list(ev, "targets") or [])]
                text = yamledit.edit_entry(text, "events", ev["index"], {"targets": targets})
            saved = self.save_config(yamledit.edit_entry(text, "outputs", row["index"],
                                                         {"name": new}))
        saved["renamed"] = new
        saved["was_called"] = old
        saved["events_rewritten"] = moved
        return saved

    def set_output_volume(self, payload: dict) -> dict:
        """Ask one of our speakers for a level, and write that ask into the profile.

        The level a test comes out at was, until now, whatever the speaker or the
        computer sitting in front of it happened to be set to - so two households
        pressing **test** heard two different loudnesses and neither could say why.
        `volume:` is the profile's word for it and the backend already applies it to
        everything it plays through that output, a test included, so the page only has
        to write the number honestly:

        * only a kind of output whose `takes_volume` is true gets one. A computer's own
          level - the machine running muezzin, or the Pi in the attic - belongs to
          whoever is sitting at it, which is the same rule the preview on this page
          follows.
        * and only onto a target that has a level of its own. A speaker group is a name
          several speakers share: asked for a level its receiver answers with those
          speakers and their own levels, and none of them move, because nothing outside
          the Google Home app moves several speakers together. Writing the number anyway
          leaves a profile that looks configured and a room that is not.
        * `null` puts it back to not saying anything, which on a Cast device means
          "whatever it is at right now".
        * the number is checked here, not at 5 am: a `volume:` of 40 loads, and a Cast
          device clamps it to full scale, so the house gets a shout instead of the
          background level somebody meant.
        """
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("which output?")
        asked = payload.get("volume")
        if asked in (None, ""):
            level = None
        else:
            try:
                level = float(asked)
            except (TypeError, ValueError):
                raise ValueError(f"{asked!r} is not a level; it is a number between 0 and 1")
            if not 0.0 <= level <= 1.0:
                raise ValueError(f"{level} is not a level: a speaker level is a number "
                                 "between 0 and 1, like 0.6")
        # Whether this output's target is a group is a question about the network, and the
        # answer can cost a scan, so it is asked before the profile is locked: nobody else's
        # edit waits on a broadcast. The loaded profile is only read here, never written.
        prior = next((o for o in self.runner.profile.outputs if o.name == name), None)
        if prior is not None and prior.kind == "google_cast" and prior.target:
            self.warm_cast_scan()
        with self._editing() as text:
            rows = yamledit.entries(text, "outputs")
            row = next((r for r in rows if yamledit.entry_scalar(r, "name") == name), None)
            if row is None:
                raise ValueError(f"no output called {name} in this profile")
            kind = (yamledit.entry_scalar(row, "kind") or "").strip().lower()
            cls = KINDS.get(kind)
            if cls is None:
                raise ValueError(f"{name} says it is {kind}, which is not one of "
                                 f"{', '.join(sorted(KINDS))}")
            if not getattr(cls, "takes_volume", False):
                raise ValueError(f"{name} is {kind}: muezzin only asks a speaker it casts to "
                                 "for a level, and the level of a computer belongs to whoever "
                                 "is sitting at it")
            asked_of = (yamledit.entry_scalar(row, "target") or "").strip()
            if self.cast_target_kind(asked_of) == "group":
                raise ValueError(
                    f"{name} points at {asked_of!r}, which the network says is a speaker group, "
                    "not a speaker. A group has no level of its own to be asked for: asked, it "
                    "answers with the speakers in it and the levels the Google Home app left "
                    "them at, and none of those move. muezzin will not write a number nothing "
                    "honours - point this output at one speaker, or set the group's level there")
            saved = self.save_config(yamledit.edit_entry(text, "outputs", row["index"],
                                                         {"volume": level}))
        saved["output"] = name
        saved["volume"] = level
        return saved

    def save_upload(self, filename: str, data: bytes) -> dict:
        """Put a recording in media_dir, if it really is a recording.

        The suffix is what the uploader decided to call it; the first few bytes are
        what a speaker would be handed, so a file called adhan.mp3 that is really
        something else is refused here rather than at 5 am. It never overwrites:
        silently replacing the clip someone is already playing is not a reply a
        person can recover from, so a clash is an error and a new name is the fix.
        """
        root = Path(self.runner.profile.media_dir)
        name = Path(str(filename).replace("\\", "/")).name
        if not name or name != str(filename).replace("\\", "/"):
            raise ValueError("needs a plain file name, with no path in it")
        if name.startswith(".") or len(name) > 120:
            raise ValueError(f"{name} is not a name this will accept")
        suffix = Path(name).suffix.lower()
        if suffix not in AUDIO_SUFFIXES:
            raise ValueError(f"{name} is not one of {', '.join(sorted(AUDIO_SUFFIXES))}")
        if not data:
            raise ValueError(f"{name} is empty")
        kind = _sniff_audio(data)
        expected = {".mp3": "mp3", ".wav": "wav", ".ogg": "ogg", ".oga": "ogg",
                    ".opus": "ogg", ".flac": "flac", ".m4a": "m4a", ".aac": "m4a"}[suffix]
        if kind != expected:
            raise ValueError(f"{name} looks like {kind or 'not audio'} by its header, "
                             f"which is not the {expected} the name claims")
        root.mkdir(parents=True, exist_ok=True)
        dest = root / name
        try:
            with open(dest, "xb") as fh:      # exclusive: never overwrite
                fh.write(data)
        except FileExistsError:
            raise ValueError(f"{name} is already in {root}; pick it from the list, "
                             f"or upload it under a different name") from None
        log.info("uploaded %s (%d bytes) to %s", name, len(data), root)
        saved = {"uploaded": name, "bytes": len(data), "kind": kind}
        if self.runner.media:
            # the absolute path, because url_for resolves a bare name against the
            # working directory and would then refuse a file it just wrote
            saved["url"] = self.runner.media.url_for(dest)
        return saved

    def clip(self, name: str) -> tuple[Path, str]:
        """Which recording the browser should fetch for itself, and as what type.

        This is the preview: someone collecting recordings wants to know what one
        sounds like before assigning it to a prayer, so the page asks for the bytes
        and the sound comes out of the machine the page is open on. Nothing is sent
        to a speaker, and no machine's level is touched - the page has no volume
        control, because the level on a computer belongs to whoever is in front of
        it. That is also why this is a read and not a write: a guest should be able
        to hear the library on a read-only panel.

        Only a plain file name from `media_dir` answers. The header decides the
        type, so a file called adhan.mp3 that is really something else is served as
        what it is, or refused if the header is not audio at all.
        """
        plain = str(name).replace("\\", "/")
        if "/" in plain or not plain or plain.startswith("."):
            raise _Status(400, "needs a plain file name from the list, with no path in it")
        root = Path(self.runner.profile.media_dir).resolve()
        full = (root / plain).resolve()
        if not full.is_relative_to(root) or not full.is_file():
            raise _Status(404, f"{plain} is not one of the recordings in media_dir")
        with open(full, "rb") as handle:
            head = handle.read(12)
        kind = _sniff_audio(head)
        if kind not in CONTENT_TYPES:
            raise _Status(415, f"{plain} does not look like audio by its first bytes, so "
                               f"this browser would only fail at it")
        return full, CONTENT_TYPES[kind]

    # ---- serving ---------------------------------------------------------

    def start(self) -> None:
        # BaseHTTPRequestHandler's constructor takes only (request, address, server),
        # so the panel reaches the handler as a class attribute, not a kwarg.
        class Bound(_Handler):
            panel = self

        # LANServer rather than the standard library's class: see net.py.
        self._httpd = net.LANServer(("0.0.0.0", self.port), Bound)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="muezzin-web", daemon=True)
        self._thread.start()
        log.info("web panel at http://%s:%s", self.runner.media.host_ip if self.runner.media
                 else "127.0.0.1", self.port)

    def serve_forever(self) -> None:
        if not self._httpd:
            self.start()
        self._thread.join()

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


def _zone(name: str):
    from zoneinfo import ZoneInfo
    return ZoneInfo(name)


class _Status(Exception):
    """An error that knows which HTTP status the page should see."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class _Handler(http.server.BaseHTTPRequestHandler):
    panel: WebPanel
    server_version = "muezzin"
    MAX_BODY = 256 * 1024
    _sent = False                 # at most one response per connection
    # One browser tab left open on a flaky wifi should not tie up a thread for
    # the rest of the day; if no bytes arrive for this long, the connection dies.
    timeout = 30

    def log_message(self, fmt, *args):
        log.debug("web http: " + fmt, *args)

    # helpers
    def _json(self, obj, status=200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self._sent = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _write(self, content: bytes, content_type: str, status=200) -> None:
        self._sent = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _send_file(self, path: Path, content_type: str) -> None:
        """A recording, copied through in pieces rather than read into memory: a
        whole recitation runs to a hundred megabytes, and a browser previewing one
        should not need this process to hold all of it at once.

        The byte range the client asked for is honoured. That is what lets the
        page's slider jump to the middle of a clip: a browser only offers to seek in
        something it can ask part of, and a server that always answers from byte
        zero leaves the sound where it started with no word about why. An
        unsatisfiable ask is a 416 with the file's real length in it, because a
        client with the wrong idea about a file should be told, not quietly given
        the whole thing.
        """
        try:
            span = fileserve.plan(self.headers.get("Range"), path.stat().st_size)
        except fileserve.BadRange as exc:
            # Answered here rather than raised as an error, because the answer needs
            # the file's length in it and the generic error path has no idea what
            # length to name.
            self._sent = True
            fileserve.refuse(self, path.stat().st_size, str(exc))
            return
        self._sent = True
        fileserve.deliver(self, path, content_type, span, cache="no-store")

    def _fail(self, status: int, message: str) -> None:
        """Report an error - but never a second time on one connection, which is
        how a browser ends up parsing a status line out of the middle of a
        response and seeing nonsense."""
        if self._sent:
            return
        try:
            self._json({"error": message}, status)
        except Exception:
            self.close_connection = True

    def _host_ok(self) -> bool:
        """Is the name in the Host header a name this machine was asked for by?

        See WebPanel.serves_host: this is the check that stops somebody else's
        website from resolving its own domain to this LAN address and then
        reading the page - and the API behind it - as if it were its own.
        """
        return self.panel.serves_host(self.headers.get("Host"))

    def _same_origin(self) -> bool:
        """A browser always sends Origin on a POST, so a write from some other
        page - a form on a site someone in the house is visiting - is refused
        here. curl has no Origin and stays allowed; this is a guard for browsers,
        not access control."""
        if (self.headers.get("Sec-Fetch-Site") or "").lower() in ("cross-site", "cross-origin"):
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        if origin == "null":            # a sandboxed or opaque-origin page
            return False
        return urlparse(origin).netloc.lower() == (self.headers.get("Host") or "").lower()

    def _body(self) -> dict:
        if self.headers.get("Transfer-Encoding"):
            # Not implemented on purpose. This handler speaks HTTP/1.0, and a
            # chunked body read as though it were not chunked ends the request
            # early and leaves the rest of it to be parsed as the next one.
            raise _Status(501, "this page speaks HTTP/1.0 with Content-Length only")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise _Status(400, "Content-Length has to be a number")
        if length < 0:
            raise _Status(400, "Content-Length cannot be negative")
        if length > self.MAX_BODY:
            # an unauthenticated port should not allocate whatever a client asks for
            self._discard(length, self.MAX_BODY)
            raise _Status(413, f"a {length} byte body is more than this page needs")
        if length == 0:
            return {}
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise _Status(400, f"expected Content-Type: application/json, got {ctype or 'nothing'}")
        data = self.rfile.read(length)
        if len(data) != length:
            self.close_connection = True    # the rest of this socket is unknowable
            raise _Status(400, "the request body was cut short")
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"expected a JSON body: {exc}")
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object, like {}")
        return payload

    def _discard(self, length: int, cap: int) -> None:
        """Read and throw away a body this handler has already refused.

        A client that is still writing when the socket closes takes a reset rather
        than the reply, and the browser then shows "network error" where the truth
        was "that file is too big". Draining up to the limit we just enforced costs
        bandwidth on a request that was failing anyway, and buys back the sentence
        that explains it.
        """
        remaining = min(length, cap)
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
        self.close_connection = True     # whatever follows is not ours to parse

    def _raw(self, limit: int) -> bytes:
        """A body that is the file itself, not JSON wearing a filename."""
        if self.headers.get("Transfer-Encoding"):
            raise _Status(501, "an upload needs Content-Length; this page does not read "
                               "chunked bodies")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise _Status(400, "Content-Length has to be a number")
        if length <= 0:
            raise _Status(400, "an upload needs the file in the body")
        if length > limit:
            self._discard(length, limit)
            raise _Status(413, f"{length} bytes is more than the {limit} byte limit "
                               f"for a recording")
        data = self.rfile.read(length)
        if len(data) != length:
            self.close_connection = True    # the rest of this socket is unknowable
            raise _Status(400, "the upload was cut short")
        return data

    def _drain(self, cap: int) -> None:
        """Throw away a body this handler has already refused.

        Refusing without reading leaves the bytes on the socket, and the next
        request on that connection - which a browser sends without waiting to be
        asked - then starts in the middle of the last one's file.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            return
        if self.headers.get("Transfer-Encoding"):
            # A chunked body has no declared size, so there is nothing safe to
            # count out and throw away. Close instead of guessing where it ends.
            self.close_connection = True
            return
        if length > 0:
            self._discard(length, cap)

    # routes
    def do_GET(self) -> None:
        try:
            if not self._host_ok():
                self._json({"error": "this page answers to its own address, not to the name "
                                     "in that request"}, 403)
                return
            if self.path in ("/", "/index.html"):
                self._write(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._json(self.panel.state())
            elif self.path.startswith("/api/speakers"):
                # ?refresh=1 rescans; without it the page gets the last scan and
                # is told when that was, so "cached" is visible instead of implied.
                # The key is matched exactly, because a query that merely happens
                # to contain the word somewhere else must not trigger a broadcast.
                wanted = (parse_qs(urlparse(self.path).query).get("refresh") or [""])[0]
                refresh = wanted.lower() not in ("", "0", "false", "no")
                self._json(self.panel.speakers(refresh))
            elif self.path.startswith("/api/clip"):
                # A recording for the browser to play by itself. A read, so it works
                # on a read-only panel: hearing what a clip sounds like changes
                # nothing, anywhere.
                site = (self.headers.get("Sec-Fetch-Site") or "").casefold()
                if site not in ("", "same-origin", "none"):
                    # The one read that hands over a file, so it gets the same
                    # courtesy the writes get: a browser says honestly whether the
                    # request came from this page or from somebody else's, and a
                    # library of recordings is not a public share. curl says
                    # nothing, and stays allowed; this is a browser guard.
                    self._json({"error": "recordings are only handed to this page"}, 403)
                    return
                name = (parse_qs(urlparse(self.path).query).get("name") or [""])[0]
                clip, content_type = self.panel.clip(name)
                self._send_file(clip, content_type)
            elif self.path.startswith("/api/near"):
                # "What are these numbers near?" is a read, and an offline one: it works
                # on a read-only panel, and it asks nobody anything.
                query = parse_qs(urlparse(self.path).query)
                self._json(self.panel.near({
                    "latitude": (query.get("lat") or [""])[0],
                    "longitude": (query.get("lon") or [""])[0]}))
            elif self.path.startswith("/api/tile"):
                # One square of a map this daemon fetched, on a profile that asked for a
                # map. The browser never talks to the tile server itself: the page keeps
                # being a page from this address and nothing else.
                site = (self.headers.get("Sec-Fetch-Site") or "").casefold()
                if site not in ("", "same-origin", "none"):
                    self._json({"error": "map squares are only handed to this page"}, 403)
                    return
                query = parse_qs(urlparse(self.path).query)
                self._write(self.panel.tile((query.get("z") or [""])[0],
                                            (query.get("x") or [""])[0],
                                            (query.get("y") or [""])[0]), "image/png")
            else:
                self._json({"error": f"no such path: {self.path}"}, 404)
        except _Status as exc:
            # A refusal this side chose - a name that is not in media_dir, a file
            # whose header is not audio. It has a status and a reason already, and
            # turning it into a 500 with a traceback in the log would hide both.
            self._json({"error": str(exc)}, exc.status)
        except ValueError as exc:
            # Coordinates that are not coordinates: the read routes never reach the
            # write paths, so this is where their bad input gets a 400 with the reason
            # instead of a 500 and a line in a log nobody reads.
            self._fail(400, str(exc))
        except ConnectionError:
            pass  # the page went away mid-response, which is normal
        except Exception as exc:                                  # never kill the thread
            # The exception's text names paths and values out of the profile; what
            # the page needs is that this side broke, and where to go for the rest.
            log.exception("GET %s failed", self.path)
            self._fail(500, "something went wrong on the daemon; its log has the detail")

    def do_POST(self) -> None:
        try:
            if not self._host_ok():
                # Nothing in the body is interpreted, but it is still read off the
                # socket and thrown away, bounded: a connection left half-read
                # reaches the page as a reset rather than as the reason for the
                # refusal, and the next thing on that connection becomes nonsense.
                self._drain(MAX_UPLOAD)
                self._json({"error": "this page answers to its own address, not to the name "
                                     "in that request"}, 403)
                return
            if not self._same_origin():
                self._drain(MAX_UPLOAD)
                self._json({"error": "this page only takes writes from its own origin"}, 403)
                return
            if self.path == "/api/geocode" and not self.panel.allow_edit:
                # The one path that is allowed past the read-only gate, because it is
                # not a change: it asks a question of a machine elsewhere and writes
                # nothing here. A household running a locked panel should still be able
                # to see what its coordinates mean, in the same way it can listen to a
                # recording or look at a scanned speaker.
                self._json(self.panel.find(self._body()))
                return
            if not self.panel.allow_edit:
                # Answered before any of the body is interpreted, but still read
                # off the socket and thrown away: a connection left half-read turns
                # whatever the browser sends next into nonsense.
                self._drain(MAX_UPLOAD)
                self._json({"error": "this panel is read-only; restart without --read-only "
                                     "to change the profile, add recordings or play test "
                                     "files"}, 403)
                return
            if self.path.startswith("/api/media/upload"):
                # Not JSON, so it does not go through _body(); and the body is read
                # before anything is answered - a socket left half-read turns the
                # next request on this connection into nonsense.
                data = self._raw(MAX_UPLOAD)
                name = (parse_qs(urlparse(self.path).query).get("name") or [""])[0]
                self._json(self.panel.save_upload(name, data))
                return
            body = self._body()
            if self.path == "/api/output":
                self._json(self.panel.toggle_output(str(body["name"]), bool(body["enabled"])))
            elif self.path == "/api/test":
                self._json(self.panel.test_play(str(body["output"]),
                                                [str(m) for m in (body.get("media") or [])]))
            elif self.path == "/api/test/stop":
                self._json(self.panel.stop_test(body))
            elif self.path == "/api/config":
                self._json(self.panel.save_config(str(body.get("text", ""))))
            elif self.path == "/api/reload":
                self._json(self.panel.reload())
            elif self.path == "/api/method":
                self._json(self.panel.set_method(body))
            elif self.path == "/api/geocode":
                # The one request this panel makes to a machine that is not on this
                # network, and it happens only because someone pressed find-it.
                self._json(self.panel.find(body))
            elif self.path == "/api/location":
                self._json(self.panel.set_location(body))
            elif self.path == "/api/hijri":
                self._json(self.panel.set_hijri_offset(body.get("days", body.get("offset"))))
            elif self.path == "/api/audio":
                self._json(self.panel.set_audio(body))
            elif self.path == "/api/speaker/add":
                self._json(self.panel.add_speaker(body))
            elif self.path == "/api/box/add":
                self._json(self.panel.add_box(body))
            elif self.path == "/api/output/remove":
                self._json(self.panel.remove_output(str(body["name"])))
            elif self.path == "/api/output/rename":
                self._json(self.panel.rename_output(body))
            elif self.path == "/api/output/volume":
                self._json(self.panel.set_output_volume(body))
            elif self.path == "/api/library/hold":
                self._json(self.panel.hold_recording(body))
            elif self.path == "/api/library/delete":
                self._json(self.panel.delete_recording(body))
            elif self.path == "/api/library/insert":
                self._json(self.panel.insert_recording(body))
            else:
                self._json({"error": f"no such path: {self.path}"}, 404)
        except _Status as exc:
            self._json({"error": str(exc)}, exc.status)
        except KeyError as exc:
            self._fail(400, f"missing field: {exc}")
        except ValueError as exc:
            self._fail(400, str(exc))
        except RuntimeError as exc:            # busy testing, or a disabled output
            self._fail(409, str(exc))
        except geocode.NeedsInternet as exc:
            # The page asked this daemon to ask somebody further away, and that further
            # away machine could not be reached at all.
            self._fail(504, str(exc))
        except geocode.GeocodeError as exc:
            # Reached, but would not answer honestly: a redirect, an error status, a
            # certificate this side could not verify. The reason is the whole message.
            self._fail(502, str(exc))
        except ConnectionError:
            pass  # the page went away mid-response, which is normal
        except Exception as exc:
            log.exception("POST %s failed", self.path)
            self._fail(500, "something went wrong on the daemon; its log has the detail")
