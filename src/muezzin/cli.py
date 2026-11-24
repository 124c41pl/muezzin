"""muezzin command line."""
from __future__ import annotations

import argparse
import datetime as dt
import errno
import logging
import os
import sys
import tempfile
from pathlib import Path

import yaml

from . import __version__, calc, geocode, localplay, places, yamledit
from .config import (STARTER_LATITUDE, STARTER_LONGITUDE, STARTER_TIMEZONE, OutputConfig,
                     Profile, load_profile, uses_starter_location, valid_host)

log = logging.getLogger("muezzin.cli")


def _host_arg(value: str) -> str:
    """A --allow-host value, checked where it is typed rather than at the point
    where it silently stops matching anything."""
    if not valid_host(value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a plain hostname or IP address")
    return value


def _env_port(name: str) -> int | None:
    """A port named in the environment, or None when this run has no opinion.

    This exists for containers: an image ships the command line, so the person
    starting a second container on a machine that already runs one has nothing to
    edit but the environment. Reading it here, and refusing a value that is not a
    port here, is the whole point: found later that value is an OSError about an
    address family, or a page sitting on a port nobody meant to open, in both cases
    with nothing in the message naming what was typed.
    """
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    wrong = (f"{name} is not a port: {raw!r}. Name a number between 0 and 65535; "
             "0 means pick a free one.")
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(wrong) from None
    if not 0 <= port < 65536:
        raise ValueError(wrong)
    return port


def _port_busy(exc: OSError, what: str, port: int, env_name: str, where: str) -> int:
    """A port that was already spoken for, said in the terms the fix is written in.

    This is what the second muezzin on a machine runs into, and the operating
    system's own sentence - "[Errno 98] Address already in use" - knows nothing
    about this program having two ports, let alone where each one is named. Anything
    that is not this mistake keeps the traceback it had: a media folder that went
    missing should not be dressed up as a port problem.
    """
    if getattr(exc, "errno", None) not in (errno.EADDRINUSE, errno.EACCES):
        raise exc
    reason = ("that port is already in use on this machine"
              if exc.errno == errno.EADDRINUSE else
              "this machine would not let us listen there - ports under 1024 need privileges")
    print(f"{what} could not start on port {port}: {reason}.\n"
          f"      Name another one - {env_name} in the environment, or {where} for this run -\n"
          f"      or 0, and a free port is picked for you.", file=sys.stderr)
    return 2


EXAMPLE = """\
# muezzin profile - everything here is data; nothing needs a code change.
location:
  latitude: 40.7128
  longitude: -74.006
  timezone: America/New_York     # IANA name: DST is handled by the tz database
  elevation_m: 10

method:
  preset: isna                   # any name from `muezzin methods`
  asr_shadow: standard           # standard | hanafi
  # override a single number to match your community's published table:
  # fajr_angle: 15.0
  # isha_angle: 15.0
  # isha_interval: 90            # minutes after maghrib instead of an angle
  # maghrib_angle_offset: 3.7    # e.g. Tehran institute maghrib at 4.5 deg
  # high_latitude_rule: angle_based

adjustments: {fajr: 0, dhuhr: 5, maghrib: 0}

media_dir: media
http_port: 8010                  # serves media_dir to Cast devices

# Display only. The page shows a tabular Hijri date, and the moon gets the final
# word, so shift it to line up with the calendar you follow. No prayer time and
# no event reads this.
hijri_offset: 0

# Who the page credits, in its footer. Name a person: a person is who someone
# can ask about the code, or tell that a time looks wrong.
# attribution: "your name or handle"

outputs:
  - name: pc
    kind: pc_speakers              # this machine, at whatever level it is already set to
  - name: study
    kind: google_cast
    target: Study speaker      # `muezzin devices` lists names, groups included
    volume: 0.5                  # the level on that speaker, and only on speakers
  - name: landing-group
    kind: google_cast
    target: Landing group        # a Google Home speaker GROUP works as one target
    volume: 0.45
  - name: pi-box
    kind: lan_box
    host: 192.168.0.50
    port: 8090
  - name: testdir
    kind: file
    host: out
    enabled: false

events:
  - name: fajr-adhan
    at: fajr
    media: [fajr.mp3]
    targets: [pc, study, pi-box]
    volume: 0.8              # one level for the cast targets in this event
  - name: sunrise-tune
    at: sunrise
    offset_min: -5
    media: [dua.mp3]
    targets: [study]
  - name: jumuah
    at: dhuhr
    offset_min: 15
    days: [fri]
    media: [khutbah.mp3]
"""

# What `muezzin init` writes, and it is deliberately smaller than EXAMPLE above.
# The example is documentation, so it shows four kinds of output; a starter must
# not name one device the reader does not own, because an output pointed at a
# speaker nobody has is an error at every single prayer time.
STARTER = """\
# muezzin profile. Everything here is data: change a number, not the code.
#
# The three lines under `location` are a placeholder for New York. Until they
# say where you are, every time this program produces is New York's, and the
# arithmetic will not complain about that, so change them first.

location:
  latitude: 40.7128            # your latitude, north positive
  longitude: -74.006           # your longitude, east positive
  timezone: America/New_York   # IANA name: DST is handled by the tz database

method:
  preset: isna                 # `muezzin methods` lists the presets and their angles
  asr_shadow: standard         # standard | hanafi
  # one number at a time, to match the table your community publishes:
  # fajr_angle: 15.0
  # isha_angle: 15.0
  # maghrib_angle_offset: 3.7  # e.g. the Tehran institute's maghrib

adjustments: {fajr: 0, dhuhr: 5, maghrib: 0}   # minutes, per prayer

media_dir: media               # drop your adhan recordings in here
http_port: 8010                # serves media_dir to Cast devices
hijri_offset: 0                # display only: lines the page up with your calendar

# No speakers listed yet, on purpose: an output pointed at a speaker nobody owns
# is an error at every single prayer time. `muezzin devices` asks the network
# what is there, and the page's "look again" then "use" writes the entry for you.
# A scan by itself changes nothing, so this list is only ever what you chose. The
# shortest entry of all is `kind: pc_speakers`, for the speakers already attached
# to the machine this file is on: it needs a name and nothing else. To write one
# by hand, delete the `# ` marks on the four lines below.
outputs:
  # - name: house-group            # a name you choose; the events below use these
  #   kind: google_cast            # or pc_speakers, lan_box, file
  #   target: Whole-house group    # spelled exactly as `muezzin devices` prints it
  #   volume: 0.5                  # the level on a speaker; a computer plays at its own

# An event with no `targets:` reaches every enabled output, which is what most
# households want: add a speaker and it joins the schedule this file already
# describes. Add `targets:` when one prayer should go somewhere narrower, and
# `days:` for a reminder that fires once a week.
#
# None of these five name a recording, and that is on purpose as well. `muezzin
# init` makes an empty media_dir, so a starter that said `media: [fajr.mp3]`
# hands over five appointments that fire on time into silence, with no error
# anywhere and the only proof a line in a log nobody reads at 5 am. Put a
# recording in that folder - the page's sound card does it - and then either name
# it (`media: [name.mp3]`) or let the prayer draw from whatever the folder holds
# (`random: 1`). The page's prayer rows write both of those for you.
events:
  - name: fajr-adhan
    at: fajr
  - name: dhuhr-adhan
    at: dhuhr
  - name: asr-adhan
    at: asr
  - name: maghrib-adhan
    at: maghrib
  - name: isha-adhan
    at: isha
"""


def starter_text(media_dir: str = "") -> str:
    """The starter profile, with its `media_dir` line pointed at a folder you name.

    The default stays relative on purpose: a profile that moves with its folder
    keeps finding its recordings. A container is the case where that default lands
    in the wrong place, because the audio is mounted at a fixed path outside the
    config volume, so the image says where the mount is instead of handing over a
    starter pointed at an empty directory.
    """
    if not media_dir:
        return STARTER
    return STARTER.replace("media_dir: media", f"media_dir: {media_dir}", 1)


def starter_warnings(profile: Profile) -> list[str]:
    """Say once, in plain words, the three things a starter profile makes easy to
    miss: a city nobody chose, a schedule with nowhere to play, and a schedule with
    nothing to play."""
    notes = []
    if uses_starter_location(profile.location):
        notes.append(f"location is still the starter's placeholder "
                     f"({STARTER_LATITUDE}, {STARTER_LONGITUDE}, {STARTER_TIMEZONE}): "
                     f"every time here is New York's until those three lines change "
                     f"(`muezzin where <city> --write` writes a city centre into them)")
    if not profile.outputs:
        notes.append("no speakers configured: `muezzin devices` shows what is on the "
                     "network and the panel adds one (or write an outputs: entry). An "
                     "event with no targets reaches every enabled output")
    elif not profile.enabled_outputs():
        notes.append(f"all {len(profile.outputs)} configured outputs are disabled: "
                     f"nothing will play")
    if profile.nothing_assigned():
        notes.append("nothing is assigned to play yet: no event names a recording and none "
                     "draws at random, so every appointment in this schedule fires into "
                     "silence (put a recording in media_dir, then give an event "
                     "`media: [name.mp3]` or `random: 1`)")
    return notes


def _fmt(h):
    if h is None:
        return "  --  "
    day = ""
    if h >= 24.0:
        day, h = "+1", h - 24.0
    elif h < 0:
        day, h = "-1", h + 24.0
    m = int(round((h % 1) * 60))
    if m == 60:
        # 23.9999 rounds up to a whole hour: the clock rolls over to 00:00 and the
        # day marker has to follow it, or the table says today at midnight
        h, m = h + 1, 0
        if h >= 24.0:
            h -= 24.0
            day = day or "+1"
    return f"{int(h) % 24:02d}:{m:02d}{day}"


def cmd_times(profile: Profile, date, days: int) -> int:
    keys = ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha", "midnight", "true_night"]
    print(f"# {profile.params.label}  asr={'hanafi' if profile.asr_shadow == 2.0 else 'standard'}")
    print(f"# {profile.location.latitude}, {profile.location.longitude} {profile.location.timezone}"
          f"  (hl rule: {profile.params.high_latitude_rule})")
    # stderr, so a table that is piped somewhere stays a table
    for note in starter_warnings(profile):
        print(f"# note: {note}", file=sys.stderr)
    print("date        " + "".join(f"{k[:8]:>9}" for k in keys))
    from .scheduler import clock_hours
    for i in range(days):
        d = date + dt.timedelta(days=i)
        t = calc.compute_times(profile.location, d, profile.params,
                               asr_shadow=profile.asr_shadow, adjustments=profile.adjustments)
        # The calculation measures a day against one civil offset; a table people read
        # has to say what their clocks will show, which is the same thing except on the
        # days the zone moves its own clock.
        hours = clock_hours(t, profile.location.timezone)
        print(f"{t.date}  " + "".join(f"{_fmt(hours.get(k)):>9}" for k in keys))
    return 0


def cmd_methods() -> int:
    width = max(len(k) for k in calc.PRESETS)
    for key, p in sorted(calc.PRESETS.items()):
        isha = f"isha {p.isha_angle} deg" if p.isha_angle is not None else f"isha +{p.isha_interval} min"
        # Which way the night ends, printed on every row. Naming only the Ja'fari rows
        # would leave the others described by an absence, which is how a list of
        # methods starts reading as one school's list.
        night = "night ends at Fajr" if p.midnight_from_fajr else "night ends at sunrise"
        print(f"{key:<{width}}  fajr {p.fajr_angle} deg   {isha:<20}  {p.label}  {night}")
    print("\nOverride any single value in the profile's `method:` block; the preset is a starting point.")
    return 0


def cmd_where(city: str | None, config: Path, write: bool, online: bool = False,
              coords: str | None = None, choose: int = 0, postcode: str = "") -> int:
    """Look up the coordinates and the civil clock behind a place.

    This is the first step of a profile, so it is also the first thing worth
    getting right on purpose rather than by default: the starter's placeholder
    location is a real city's coordinates, and a timetable computed from them
    looks exactly as plausible as yours.

    Three doors, in the order it is worth trying them. The table offline answers for a
    city and costs nothing. `--coords` answers for numbers you already have, also
    offline, by naming the cities nearest to them - which is how a transposed coordinate
    gets caught before it quietly becomes somebody else's timetable. `--online` asks
    OpenStreetMap, which answers for a street rather than only a city, at the cost of
    sending the words someone typed to a machine that is not on this network; so it is
    asked for by name, never reached for on its own.

    With `--online`, `--postcode` goes with the words in place of the name of a town,
    which measured is the difference between the door asked for and several stretches of
    a street that are not it.
    """
    if postcode and not online and not coords:
        print("# note: --postcode goes with --online only. The offline table knows city "
              "names, and a code is not a city name.", file=sys.stderr)
    if coords:
        return _where_coords(coords, config, write, online)
    if online:
        return _where_online(city, config, write, choose, postcode)
    if not city:
        print(f"`muezzin where <city>` prints the coordinates and time zone behind a city "
              f"name, offline, from a table of {len(places.PLACES)} city centres.")
        print("Names are matched without case, and the region is optional: `orlando` and "
              "`london ontario` both work. Two cities share a name, so `london` asks you "
              "which one instead of choosing for you.")
        print("A time zone only labels the clock. Orlando, Florida and Erie, Pennsylvania "
              "are both America/New_York, and their fajr and maghrib land at different "
              "clock times because the sun sits at a different angle over each of them.")
        print("`--coords 42.1292,-80.0851` says what a set of numbers means by naming the "
              "cities nearest to it, still offline. `--online` asks OpenStreetMap for a "
              "street rather than a city: the only request this program makes away from "
              "your own network, needs no account and no key, and keeps nothing.")
        return 0

    hits = places.find(city)
    if not hits:
        stem = city.strip().casefold()[:4]
        near = [p.label for p in places.PLACES if stem in p.label.casefold()]
        print(f"no city centre called {city!r} in the table"
              + (f"; closest: {', '.join(near[:6])}" if near else ""), file=sys.stderr)
        print("That is fine: write your own latitude, longitude and timezone into the "
              "profile. This table is a starting point, not an index of the world.",
              file=sys.stderr)
        return 2
    if len(hits) > 1:
        print(f"{city!r} matches more than one city, and picking one silently would put "
              "your times somewhere else entirely:", file=sys.stderr)
        for place in hits:
            print(f"  muezzin where \"{place.label}\"", file=sys.stderr)
        return 2

    place = hits[0]
    print(f"{place.label}:  latitude {place.latitude}, longitude {place.longitude}, "
          f"timezone {place.timezone}")
    print("# the coordinates move the times; the time zone only names the clock they land on")
    if not write:
        print(f"# to put those three lines into {config}: "
              f"muezzin where --write \"{place.label}\"")
        return 0

    return _write_location(config, place.as_config())


def _write_location(config: Path, values: dict) -> int:
    """Put the three location lines into a profile, once they are known to load.

    Only that block's lines are rewritten, because the comments in a profile are part of
    the profile: they are what tells someone six months later that the time zone only
    labels the clock. And the file is only replaced after the result has been loaded,
    because a location line that does not parse is worse than no new location at all.
    """
    if not config.exists():
        print(f"{config} not found: run `muezzin init` first, or name the profile with -c",
              file=sys.stderr)
        return 2
    original = config.read_bytes()
    text = original.decode("utf-8")
    try:
        edited = yamledit.set_in_block(text, "location", values)
    except ValueError as exc:
        print(f"{config}: {exc}", file=sys.stderr)
        return 2
    fd, name = tempfile.mkstemp(dir=str(config.parent or "."),
                                prefix=config.name + ".", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(edited)
        try:
            probe = load_profile(tmp)
        except (KeyError, ValueError, TypeError, yaml.YAMLError) as exc:
            print(f"not writing {config}: the result would not load. {exc}", file=sys.stderr)
            return 2
    finally:
        tmp.unlink(missing_ok=True)

    # A profile checked out on Windows uses CRLF; keep it that way so this is one
    # changed line in a diff instead of the whole file.
    data = edited.replace("\r\n", "\n").replace("\n", "\r\n") if b"\r\n" in original else edited
    config.write_bytes(data.encode("utf-8"))
    print(f"# wrote that to {config}")
    if uses_starter_location(probe.location):
        print("# note: this is the same city the starter profile guesses, so the page will "
              "still say the location was never chosen. Put your own street's numbers in "
              "when you want the times for where you actually stand.")
    return 0


def _where_online(text: str | None, config: Path, write: bool, choose: int,
                  postcode: str = "") -> int:
    """Ask OpenStreetMap's Nominatim, and be exact about what that asked for.

    A lookup answers for a street, which the offline table cannot. What it costs is that
    the words someone typed - often their own street - travel to a machine that is not on
    their network. That is worth doing knowingly and not by default, so the price is
    printed before the question is sent, and nothing about the question is kept here.
    """
    if not text and not postcode:
        print('`muezzin where --online "1200 Peach Street, Erie, PA"` asks OpenStreetMap '
              "for a place, which answers for a street and not only for a city in the "
              "offline table.", file=sys.stderr)
        print('`muezzin where --online "1200 Peach Street" --postcode 16508` asks with the '
              "postal code in place of the name of a town. Measured on the public lookup, a "
              "line naming a town answered with five stretches of the street and none of "
              "them the door asked for, while the same words with the code answered with "
              "the door itself.")
        print("No account and no key are needed. The words you type go to them; nothing is "
              "saved here about the question, and the request carries only the name of the "
              "program that is asking.")
        return 2
    asked = text or postcode
    code = f' --postcode "{postcode}"' if postcode else ""
    # A code on its own is a whole ask, so the line printed back to type has to leave the
    # quotes out rather than ask for the same code twice.
    quote = f' "{text}"' if text else ""
    print(f"# asking {geocode.provider()}: the words you typed leave this network, and "
          "nothing here keeps a record of them")
    try:
        hits = geocode.search(text, postcode)
    except geocode.GeocodeError as exc:
        # The message says what went wrong without repeating the place asked about,
        # because this line ends up in terminals and bug reports.
        print(f"the lookup did not answer: {exc}", file=sys.stderr)
        return 2
    if not hits:
        again = geocode.shorter(text or "")
        print(f"{geocode.provider()} found nothing called {asked!r}. A whole address is one "
              "hard question for a lookup: the street can be in the map, and the number on "
              "it, and the answer still empty, because a street is filed under the place it "
              "sits in rather than under the town name people put in a posting address.",
              file=sys.stderr)
        if not postcode:
            print("# a postal code answers where the name of a town stops the answer, so "
                  'the street plus "--postcode 16508" is the other way in.',
                  file=sys.stderr)
        if again:
            print(f'# ask with the words before the town: muezzin where --online{code} '
                  f'"{again}"', file=sys.stderr)
            print("# read the label before writing anything down: with fewer words a "
                  "street of the same name in another town answers just as happily.",
                  file=sys.stderr)
        return 2
    if len(hits) > 1 and not choose:
        print(f"{asked!r} could be more than one place, and choosing between two of them "
              "is not this program's call to make:", file=sys.stderr)
        for number, hit in enumerate(hits, 1):
            clock = hit.timezone or f"no time zone: {hit.zone_note}"
            print(f"  {number}) {hit.label}   {hit.latitude}, {hit.longitude}   {clock}",
                  file=sys.stderr)
        print(f'# then: muezzin where --online{code} --choose N --write{quote}',
              file=sys.stderr)
        return 2
    if choose:
        if not 1 <= choose <= len(hits):
            print(f"--choose {choose} is not one of the {len(hits)} answers it gave",
                  file=sys.stderr)
            return 2
        hit = hits[choose - 1]
    else:
        hit = hits[0]
    print(f"{hit.label}:  latitude {hit.latitude}, longitude {hit.longitude}")
    print(f"# {hit.zone_note}")
    if hit.timezone:
        print(f"# timezone {hit.timezone}")
    print("# the coordinates move the times; the time zone only names the clock they land on")
    if not write:
        picked = f"--choose {choose} " if choose else ""
        print(f"# to put those three lines into {config}: "
              f"muezzin where --online{code} {picked}--write{quote}")
        return 0
    try:
        values = hit.as_config()
    except geocode.GeocodeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return _write_location(config, values)


def _pair_coords(argv: list[str]) -> list[str]:
    """Let someone south of the equator type their own latitude.

    argparse reads a value that begins with a dash as another flag, so
    `--coords -33.8683,151.2093` would be answered with "expected one argument" -
    a complaint about Sydney, Australia, from a program asking for a place. The
    fix is the spelling argparse accepts, done on its behalf: the pair is joined
    to the option with an equals sign.
    """
    fixed = list(argv)
    index = 0
    while index < len(fixed):
        if (fixed[index] == "--coords" and index + 1 < len(fixed)
                and fixed[index + 1].startswith("-") and "," in fixed[index + 1]):
            fixed[index] = f"--coords={fixed[index + 1]}"
            del fixed[index + 1]
        index += 1
    return fixed


def _two_numbers(text: str) -> tuple[float, float]:
    """Read `42.1292,-80.0851`, the way a map page or a phone shows it, and nothing else.

    Out-of-range values are refused rather than clamped: a latitude of 91 is a copy-paste
    mistake, and a timetable built from a clamped 90 would be wrong in a way that is very
    hard to notice.
    """
    parts = [part.strip() for part in text.replace(";", ",").split(",")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"{text!r} is not two numbers with a comma between them")
    try:
        latitude, longitude = (float(part) for part in parts)
    except ValueError:
        raise ValueError(f"{text!r} is not two numbers") from None
    if not (abs(latitude) <= 90.0 and abs(longitude) <= 180.0):
        raise ValueError("latitude goes from -90 to 90 and longitude from -180 to 180")
    return latitude, longitude


def _where_coords(coords: str, config: Path, write: bool, online: bool) -> int:
    """Say what a set of numbers is near, with no request to anybody unless asked.

    The mistake this exists for: a coordinate copied from a form, a phone, or a different
    city's page, which loads into a profile and produces a timetable that looks perfectly
    normal for the wrong place. Naming the nearest cities and how far away they are makes
    it obvious at the moment it is typed.
    """
    try:
        latitude, longitude = _two_numbers(coords)
    except ValueError as exc:
        print(f"{exc}. Write them as muezzin where --coords \"42.1292,-80.0851\", north "
              "positive and east positive.", file=sys.stderr)
        return 2
    print(f"those numbers are latitude {latitude}, longitude {longitude}")
    near = geocode.nearest_named(latitude, longitude, 3)
    for row in near:
        print(f"  {row['name']}:  {row['km']:,.0f} km away, bearing {row['bearing']:.0f} "
              "degrees from true north")
    if near and near[0]["km"] > geocode.FAR_KM:
        print(f"# that is a long way from anywhere muezzin can name: the nearest city in "
              f"the table is {near[0]['name']}, {near[0]['km']:,.0f} km away. If you did "
              "not mean somewhere that remote, a number has been transposed or copied from "
              "the wrong place.", file=sys.stderr)
    zone = None
    why = "no city in the table is near enough to lend its clock"
    if near and near[0]["km"] <= geocode.ZONE_NEAR_KM:
        zone = near[0]["timezone"]
        why = f"borrowed from {near[0]['name']}, {near[0]['km']:,.0f} km away"
    if online:
        print(f"# asking {geocode.provider()} what it calls those numbers")
        try:
            hits = geocode.reverse(latitude, longitude)
        except geocode.GeocodeError as exc:
            print(f"the map did not answer: {exc}", file=sys.stderr)
            hits = []
        for hit in hits[:3]:
            print(f"  the map calls it: {hit.label}")
        if hits and hits[0].timezone:
            zone, why = hits[0].timezone, "the lookup named this zone"
    if not write:
        print(f"# to put those three lines into {config}: muezzin where --coords "
              f"\"{latitude},{longitude}\" --write"
              + ("" if online else "   # add --online to ask the map what is there"))
        return 0
    if not zone:
        print("no time zone could be agreed for those numbers: no city in the table is "
              "nearby and the map did not name one. Write the timezone line yourself; the "
              "two coordinates are good.", file=sys.stderr)
        return 2
    print(f"# timezone {zone}  # {why}")
    return _write_location(config, {"latitude": latitude, "longitude": longitude,
                                    "timezone": zone})


def cmd_devices(timeout: float) -> int:
    from .backends import scan_speakers

    found = scan_speakers(timeout)
    speakers, groups, boxes = found["speakers"], found["groups"], found["boxes"]
    if not speakers and not boxes:
        print("no Cast/Nest speakers and no muezzin boxes found. Check both machines are on the "
              "same LAN/subnet, that mDNS is not blocked (common on 'public' network profiles in "
              "Windows; on macOS, allow incoming connections when the firewall asks), and that "
              "the Wi-Fi is not client-isolated.")
        return 1
    if speakers or groups:
        print(f"{'speaker / group':<28} {'model':<26} {'group':<6} address")
        for d in groups + speakers:
            print(f"{d['name'][:28]:<28} {d['model'][:26]:<26} {'yes' if d['group'] else '-':<6} "
                  f"{d['address']}:{d['port']}")
            if not d["group"]:
                continue
            # the group's own announcement names only the speaker running it, so the
            # members are read back from the speakers themselves (see backends.py)
            members = d.get("members") or []
            if not d.get("membership_known"):
                note = "members: unknown, those speakers did not answer"
            elif members:
                note = "members: " + ", ".join(members)
            else:
                note = "members: nobody claimed it"
            print(" " * 34 + note)
        print("\n  -> use the name as `target:` on an output of kind google_cast\n")
    if boxes:
        print(f"{'box':<28} {'protocol':<16} {'player':<10} address")
        for b in boxes:
            print(f"{b['name'][:28]:<28} {b['kind']:<16} {b['player'][:10]:<10} "
                  f"{b['address']}:{b['port']}")
        print("\n  -> use the address as `host:` on an output of kind lan_box "
              "(an muezzin box you can start with `muezzin box`)")
    return 0


def cmd_box(name: str, port: int, player: str | None, allow_hosts: tuple[str, ...] = ()) -> int:
    from .box import Box

    box = Box(name, port, player, allow_hosts)
    if box.player_name == "none":
        print(f"warning: no player found on this machine.\n{localplay.install_advice()}\n"
              "      Pass --player 'your-command' if you have one under another name.",
              file=sys.stderr)
    if not allow_hosts:
        print("note: this box will not fetch URLs. Add --allow-host <address of the machine\n"
              "      that serves your media> if the daemon should hand it URLs instead of bytes.",
              file=sys.stderr)
    print(f"muezzin box {name!r} on port {port} (player: {box.player_name}); Ctrl-C to stop")
    try:
        box.run_forever()
    except OSError as exc:
        return _port_busy(exc, f"the box {name!r}", port, "MUEZZIN_BOX_PORT", "`--port <port>`")
    except KeyboardInterrupt:
        print("stopping")
    finally:
        box.shutdown()
    return 0


def _media_candidates(profile: Profile, name: str) -> list[Path]:
    """Where a media name from the command line could point: as typed, or inside media_dir."""
    p = Path(name)
    if p.is_absolute():
        return [p]
    return [p, profile.media_dir / p]


def _resolve_media(profile: Profile, name: str) -> Path:
    for cand in _media_candidates(profile, name):
        if cand.exists():
            return cand
    return Path(name)


def _describe_candidates(profile: Profile, name: str) -> str:
    return ", ".join(str(c) for c in _media_candidates(profile, name))


def cmd_play_now(profile: Profile, names: list[str], media: list[str], volume) -> int:
    from . import backends as B
    from .media import MediaServer

    targets = [profile.output(n) for n in names] if names else profile.enabled_outputs()
    targets = [t for t in targets if t]
    if not targets:
        print(f"no such output(s): {names}. Configured: "
              f"{', '.join(o.name for o in profile.outputs)}", file=sys.stderr)
        return 2
    files = [_resolve_media(profile, m) for m in media]
    missing = [f"{m} (tried {_describe_candidates(profile, m)})" for m, f in zip(media, files) if not f.exists()]
    if missing:
        print("media not found:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 2

    needs_urls = any(getattr(B.KINDS.get(t.kind), "needs_urls", False) for t in targets)
    server = MediaServer(profile.media_dir, profile.http_port) if needs_urls else None
    if server:
        server.start()
    try:
        for t in targets:
            try:
                B.build(t, server).play(files, volume)
                print(f"played on {t.name} ({t.kind})")
            except Exception as exc:
                print(f"FAILED on {t.name} ({t.kind}): {exc}", file=sys.stderr)
                return 1
    finally:
        if server:
            server.stop()
    return 0


def cmd_next(profile: Profile, days: int) -> int:
    """Show what the daemon would actually do: events, wall clock, targets, media."""
    from zoneinfo import ZoneInfo

    from .scheduler import lead_of, upcoming

    rows = upcoming(profile, days=days)
    tz = profile.location.timezone
    now = dt.datetime.now(ZoneInfo(tz))
    print(f"# now {now:%Y-%m-%d %H:%M} {tz}   method: {profile.params.label}")
    # `next` is the command that gets trusted, so it says why a row reads NO TARGETS
    for note in starter_warnings(profile):
        print(f"# note: {note}", file=sys.stderr)
    if not rows:
        print("nothing scheduled in this window - check the `events:` block "
              "(and `days:` here, currently asking for the next", days, "day(s)")
        return 1
    for sev in rows:
        targets = profile.targets_for(sev.event)
        names = ", ".join(f"{t.name}" for t in targets) or "NO TARGETS"
        # Say out loud that the sound starts before the printed time, and by how
        # much: this is the command people trust, so a call that goes out a few
        # seconds early should read as a decision and not as a surprise.
        early = lead_of(targets)
        note = f" (played {early:g} s early)" if early > 0 else ""
        # An event that draws from the library cannot name the recordings it will play,
        # because the drawing does not happen until the event fires. Say what it does
        # instead of printing an empty bracket, which reads as a mistake rather than as
        # a plan - and name the ones it does promise, since those are fixed.
        picks = " ".join(sev.event.media)
        if sev.event.random:
            picks = (picks + " + " if picks else "") + f"{sev.event.random} at random"
        print(f"{sev.when:%a %d %b %H:%M}  {sev.event.name:<16} -> {names}{note}"
              f"   [{picks}]")
    return 0


def panel_address(host: str, port: int, read_only: bool) -> str:
    """The address to type into a browser, and the one thing a container adds.

    The media server names the interface this process can see, which inside a
    container is the container's own - often 127.0.0.1 - and a phone in the next
    room has no route to it. A log line whose whole job is to tell somebody where
    to point their browser cannot be allowed to be a mystery in the first minute of
    an install, which is when it gets read.
    """
    where = f"http://{host}:{port}{' (read-only)' if read_only else ''}"
    if host in ("127.0.0.1", "::1", "localhost"):
        return (f"{where}\n  that is this machine's own address; from another device use this "
                f"machine's address on your network at port {port} (a container run with "
                f"--network host answers there)")
    return where


def cmd_daemon(config_path: Path, web_port=None, read_only: bool = False,
               allow_hosts: tuple[str, ...] = ()) -> int:
    from .scheduler import Runner

    profile = load_profile(config_path)
    try:
        runner = Runner(profile)      # the media server binds its port in here
    except OSError as exc:
        return _port_busy(exc, "the media server", profile.http_port, "MUEZZIN_HTTP_PORT",
                          "`http_port:` in the profile")
    panel = None
    if web_port is not None:
        from .web import WebPanel

        panel = WebPanel(runner, port=web_port, allow_edit=not read_only,
                         allow_hosts=allow_hosts)
        try:
            panel.start()
        except OSError as exc:
            # The media server is already holding its port, and a daemon that walks
            # away without letting go of it leaves the next one failing on a port
            # nobody can see anyone using.
            runner.shutdown()
            return _port_busy(exc, "the control panel", web_port, "MUEZZIN_WEB_PORT",
                              "`--web <port>`")
    print(f"muezzin {__version__}: {profile.location.timezone} / {profile.params.label}; "
          f"outputs: {', '.join(o.name for o in profile.enabled_outputs())}")
    for note in starter_warnings(profile):
        log.warning("%s", note)
    if panel:
        host = runner.media.host_ip if runner.media else "127.0.0.1"
        print(f"control panel: {panel_address(host, panel.port, read_only)}")
    try:
        runner.run_forever()
    except KeyboardInterrupt:
        print("stopping")
    except Exception:
        # Come out non-zero on purpose. A service unit told to restart on failure
        # cannot restart what it was told exited cleanly, and an adhan that went
        # missing because the daemon fell over on Tuesday is the worst kind of
        # bug this program can have: the house finds out at Fajr.
        log.exception("the scheduler stopped")
        print("the scheduler stopped; see the log above", file=sys.stderr)
        return 1
    finally:
        if panel:
            panel.stop()
        runner.shutdown()
    return 0


def cmd_web(config_path: Path, port: int, read_only: bool,
            allow_hosts: tuple[str, ...] = ()) -> int:
    """Serve the control panel without running the scheduler - for editing a
    profile and checking times from a phone, e.g. while the real daemon runs on
    another machine."""
    from .scheduler import Runner
    from .web import WebPanel

    profile = load_profile(config_path)
    try:
        runner = Runner(profile)
    except OSError as exc:
        return _port_busy(exc, "the media server", profile.http_port, "MUEZZIN_HTTP_PORT",
                          "`http_port:` in the profile")
    panel = WebPanel(runner, port=port, allow_edit=not read_only, allow_hosts=allow_hosts)
    try:
        panel.start()
    except OSError as exc:
        runner.shutdown()
        return _port_busy(exc, "the control panel", port, "MUEZZIN_WEB_PORT", "`--port <port>`")
    host = runner.media.host_ip if runner.media else "127.0.0.1"
    print(f"muezzin {__version__}: {profile.params.label} at http://{host}:{panel.port}"
          f"{' (read-only)' if read_only else ''}")
    print("no scheduler here - use `muezzin daemon --web` to also play the adhan")
    try:
        panel.serve_forever()
    except KeyboardInterrupt:
        print("stopping")
    finally:
        panel.stop()
        runner.shutdown()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="muezzin", description=__doc__)
    ap.add_argument("--version", action="version", version=f"muezzin {__version__}")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="debug logging: shows every media URL a speaker fetched, "
                         "which is how you tell a firewall problem from a dead speaker")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # A port may be named in the environment, which is the only knob a container
    # has when the image already chose the arguments it runs with. The variables
    # change which number a port gets, never whether the page runs at all: an
    # unauthenticated page turning up because a variable was set in somebody's
    # shell profile is not the sort of thing to discover by accident.
    try:
        web_env = _env_port("MUEZZIN_WEB_PORT")
        box_env = _env_port("MUEZZIN_BOX_PORT")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    # The three parsers below compare these against None rather than trusting them:
    # 0 is an answer, not an absence. It means "take a free port", which is the other
    # way a second muezzin on this machine avoids the first one's numbers.

    def add_config(p):
        p.add_argument("-c", "--config", type=Path, default=Path("muezzin.yaml"))

    p = sub.add_parser("times", help="print the computed timetable")
    add_config(p)
    p.add_argument("-d", "--date", type=lambda s: dt.date.fromisoformat(s), default=dt.date.today())
    p.add_argument("--days", type=int, default=1)

    sub.add_parser("methods", help="list calculation presets and their angles")

    p = sub.add_parser("where", help="look up the coordinates and time zone for a place")
    add_config(p)
    p.add_argument("city", nargs="?", help='city name: "orlando", "london ontario", "qom"')
    p.add_argument("--write", action="store_true",
                   help="put the answer into the profile's location: block, instead of "
                        "only printing it")
    p.add_argument("--coords", metavar="LAT,LON",
                   help="say what a set of numbers means, nearest known city first, so a "
                        "coordinate copied from somewhere can be checked. A pair south of "
                        "the equator is typed as it reads: --coords -33.87,151.21")
    p.add_argument("--online", action="store_true",
                   help="ask OpenStreetMap's Nominatim: answers for a street rather than "
                        "only a city, at the cost that the words you typed leave this "
                        "network. Nothing is kept, nothing needs an account or a key")
    p.add_argument("--postcode", default="", metavar="CODE",
                   help="with --online, the code travels with the words in place of the "
                        'name of a town: --online "2456 w 12th st" --postcode 16508 '
                        "answered with the door itself, where the same words naming a town "
                        "answered with five stretches of street and none of them the door. "
                        "A code on its own finds the whole code area, and one code can "
                        "exist in two countries")
    p.add_argument("--choose", type=int, default=0, metavar="N",
                   help="take answer number N when the lookup answers more than one place")

    p = sub.add_parser("next", help="show the next events the daemon will fire, and to what")
    add_config(p)
    p.add_argument("--days", type=int, default=2)

    p = sub.add_parser("devices", help="scan the LAN for speakers, groups and speaker boxes")
    p.add_argument("--timeout", type=float, default=4.0)

    p = sub.add_parser("play-now", help="test playback through configured outputs")
    add_config(p)
    # append, not nargs="*": a greedy option would eat the media paths that follow it
    p.add_argument("--to", action="append", default=[], metavar="OUTPUT",
                   help="output name; repeat for several (default: all enabled)")
    p.add_argument("--volume", type=float, default=None,
                   help="the level for the Cast speakers in this playback; a computer - this "
                        "machine or a box on the LAN - plays at its own level")
    p.add_argument("media", nargs="*", help="files in media_dir (or absolute paths)")

    p = sub.add_parser("daemon", help="run the scheduler until stopped")
    add_config(p)
    p.add_argument("--web", nargs="?", type=int, const=8020 if web_env is None else web_env,
                   default=None, metavar="PORT",
                   help="also serve the browser control panel; a bare --web means port "
                        "8020, or MUEZZIN_WEB_PORT when that is set")
    p.add_argument("--read-only", action="store_true",
                   help="the web panel may show state but not save config or play test files")
    p.add_argument("--allow-host", action="append", type=_host_arg, default=[], metavar="NAME",
                   help="extra name the panel answers to, if you reach it by a hostname; "
                        "repeat for more than one")

    p = sub.add_parser("web", help="serve the control panel only, without the scheduler")
    add_config(p)
    p.add_argument("--port", type=int, default=8020 if web_env is None else web_env,
                   help="the port to answer on: 8020, or MUEZZIN_WEB_PORT if that is set")
    p.add_argument("--read-only", action="store_true")
    p.add_argument("--allow-host", action="append", type=_host_arg, default=[], metavar="NAME",
                   help="extra name the panel answers to, if you reach it by a hostname; "
                        "repeat for more than one")

    p = sub.add_parser("box", help="run the speaker agent on a Pi or a second machine")
    p.add_argument("--name", default="muezzin-box", help="name to advertise on the LAN")
    p.add_argument("--port", type=int, default=8090 if box_env is None else box_env,
                   help="the port this box answers on: 8090, or MUEZZIN_BOX_PORT if set. "
                        "Two boxes on one machine need different ports and different names")
    p.add_argument("--player", default=None,
                   help="command that plays one file (default: what this machine already has)")
    p.add_argument("--allow-host", action="append", type=_host_arg, default=[], metavar="ADDRESS",
                   help="address this box may fetch a recording from; repeat per machine, or "
                        "name .example.com to cover that domain. Without it the box only "
                        "accepts files sent to it directly")

    p = sub.add_parser("init", help="write a starter profile")
    p.add_argument("-c", "--config", type=Path, default=Path("muezzin.yaml"))
    p.add_argument("--media-dir", default="", metavar="PATH",
                   help="where the adhan recordings live, written into the profile as "
                        "media_dir; default is a folder called media next to the profile")

    # A latitude that starts with a dash is a place, not a switch: see _pair_coords.
    argv = _pair_coords(sys.argv[1:] if argv is None else list(argv))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "init":
        if args.config.exists():
            print(f"{args.config} already exists; not overwriting", file=sys.stderr)
            return 1
        folder = Path(args.media_dir) if args.media_dir else args.config.parent / "media"
        # A profile asked for in a folder that does not exist yet is a plan or a
        # typo, and either way the answer is the folder, not a traceback about it.
        args.config.parent.mkdir(parents=True, exist_ok=True)
        folder.mkdir(parents=True, exist_ok=True)
        args.config.write_text(starter_text(args.media_dir), encoding="utf-8")
        print(f"wrote {args.config} (and a {folder} directory - drop your adhan files in it)")
        print("no speakers are configured: run `muezzin where <city> --write` to say where "
              "you are, then `muezzin devices` to see what is on the network and add a "
              "speaker from the panel")
        # The other half of a first install, said at the moment it is true. The
        # events in this file name no recording on purpose - the folder just made
        # beside them is empty - and the version that named five recordings instead
        # produced a week of silent mornings on a machine where everything else was
        # configured correctly.
        print("nothing is assigned to play yet: the adhans in this file name no recording, "
              "because the media folder is empty. Put a recording in it, then give one "
              "prayer that name or press random on the page's prayer rows")
        return 0
    if args.cmd == "methods":
        return cmd_methods()
    if args.cmd == "where":
        return cmd_where(args.city, args.config, args.write, args.online,
                         args.coords, args.choose, args.postcode)
    if args.cmd == "devices":
        return cmd_devices(args.timeout)
    if args.cmd == "box":
        return cmd_box(args.name, args.port, args.player, tuple(args.allow_host))

    try:
        profile = load_profile(args.config)
    except FileNotFoundError:
        print(f"{args.config} not found. Run `muezzin init` to create one.", file=sys.stderr)
        return 2
    except yaml.YAMLError as exc:
        print(f"{args.config}: that is not readable YAML. {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # a directory where a profile was expected, or a file nobody can open
        print(f"{args.config}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    except (KeyError, ValueError) as exc:
        print(f"{args.config}: {exc}", file=sys.stderr)
        return 2

    if args.cmd == "times":
        return cmd_times(profile, args.date, args.days)
    if args.cmd == "next":
        return cmd_next(profile, args.days)
    if args.cmd == "play-now":
        return cmd_play_now(profile, args.to, args.media, args.volume)
    if args.cmd == "daemon":
        return cmd_daemon(args.config, args.web, args.read_only, tuple(args.allow_host))
    if args.cmd == "web":
        return cmd_web(args.config, args.port, args.read_only, tuple(args.allow_host))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
