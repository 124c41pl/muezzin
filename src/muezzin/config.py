"""Configuration model: everything muezzin does is data, not enums.

A profile is a YAML file (see muezzin.example.yaml). The important design
decision: `method` is not a pick-from-a-list. It is a named preset that any single
number may override, so a community's own published angles are representable
without waiting for an upstream release.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import yaml

from .calc import (ASR_SHADOW_HANAFI, ASR_SHADOW_STANDARD, Adjustments, Location,
                   MethodParams, method_from_config)

# A `host:` ends up inside a URL the daemon builds when it talks to a LAN box, so
# keep it to what a hostname or an IP literal is actually allowed to contain.
# Spaces, `@`, `/`, `?` and control characters are not address characters; they
# are what an attacker-chosen value looks like.
_HOST_RE = re.compile(r"^[A-Za-z0-9._:\-\[\]]{1,253}$")


def valid_host(text: str) -> bool:
    """Is this a plausible host or address to send a request to?

    The profile is a local file, but it decides where the daemon opens
    connections, and a stray "http://" or a space in a `host:` field is far more
    likely a paste gone wrong than a working device. Checked at load time so the
    mistake surfaces as a sentence, not as silence at 5 am.
    """
    return bool(_HOST_RE.fullmatch(str(text)))


# The coordinates the starter profile ships with: a placeholder for New York, so
# a profile still carrying all three is one nobody has set up yet.
STARTER_LATITUDE = 40.7128
STARTER_LONGITUDE = -74.006
STARTER_TIMEZONE = "America/New_York"


def uses_starter_location(loc: Location) -> bool:
    """Is this profile still sitting on the starter's placeholder coordinates?

    This is the one kind of wrong that produces no error: the arithmetic is
    impeccable and the city is somebody else's. Kept deliberately narrow, so a
    profile whose author changed any one of the three values never hears from
    this function.
    """
    return (round(float(loc.latitude), 4) == STARTER_LATITUDE
            and round(float(loc.longitude), 4) == STARTER_LONGITUDE
            and str(loc.timezone) == STARTER_TIMEZONE)


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# How far an event may be shifted from the prayer time it hangs off. Bigger than
# a day and it is no longer "the adhan, twenty minutes later", it is a typo that
# lands on some other weekday.
MAX_OFFSET_MIN = 1440


def _inside(root: Path, rel) -> Path:
    """Resolve `rel` under `root`, and refuse if the result escapes it."""
    p = (root / str(rel)).resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"{rel!r} is outside {root}; keep the files inside that folder and "
                         "name them relative to it")
    return p


@dataclass
class OutputConfig:
    """One place sound can end up: a Cast speaker, a group, the PC, a LAN box."""
    name: str
    kind: str                      # google_cast | lan_box | pc_speakers | file
    target: Optional[str] = None   # speaker/group name (Cast) or host (lan_box)
    host: Optional[str] = None
    port: Optional[int] = None
    volume: float = 0.5
    enabled: bool = True


@dataclass
class EventConfig:
    """What to play, when, and where."""
    name: str
    at: str                                  # fajr|sunrise|dhuhr|asr|maghrib|isha|midnight|true_night|shurf
    offset_min: int = 0                      # play this many minutes after `at`
    media: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)   # output names; empty = all enabled
    volume: Optional[float] = None           # overrides the output's own volume
    days: Optional[list[str]] = None         # e.g. ["fri"] to restrict


@dataclass
class Profile:
    location: Location
    params: MethodParams
    asr_shadow: float
    adjustments: Adjustments
    media_dir: Path
    outputs: list[OutputConfig]
    events: list[EventConfig]
    http_port: int = 8010            # serves media to Cast devices
    hijri_offset: int = 0            # shift the displayed Hijri date to match your moon
    attribution: Optional[str] = None  # whose name the page shows in its credit line
    out_dir: Optional[Path] = None   # the only directory `kind: file` outputs may write into
    path: Optional[Path] = None

    def output(self, name: str) -> Optional[OutputConfig]:
        return next((o for o in self.outputs if o.name == name), None)

    def media_path(self, rel) -> Path:
        """Resolve one entry of an event's `media:` list.

        Everything that reads a recording goes through here, so a profile that
        names `../../whatever.wav` is rejected where it is written rather than
        read out of nowhere at 5 am.
        """
        return _inside(self.media_dir, rel)

    def enabled_outputs(self) -> list[OutputConfig]:
        return [o for o in self.outputs if o.enabled]

    def targets_for(self, ev: EventConfig) -> list[OutputConfig]:
        if ev.targets:
            return [o for o in (self.output(n) for n in ev.targets) if o and o.enabled]
        return self.enabled_outputs()


def load_profile(path) -> Profile:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")

    locraw = raw.get("location") or {}
    try:
        latitude = float(locraw["latitude"])
        longitude = float(locraw["longitude"])
    except (KeyError, TypeError, ValueError):
        # A KeyError here would be a traceback over a missing decimal point, and
        # the person reading it would not be told which line to fix.
        raise ValueError(f"{path}: location needs latitude and longitude as numbers; "
                         f"this one says {locraw if isinstance(locraw, dict) else locraw!r}") from None
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise ValueError(f"{path}: location latitude must be between -90 and 90 and longitude "
                         f"between -180 and 180, got {latitude}, {longitude}")
    tzname = str(locraw["timezone"])
    try:
        ZoneInfo(tzname)
    except (KeyError, ValueError):
        # Nothing checks the zone again before the daemon has already started, so
        # a typo here would end as a traceback and a silent morning.
        raise ValueError(f"{path}: location timezone {tzname!r} is not a zone this machine "
                         "knows. Use an IANA name like America/New_York.") from None
    loc = Location(
        latitude=latitude,
        longitude=longitude,
        timezone=tzname,
        elevation_m=float(locraw.get("elevation_m", 0.0)),
    )

    mraw = dict(raw.get("method") or {})
    preset = mraw.pop("preset", None) or mraw.pop("method", "mwls")
    shadow_raw = mraw.pop("asr_shadow", "standard")
    # minute offsets are part of "how the times for this house are worked out", so
    # people write them inside the method block as often as at the top level. Read
    # either place - and never drop a name quietly, because an offset that reaches
    # no prayer is worse than an offset nobody asked for.
    margin = mraw.pop("adjustments", None) or {}
    params = method_from_config({"method": preset, **mraw})

    shadow = ASR_SHADOW_HANAFI if str(shadow_raw).lower().startswith("hana") else ASR_SHADOW_STANDARD

    araw = raw.get("adjustments") or {}
    for label, table in (("method.adjustments", margin), ("adjustments", araw)):
        if not isinstance(table, dict):
            raise ValueError(f"{path}: {label} should name prayers with minutes, "
                             f"not {table!r}")
    clash = sorted(set(margin) & set(araw))
    if clash:
        raise ValueError(f"{path}: {', '.join(clash)} is adjusted twice, once under method: "
                         f"and once at the top level; keep the one you mean")
    merged = {**margin, **araw}
    unknown = sorted(k for k in merged if k not in Adjustments.__dataclass_fields__)
    if unknown:
        raise ValueError(f"{path}: {', '.join(unknown)} is not a prayer time that can be "
                         f"nudged; the names are {', '.join(Adjustments.__dataclass_fields__)}")
    try:
        adj = Adjustments(**{k: int(v) for k, v in merged.items()})
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path}: adjustments want whole minutes per prayer; {exc}") from None

    media_dir = (path.parent / str(raw.get("media_dir", "media"))).resolve()
    # `kind: file` outputs copy recordings somewhere. That is a genuinely useful
    # feature and a genuine way to write into any directory on the machine, so the
    # profile names one root and the outputs live inside it.
    out_dir = (path.parent / str(raw.get("out_dir", "out"))).resolve()

    outputs = []
    from .backends import KINDS          # lazy: keeps config importable without the players
    for item in raw.get("outputs") or []:
        kind = str(item["kind"])
        if kind not in KINDS:
            raise ValueError(f"{path}: output {item.get('name')!r} has unknown kind {kind!r}; "
                             f"known kinds: {', '.join(sorted(KINDS))}")
        host = item.get("host")
        if kind == "file":
            dest = Path(str(host or item.get("target") or "out"))
            dest = dest.resolve() if dest.is_absolute() else (path.parent / dest).resolve()
            if dest != out_dir and out_dir not in dest.parents:
                raise ValueError(f"{path}: output {item.get('name')!r} writes to {dest}, which is "
                                 f"outside out_dir ({out_dir}). Set out_dir in the profile if you "
                                 "want the copies somewhere else.")
            host = str(dest)            # already absolute, so the backend cannot reinterpret it
        elif host is not None and not valid_host(host):
            raise ValueError(f"{path}: output {item.get('name')!r} has host {host!r}, which is not "
                             "a plain hostname or IP address")
        port = item.get("port")
        if port is not None:
            port = int(port)
            if not 0 < port < 65536:
                raise ValueError(f"{path}: output {item.get('name')!r} has port {port}, which is "
                                 "not between 1 and 65535")
        outputs.append(OutputConfig(
            name=str(item["name"]),
            kind=kind,
            target=item.get("target"),
            host=host,
            port=port,
            volume=float(item.get("volume", 0.5)),
            enabled=bool(item.get("enabled", True)),
        ))

    events = []
    for item in raw.get("events") or []:
        name = str(item.get("name") or item["at"])
        offset = int(item.get("offset_min", 0))
        if not -MAX_OFFSET_MIN <= offset <= MAX_OFFSET_MIN:
            raise ValueError(f"{path}: event {name!r} has offset_min {offset}; a shift has to stay "
                             f"within one day ({MAX_OFFSET_MIN} minutes), otherwise the event "
                             "lands on a different weekday and never fires")
        days = None
        if item.get("days"):
            raw_days = item["days"]
            if isinstance(raw_days, str):
                # `days: fri` reads as one weekday in YAML, so accept it as one;
                # iterating the string instead would check the letters f, r, i.
                raw_days = [raw_days]
            days = [str(d).lower()[:3] for d in raw_days]
            bad = [d for d in days if d not in WEEKDAYS]
            if bad:
                raise ValueError(f"{path}: event {name!r} has days it does not name: "
                                 f"{', '.join(bad)}; use {', '.join(WEEKDAYS)}")
        events.append(EventConfig(
            name=name,
            at=str(item["at"]),
            offset_min=offset,
            media=[str(m) for m in (item.get("media") or [])],
            targets=[str(t) for t in (item.get("targets") or [])],
            volume=(float(item["volume"]) if item.get("volume") is not None else None),
            days=days,
        ))

    # A typo in a config file otherwise shows up as silence at 5 am, which is the
    # worst possible time to discover it, so reject the file now instead.
    from .scheduler import PRAYER_KEYS
    known_outputs = {o.name for o in outputs}
    for ev in events:
        if ev.at not in PRAYER_KEYS:
            raise ValueError(f"{path}: event {ev.name!r} has unknown `at: {ev.at}`; "
                             f"known times: {', '.join(PRAYER_KEYS)}")
        unknown = [t for t in ev.targets if t not in known_outputs]
        if unknown:
            raise ValueError(f"{path}: event {ev.name!r} targets output(s) that do not exist: "
                             f"{', '.join(unknown)}. Outputs you defined: "
                             f"{', '.join(sorted(known_outputs)) or 'none'}")
        if not ev.media:
            raise ValueError(f"{path}: event {ev.name!r} has no `media:` files to play")
        for m in ev.media:
            try:
                _inside(media_dir, m)
            except ValueError as exc:
                raise ValueError(f"{path}: event {ev.name!r}: {exc}") from None

    # Display-only, but a typo here silently moves every Hijri date on the page,
    # so keep it in the small range where it means "our moon and your moon
    # disagreed by a day".
    offset_raw = raw.get("hijri_offset", 0)
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise ValueError(f"{path}: hijri_offset must be a whole number of days, "
                         f"got {offset_raw!r}") from None
    if not -3 <= offset <= 3:
        raise ValueError(f"{path}: hijri_offset must be between -3 and 3, got {offset}. "
                         "It shifts the Hijri date the page shows, not the prayer times.")

    http_port = int(raw.get("http_port", 8010))
    if not 0 <= http_port < 65536:
        raise ValueError(f"{path}: http_port must be between 0 and 65535, got {http_port}. "
                         "0 means pick a free port.")

    return Profile(location=loc, params=params, asr_shadow=shadow, adjustments=adj,
                   media_dir=media_dir, outputs=outputs, events=events,
                   http_port=http_port, hijri_offset=offset,
                   attribution=(str(raw["attribution"]) if raw.get("attribution") else None),
                   out_dir=out_dir, path=path)
