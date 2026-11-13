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
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import yaml

from . import __version__, calc, hijri, yamledit
from .backends import scan_speakers
from .config import (STARTER_LATITUDE, STARTER_LONGITUDE, STARTER_TIMEZONE, load_profile,
                     uses_starter_location, valid_host)
from .scheduler import PRAYER_KEYS, Runner, upcoming

log = logging.getLogger("muezzin.web")

AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".ogg", ".oga", ".flac", ".aac", ".opus"}

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
                         f"every time on this page is New York's until you change it in the "
                         f"profile below.")
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
            row = {"date": date.isoformat(),
                   "weekday": date.strftime("%a"),
                   "times": {k: _fmt(getattr(times, k, None)) for k in PRAYER_KEYS}}
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
                                "media": ev.media})
        text, mtime = "", None
        if p.path and Path(p.path).exists():
            # a config saved as cp1252 by a notepad must not take the whole page
            # down with it: replace the odd bytes so the times still render
            text = Path(p.path).read_text(encoding="utf-8", errors="replace")
            mtime = dt.datetime.fromtimestamp(Path(p.path).stat().st_mtime).isoformat(timespec="seconds")
        media_dir = Path(p.media_dir)
        files = []
        if media_dir.exists():
            files = sorted(f.name for f in media_dir.iterdir()
                           if f.is_file() and f.suffix.lower() in AUDIO_SUFFIXES)
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
            # Two decimals is about a kilometre, which is enough for the page to
            # say "this is your street" without putting the exact address of the
            # house on an unauthenticated LAN port. The file keeps the precise
            # numbers, and the editor below shows them.
            "location": {"latitude": round(p.location.latitude, 2),
                         "longitude": round(p.location.longitude, 2),

                         "timezone": p.location.timezone, "elevation_m": p.location.elevation_m},
            "method": {"label": p.params.label, "preset": preset,
                       "shia": p.params.midnight_from_fajr,
                       "fajr_angle": p.params.fajr_angle,
                       "isha_angle": p.params.isha_angle,
                       "isha_interval": p.params.isha_interval,
                       "shurf_angle": p.params.shurf_angle,
                       "maghrib_angle_offset": p.params.maghrib_angle_offset,
                       "midnight": "jafari (sunset to fajr)" if p.params.midnight_from_fajr else "solar",
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
            "media_url": (f"http://{self.runner.media.host_ip}:{self.runner.media.port}/"
                          if self.runner.media else None),
            "days": days,
            "upcoming": next_events,
            "events": [{"name": e.name, "at": e.at, "offset_min": e.offset_min,
                        "media": e.media, "targets": e.targets, "volume": e.volume,
                        "days": e.days} for e in p.events],
            # the picker's choices, from the same table `muezzin methods` prints.
            # The Ja'fari group is decided by which midnight the school uses, not
            # by a label someone wrote, so it cannot drift out of step with them.
            "presets": [{"name": key, "label": value.label,
                         "shia": value.midnight_from_fajr}
                        for key, value in sorted(calc.PRESETS.items())],
            "prayers": list(PRAYER_KEYS),
            "scan_at": self.scan_at,
            # what the page should say out loud before anything else: an empty
            # profile is a valid profile, and a silent one
            "notices": self.notices(),
            "max_upload": MAX_UPLOAD,
            "outputs": [{"name": o.name, "kind": o.kind, "target": o.target, "host": o.host,
                         "port": o.port, "volume": o.volume, "enabled": o.enabled}
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
        finally:
            self.testing.release()
        return {"played": media, "output": name}

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
        if kind == "smart_azan_pi":
            raise ValueError("that box runs Smart Azan's own web service; muezzin does not "
                             "speak its protocol, so it cannot be used as an output")
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

    # ---- serving ---------------------------------------------------------

    def start(self) -> None:
        # BaseHTTPRequestHandler's constructor takes only (request, address, server),
        # so the panel reaches the handler as a class attribute, not a kwarg.
        class Bound(_Handler):
            panel = self

        self._httpd = http.server.ThreadingHTTPServer(("0.0.0.0", self.port), Bound)
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
            else:
                self._json({"error": f"no such path: {self.path}"}, 404)
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
                self._json({"error": "this page answers to its own address, not to the name "
                                     "in that request"}, 403)
                return
            if not self._same_origin():
                self._json({"error": "this page only takes writes from its own origin"}, 403)
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
            elif self.path == "/api/config":
                self._json(self.panel.save_config(str(body.get("text", ""))))
            elif self.path == "/api/reload":
                self._json(self.panel.reload())
            elif self.path == "/api/method":
                self._json(self.panel.set_method(body))
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
        except ConnectionError:
            pass  # the page went away mid-response, which is normal
        except Exception as exc:
            log.exception("POST %s failed", self.path)
            self._fail(500, "something went wrong on the daemon; its log has the detail")


PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>muezzin</title>
<style>
 /* Night green and gold, over a khatam (eight-point star) lattice drawn inline as
    an SVG: a LAN panel has no internet to fetch a tile from, and a prayer page
    that only works online is a bad prayer page. */
 :root {
  --bg:#0b1411; --card:#101d18; --card2:#0d1815; --line:#23453a; --fg:#ece7d9;
  --dim:#94a89c; --gold:#d9ab4e; --gold2:#f0cf8c; --turq:#5cb9a8;
  --mourn:#9fb2c0; --bad:#e8897a;
 }
 * { box-sizing:border-box }
 body { margin:0; color:var(--fg); font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;
  background:radial-gradient(1100px 560px at 50% -10%, rgba(31,74,58,.55), rgba(11,20,17,0) 70%),
   url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='64' height='64'%3E%3Cg fill='none' stroke='%231d3a30' stroke-width='1'%3E%3Cpath d='M32 4 60 32 32 60 4 32Z'/%3E%3Cpath d='M12 12h40v40H12z'/%3E%3Cpath d='M0 0 12 12M64 0 52 12M0 64 12 52M64 64 52 52'/%3E%3C/g%3E%3C/svg%3E");
  background-attachment:fixed; background-size:auto, 64px 64px;
   /* The longhand colour, not the shorthand: a gradient that fades to
      transparent needs something solid under it, or the page turns white
      below the fold and the dark tile starts looking like a mistake. */
   background-color:var(--bg) }
 header { padding:20px 22px 14px; border-bottom:1px solid var(--line);
  display:flex; flex-wrap:wrap; gap:14px; align-items:baseline;
  background:linear-gradient(180deg, rgba(20,48,37,.75), rgba(11,20,17,0)) }
 .star { width:34px; height:34px; stroke:var(--gold); stroke-width:1.3; fill:none; align-self:center }
 h1 { font-size:21px; margin:0; letter-spacing:.06em; color:var(--gold2) }
 .ar { font-family:"Segoe UI","Noto Naskh Arabic",Tahoma,serif; font-size:15px; color:var(--dim) }
 h2 { font-size:12.5px; text-transform:uppercase; letter-spacing:.09em; color:var(--dim); margin:0 }
 .meta { color:var(--dim); font-size:13.5px; flex:1 1 320px }
 #hijri { color:var(--gold); font-size:14px }
 #next { padding:12px 22px; border-bottom:1px solid var(--line); color:var(--dim);
  font-size:14px; background:rgba(13,24,21,.75) }
 #next b { color:var(--gold2); font-weight:600; font-size:16px }
 main { padding:22px; display:grid; gap:18px; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); max-width:1200px }
 section { background:rgba(16,29,24,.88); border:1px solid var(--line); border-radius:12px; padding:16px }
 table { width:100%; border-collapse:collapse; font-size:14px }
 th { text-align:left; color:var(--dim); font-weight:500; font-size:12.5px; padding:4px 8px 4px 0 }
 td { padding:5px 8px 5px 0; border-top:1px solid var(--line) }
 .day { border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin:0 0 14px;
  background:rgba(13,24,21,.6) }
 /* today gets the arch: two rounded top corners, which is already the shape of a
    mihrab and of a dome. No pictures, no figures - the geometry does the work. */
 .day.today { border-color:var(--gold2); border-top-left-radius:60px 44px;
  border-top-right-radius:60px 44px; background:rgba(20,44,34,.75) }
 .dayhead { display:flex; flex-wrap:wrap; gap:8px; align-items:baseline; margin-bottom:8px }
 .day .pl { color:var(--dim) }
 .day .ar { color:var(--dim); text-align:right }
 .day .t { text-align:right; font-variant-numeric:tabular-nums }
 .hij { color:var(--gold); font-size:13px }
 .mark { font-size:12px; border:1px solid var(--line); border-radius:20px; padding:1px 9px }
 .mark.mourn { color:var(--mourn); border-color:#39566b; background:rgba(60,90,115,.18) }
 .mark.celebrate { color:var(--gold2); border-color:#5c4a22; background:rgba(217,171,78,.14) }
 .mark.plain { color:var(--turq) }
  /* the Arabic name of the day, inside its own pill, in the pill's colour */
  .mark .ar { color:inherit; font-size:13px }
 .now td { color:var(--gold2) }
 .now .pl { color:var(--gold) }
 button:disabled { opacity:.45; cursor:default; border-color:var(--line) }
 button { background:#163026; color:var(--fg); border:1px solid var(--line);
  border-radius:6px; padding:5px 10px; cursor:pointer; font:inherit }
 button:hover { border-color:var(--gold) }
 .switch { width:38px; height:20px; border-radius:10px; background:#2b3f38; position:relative;
  cursor:pointer; border:0; padding:0 }
 .switch:after { content:""; position:absolute; top:3px; left:3px; width:14px; height:14px;
  border-radius:50%; background:var(--fg); transition:left .15s }
 .switch[aria-checked=true] { background:var(--gold) }
 .switch[aria-checked=true]:after { left:21px; background:#0b1411 }
 textarea { width:100%; min-height:340px; background:#08110e; color:#dbe6df;
  border:1px solid var(--line); border-radius:8px; padding:12px;
  font:13px/1.45 ui-monospace,Consolas,monospace; tab-size:2 }
 select, input[type=file] { background:#0d1815; color:var(--fg); border:1px solid var(--line);
  border-radius:6px; padding:5px 8px; font:inherit; max-width:100% }
 select:disabled, input:disabled { opacity:.45 }
 .row select { min-width:190px }
 .members { color:var(--dim); font-size:13px }
 .known { color:var(--turq) }
 .unknown { color:var(--mourn) }
 .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:12px }
 #msg { white-space:pre-wrap; font-size:13.5px; margin-top:10px; min-height:1.2em }
 #msg.err { color:var(--bad) } #msg.ok { color:var(--turq) }
 .tag { font-size:12px; color:var(--dim); border:1px solid var(--line); border-radius:20px; padding:2px 9px }
 .wide { grid-column:1/-1 }
 a { color:var(--turq) }
 footer { padding:8px 22px 30px; max-width:1200px }
 #credit { color:var(--gold); font-size:13.5px }
 .fine { color:var(--dim); font-size:12.5px; margin-top:6px }
 .notice { color:var(--gold); background:#0d1815; border:1px solid var(--line);
  border-left:3px solid var(--gold); border-radius:8px; padding:9px 13px;
  margin:10px 0 0; font-size:13.5px; max-width:1200px }
</style></head><body>
<header>
 <svg class="star" viewBox="0 0 32 32" aria-hidden="true">
  <path d="M16 2 22 10 30 16 22 22 16 30 10 22 2 16 10 10Z"/><path d="M7 7h18v18H7z"/></svg>
 <h1>muezzin</h1>
 <span class="ar">أَوقات الصلاة</span>
 <div id="hijri"></div>
 <div class="meta" id="top">loading&hellip;</div>
 <button id="refresh">refresh</button>
</header>
<div id="next"></div>
<div id="notices"></div>
<main>
 <section><h2>Timetable</h2><div id="days"></div></section>
 <section><h2>Next events</h2><table><thead><tr><th>when</th><th>event</th><th>speakers</th><th>media</th></tr></thead><tbody id="upcoming"></tbody></table></section>
 <section><h2>Outputs</h2><table><thead><tr><th>name</th><th>kind</th><th>target</th><th>on</th><th></th></tr></thead><tbody id="outputs"></tbody></table>
  <div class="row"><select id="media"></select><span class="tag" id="mediaurl"></span></div>
 </section>
 <section><h2>Method</h2>
  <div class="row"><select id="preset"></select><select id="asr"></select><button id="applymethod">apply method</button></div>
  <div class="fine" id="overrides"></div>
  <div class="fine">The list is every school muezzin ships with, Ja'fari ones grouped apart
   because they count midnight from Maghrib. If the numbers you follow are not in the list,
   write the angles under <code>method:</code> in the profile - they stay put when you change
   the name here.</div>
  <div class="row"><span class="tag">Hijri date</span><button id="hijminus">&minus;1</button><span id="hijridays">0</span><button id="hijplus">+1</button></div>
  <div class="fine">Arithmetic cannot see the moon, so this is where you tell it what you saw.</div>
 </section>
 <section class="wide"><h2>Sound</h2>
  <table><thead><tr><th>time</th><th></th><th>every day</th><th>Friday</th></tr></thead><tbody id="sound"></tbody></table>
  <div class="row"><button id="applysound">apply these clips</button><span class="tag" id="soundsay">nothing changed</span></div>
  <div class="row"><input type="file" id="file" accept=".mp3,.m4a,.wav,.ogg,.oga,.flac,.aac,.opus,audio/*"><button id="upload">add this recording</button><span class="tag" id="uploadsay"></span></div>
  <div class="fine">A clip is picked from what is already in <code>media_dir</code>; the button above
   puts a new recording there. Nothing overwrites a recording that is playing, so two recordings of
   the same adhans need two names.</div>
 </section>
 <section class="wide"><h2>Speakers on the network</h2>
  <div class="row"><button id="scan">look again</button><span class="tag" id="scansay">not looked yet</span></div>
  <table><thead><tr><th>name</th><th>what</th><th>where</th><th>members</th><th></th></tr></thead><tbody id="found"></tbody></table>
  <div class="fine">A group's members are read back from the speakers themselves: the group record
   out on the network only names the one speaker in charge of it. A speaker that will not answer
   leaves the members unknown, which is not the same as nobody being in it.</div>
 </section>
 <section class="wide"><h2>Profile <span class="tag" id="cfgpath"></span></h2>
  <textarea id="yaml" spellcheck="false"></textarea>
  <div class="row"><button id="save">save &amp; reload</button><button id="reload">reload from disk</button>
   <span class="tag">saved edits restart nothing: the daemon picks up new speakers and times on the spot</span></div>
  <div id="msg"></div>
 </section>
</main>
<footer>
 <div id="credit"></div>
 <div class="fine">The Hijri date is tabular arithmetic, so it can sit a day either side of a
  moon sighting; <code>hijri_offset</code> in your profile lines it up with the calendar you
  follow. The day markers are decoration on the calendar, not a ruling about when anything is.</div>
</footer>
<script>
let st=null;
const $=s=>document.querySelector(s);
// Speaker names come from the network, so every one of them is escaped on its way
// into the page - apostrophes included, because "Sara's Nest" is a perfectly
// ordinary thing to call a speaker and a quote is exactly what closes an attribute.
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Bilingual, the way the prayer itself is: English labels, Arabic names. These two
// tables are fixed text in the page, not something downloaded and not translated
// at runtime.
const NAME={fajr:'Fajr',sunrise:'Sunrise',dhuhr:'Dhuhr',asr:'Asr',maghrib:'Maghrib',
 isha:'Isha',midnight:'Midnight',true_night:'True night',shurf:"Shaf'",sunset:'Sunset'};
const AR={fajr:'الفجر',sunrise:'الشروق',dhuhr:'الظهر',asr:'العصر',maghrib:'المغرب',
 isha:'العشاء',midnight:'نصف الليل',true_night:'نصف الليل الشرعي',shurf:'الشفع',sunset:'الغروب'};
// The table reads as a day, not as a dictionary: sunset sits immediately before
// maghrib because on a Shia profile they are a few minutes apart and the whole
// point is to see the difference.
const ORDER=['fajr','sunrise','dhuhr','asr','sunset','maghrib','isha','midnight',
 'true_night','shurf'];
async function api(path,body){
 const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):null});
 const j=await r.json().catch(()=>({error:'bad response'}));
 if(!r.ok) throw new Error(j.error||('HTTP '+r.status));
 return j;
}
function say(t,kind){ const m=$('#msg'); m.textContent=t; m.className=kind||''; }
// The YAML box is the one place where you might be mid-edit, and a 60 second
// refresh must never throw your draft away - so the guard is "dirty", not
// "has focus": clicking test, or the phone keyboard closing, keeps your text.
function syncYaml(){
 const ta=$('#yaml');
 const path=st.config_path||'(no file)';
 if(ta.dataset.dirty==='1'){ $('#cfgpath').textContent=path+' · unsaved edits'; return; }
 ta.value=st.config_text;
 $('#cfgpath').textContent=path;
}
function render(){
 const nx=st.upcoming[0]||null;
 $('#top').textContent=`${st.method.label} · ${st.location.latitude}, ${st.location.longitude} · ${st.location.timezone} · asr ${st.method.asr} · ${st.method.midnight} midnight · ${st.now}`+(st.read_only?' · read-only':'');
 $('#hijri').innerHTML=`${esc(st.today.hijri)} AH <span class="ar">${esc(st.today.hijri_ar)}</span>`
  +(st.hijri_offset?` <span class="tag">hijri_offset ${st.hijri_offset>0?'+':''}${st.hijri_offset}</span>`:'');
 $('#next').innerHTML=nx
  ? `<b>${esc(nx.when)}</b> · ${esc(NAME[nx.at]||nx.at)} <span class="ar">${esc(AR[nx.at]||'')}</span> · ${esc(nx.name)} to ${esc(nx.targets.join(', ')||'(no speaker enabled)')}`
  : 'nothing scheduled in the next two days';
 // A brand new install sees this page long before it sees a log file, so the two
 // things that make a quiet muezzin are said here as well as in the daemon's log.
 $('#notices').innerHTML=(st.notices||[]).map(n=>`<div class="notice">${esc(n)}</div>`).join('');
 $('#days').innerHTML=st.days.map((d,i)=>
  `<div class="day${i===0?' today':''}"><div class="dayhead"><h2>${esc(d.weekday)} ${esc(d.date)}</h2>`
  +` <span class="hij">${esc(d.hijri)}</span> <span class="ar">${esc(d.hijri_ar)}</span>`
  +(d.marks||[]).map(m=>` <span class="mark ${esc(m.kind)}">${esc(m.name)}${m.ar?` <span class="ar">${esc(m.ar)}</span>`:''}</span>`).join('')
  +`</div><table>${ORDER.filter(k=>k in d.times).map(k=>[k,d.times[k]]).map(([k,v])=>
    `<tr class="${nx&&nx.at===k&&nx.date===d.date?'now':''}"><td class="pl">${esc(NAME[k]||k)}</td>`
    +`<td class="ar">${esc(AR[k]||'')}</td><td class="t">${esc(v)}</td></tr>`).join('')}</table></div>`).join('');
 $('#upcoming').innerHTML=st.upcoming.map(e=>`<tr><td>${esc(e.when)}</td><td>${esc(e.name)}<span class="tag">${esc(e.at)}${e.offset_min?` ${e.offset_min>0?'+':''}${e.offset_min}m`:''}</span></td><td>${esc(e.targets.join(', '))||'(none enabled)'}</td><td>${esc(e.media.join(', '))}</td></tr>`).join('')||'<tr><td colspan=4>nothing scheduled in the next two days</td></tr>';
 $('#outputs').innerHTML=st.outputs.map(o=>`<tr><td>${esc(o.name)}</td><td>${esc(o.kind)}</td><td>${esc(o.target||o.host||'-')}</td><td><button class="switch" data-name="${esc(o.name)}" aria-checked="${o.enabled}"></button></td><td><button data-test="${esc(o.name)}">test</button></td></tr>`).join('');
 document.querySelectorAll('.switch').forEach(b=>b.onclick=()=>act(()=>api('/api/output',{name:b.dataset.name,enabled:b.getAttribute('aria-checked')!=='true'})));
 document.querySelectorAll('[data-test]').forEach(b=>b.onclick=()=>act(()=>api('/api/test',{output:b.dataset.test,media:$('#media').value?[$('#media').value]:[]})));
 const pick=$('#media'), want=pick.value;
 pick.innerHTML=st.media_files.map(f=>`<option>${esc(f)}</option>`).join('')||'<option value="">(no audio in media_dir)</option>';
 if(want&&[...pick.options].some(o=>o.value===want)) pick.value=want;
 $('#mediaurl').textContent=st.media_url?('speakers fetch audio from '+st.media_url):'no media server needed by this profile';
  // A credit has to name a person, because a person is who answers questions about
  // the code. Say who you are with `attribution:` in the profile.
 $('#credit').innerHTML=`muezzin ${esc(st.version||'')} · MIT · `
  +(st.attribution?`written by ${esc(st.attribution)}, with an AI assistant`
                  :'written by whoever set this up, with an AI assistant');
 renderMethod();renderSound();renderFound();
 syncYaml();
 $('#save').disabled=$('#reload').disabled=st.read_only;
 document.querySelectorAll('.switch,[data-test]').forEach(b=>b.disabled=st.read_only);
 ['#preset','#asr','#applymethod','#hijminus','#hijplus','#applysound','#upload','#file'].forEach(s=>{ $(s).disabled=st.read_only; });
}
// ---- the three editors ----------------------------------------------------
//
// All of them write through the daemon, which validates the result before the
// file changes, so the page does not need to know what a legal profile is: it
// needs to know what it last showed you, and to send only what differs.
let note=[], SC=null, sent=0, up={};
function renderMethod(){
 const cur=st.method.preset||'', p=$('#preset');
 const groups=[["Not Ja'fari",[]],["Ja'fari (midnight from Maghrib)",[]]];
 (st.presets||[]).forEach(x=>groups[x.shia?1:0][1].push(x));
 p.innerHTML=(cur?'':'<option value="" selected>(angles written by hand)</option>')
  +groups.map(g=>`<optgroup label="${esc(g[0])}">${g[1].map(x=>
    `<option value="${esc(x.name)}"${x.name===cur?' selected':''}>${esc(x.label)}</option>`).join('')}</optgroup>`).join('');
 $('#asr').innerHTML=['standard','hanafi'].map(v=>
  `<option value="${v}"${v===st.method.asr?' selected':''}>${v==='hanafi'?'asr: Hanafi (later)':'asr: standard'}</option>`).join('');
 const extra=st.overridden||[];
 $('#overrides').textContent=(cur?'in use: '+st.method.label:'no preset in the file: every angle is written by hand')
  +(extra.length?' · your own numbers still in force: '+extra.join(', '):'');
 $('#hijridays').textContent=(st.hijri_offset>0?'+':'')+st.hijri_offset;
}
function clipFor(at,friday){
 const rows=(st.events||[]).filter(e=>e.at===at&&!!(e.days&&e.days.length)===friday);
 return rows[0]||null;
}
function clipSelect(at,friday){
 const ev=clipFor(at,friday), cur=ev&&ev.media&&ev.media.length?ev.media[0]:'';
 const files=(st.media_files||[]).slice();
 if(cur&&files.indexOf(cur)<0) files.unshift(cur);
 return `<select data-at="${at}" data-friday="${friday?1:0}">`
  +[''].concat(files).map(f=>`<option value="${esc(f)}"${f===cur?' selected':''}>${esc(f||'(no clip)')}</option>`).join('')
  +`</select>`+((ev&&ev.media&&ev.media.length>1)?` <span class="tag">${ev.media.length} clips</span>`:'')
  +((ev&&ev.offset_min)?` <span class="tag">${ev.offset_min>0?'+':''}${ev.offset_min}m</span>`:'');
}
function renderSound(){
 const box=$('#sound');
 if(box.dataset.dirty==='1'){ $('#soundsay').textContent='your picks are waiting for apply'; return; }
 const times=(st.days&&st.days[0]&&st.days[0].times)||{};
 box.innerHTML=ORDER.filter(k=>k in times).map(k=>
  `<tr><td>${esc(NAME[k]||k)}</td><td class="ar">${esc(AR[k]||'')}</td>`
  +`<td>${clipSelect(k,false)}</td><td>${clipSelect(k,true)}</td></tr>`).join('')
  ||'<tr><td colspan=4>no times to put clips on</td></tr>';
 document.querySelectorAll('[data-at]').forEach(s=>s.onchange=()=>{
  box.dataset.dirty='1'; $('#soundsay').textContent='your picks are waiting for apply';
  if(st.read_only) s.disabled=true;
 });
 $('#soundsay').textContent='nothing changed';
}
function renderFound(){
 const box=$('#found');
 const silent=(SC&&SC.found&&SC.found.silent)||[];
 $('#scansay').textContent=SC?('looked at '+SC.seen_at+(silent.length?' · '+silent.length+' would not say whose groups it is in':''))
  :'not looked yet';
 if(!SC){ box.innerHTML='<tr><td colspan=5>press look again to see what is on the LAN</td></tr>'; return; }
 const inuse=SC.in_profile||{};
 const act2=(target,name)=>inuse[target]
  ? `<span class="known">in use as ${esc(inuse[target])}</span> <button data-drop="${esc(inuse[target])}">stop using</button>`
  : `<button data-add="${esc(target)}">use</button>`;
 const rows=[];
 (SC.found.groups||[]).forEach(g=>rows.push(
  `<tr><td>${esc(g.name)}</td><td>group</td><td class="members">${esc(g.address||'')}:${esc(g.port||'')}</td>`
  +`<td class="members">${g.membership_known?((g.members||[]).map(esc).join(', ')||'<span class="unknown">nobody claimed it</span>'):'<span class="unknown">unknown: they did not answer</span>'}</td>`
  +`<td>${act2(g.name,'')}</td></tr>`));
 (SC.found.speakers||[]).forEach(d=>rows.push(
  `<tr><td>${esc(d.name)}</td><td>speaker${d.model?' · '+esc(d.model):''}</td><td class="members">${esc(d.address||'')}:${esc(d.port||'')}</td>`
  +`<td class="members">look at the groups above</td><td>${act2(d.name,'')}</td></tr>`));
 (SC.found.boxes||[]).forEach(b=>rows.push(
  `<tr><td>${esc(b.name)}</td><td>box${b.player?' · '+esc(b.player):''}</td><td class="members">${esc(b.address||'')}:${esc(b.port||'')}</td>`
  +`<td class="members">${b.kind==='muezzin_box'?'plays what this daemon tells it':'<span class="unknown">belongs to another program: muezzin does not speak its protocol</span>'}</td>`
  +`<td>${b.kind==='muezzin_box'?act2(b.address,b.name):'<span class="tag">not usable</span>'}</td></tr>`));
 box.innerHTML=rows.join('')||'<tr><td colspan=5>nothing answered</td></tr>';
 document.querySelectorAll('[data-add]').forEach(b=>b.onclick=()=>{
  const boxes=(SC.found.boxes||[]).filter(x=>x.address===b.dataset.add);
  act2call(boxes.length?'/api/box/add':'/api/speaker/add',
   boxes.length?{name:b.closest('tr').cells[0].textContent,host:b.dataset.add,port:Number(boxes[0].port)}:{target:b.dataset.add});
 });
 document.querySelectorAll('[data-drop]').forEach(b=>b.onclick=()=>act2call('/api/output/remove',{name:b.dataset.drop}));
}
function act2call(path,body){ act(()=>api(path,body),async()=>{ SC=await api('/api/speakers'); renderFound(); }); }
async function applySound(){
 const picks=[...document.querySelectorAll('[data-at]')];
 let sent=0;
 for(const s of picks){
  const at=s.dataset.at, friday=s.dataset.friday==='1';
  const ev=clipFor(at,friday), have=ev&&ev.media&&ev.media.length?ev.media[0]:'';
  if(s.value===have) continue;
  await api('/api/audio',{at,friday,media:s.value?[s.value]:[]});
  sent++;
 }
 return sent;
}
async function applyMethod(){
 const j=await api('/api/method',{preset:$('#preset').value,asr_shadow:$('#asr').value});
 return j;
}
async function uploadFile(){
 const f=$('#file').files[0];
 if(!f) throw new Error('choose a recording first');
 // the bytes are the whole request: the panel looks at what they start with
 // before it lets them anywhere near media_dir
 // hand over the bytes, not the File object: a File body may be sent chunked,
 // and this server needs to know the size before it writes anything to disk
 const r=await fetch('/api/media/upload?name='+encodeURIComponent(f.name),
  {method:'POST',body:await f.arrayBuffer()});
 const j=await r.json().catch(()=>({error:'bad response'}));
 if(!r.ok) throw new Error(j.error||('HTTP '+r.status));
 return j;
}
async function act(fn,after){ try{ await fn(); say('',''); if(after)await after(); await load(); }catch(e){ say(e.message,'err'); } }
// the scan is expensive and the daemon caches it, so arriving at the page shows
// what was last seen if there is a last-seen; the button is for when speakers
// have been added or moved rooms
async function load(){ st=await api('/api/state'); if(!SC&&st.scan_at) SC=await api('/api/speakers'); render(); }
$('#yaml').addEventListener('input',()=>{ $('#yaml').dataset.dirty='1'; });
$('#refresh').onclick=()=>act(load);
$('#save').onclick=()=>act(()=>api('/api/config',{text:$('#yaml').value}),()=>{ $('#yaml').dataset.dirty=''; say('saved and reloaded','ok'); });
$('#reload').onclick=()=>act(()=>api('/api/reload'),()=>{ $('#yaml').dataset.dirty=''; say('reloaded from disk','ok'); });
$('#applymethod').onclick=()=>act(async()=>{ const j=await applyMethod(); note=j.still_overridden||[]; },
 ()=>say(note.length?'method written, and your own numbers are still in force: '+note.join(', ')
                   :'method written; the timetable on this page is the new one','ok'));
$('#hijminus').onclick=()=>act(()=>api('/api/hijri',{days:st.hijri_offset-1}),()=>say('the Hijri date on this page moved','ok'));
$('#hijplus').onclick=()=>act(()=>api('/api/hijri',{days:st.hijri_offset+1}),()=>say('the Hijri date on this page moved','ok'));
$('#applysound').onclick=()=>act(async()=>{ sent=await applySound(); },
 ()=>{ $('#sound').dataset.dirty=''; say(sent?('wrote '+sent+' clip'+(sent>1?'s':'')+': the daemon reloaded with them')
                                       :'nothing needed writing','ok'); });
$('#scan').onclick=()=>act(async()=>{ SC=await api('/api/speakers?refresh=1'); },
 ()=>say(((SC.found.speakers||[]).length)+' speakers, '+((SC.found.groups||[]).length)+' groups, '
   +((SC.found.boxes||[]).length)+' boxes','ok'));
$('#upload').onclick=()=>act(async()=>{ up=await uploadFile(); },
 ()=>{ $('#uploadsay').textContent=up.uploaded+' in media_dir';
       say('added '+up.uploaded+(up.url?' · a speaker can reach it at '+up.url:''),'ok'); });
load().catch(e=>{$('#top').textContent=e.message;});
setInterval(()=>load().catch(()=>{}),60000);
</script></body></html>
"""
