"""muezzin command line."""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import tempfile
from pathlib import Path

import yaml

from . import __version__, calc, places, yamledit
from .config import (STARTER_LATITUDE, STARTER_LONGITUDE, STARTER_TIMEZONE, OutputConfig,
                     Profile, load_profile, uses_starter_location, valid_host)

log = logging.getLogger("muezzin.cli")


def _host_arg(value: str) -> str:
    """A --allow-host value, checked where it is typed rather than at the point
    where it silently stops matching anything."""
    if not valid_host(value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a plain hostname or IP address")
    return value

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
    kind: pc_speakers
    volume: 0.7
  - name: study
    kind: google_cast
    target: Study speaker      # `muezzin devices` lists names, groups included
    volume: 0.5
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
    volume: 0.8
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
  #   volume: 0.5

# An event with no `targets:` reaches every enabled output, which is what most
# households want: add a speaker and it joins the schedule this file already
# describes. Add `targets:` when one prayer should go somewhere narrower, and
# `days:` for a reminder that fires once a week.
events:
  - name: fajr-adhan
    at: fajr
    media: [fajr.mp3]
  - name: dhuhr-adhan
    at: dhuhr
    media: [dhuhr.mp3]
  - name: asr-adhan
    at: asr
    media: [asr.mp3]
  - name: maghrib-adhan
    at: maghrib
    media: [maghrib.mp3]
  - name: isha-adhan
    at: isha
    media: [isha.mp3]
"""


def starter_warnings(profile: Profile) -> list[str]:
    """Say once, in plain words, the two things a starter profile makes easy to
    miss: a city nobody chose, and a schedule with nowhere to play."""
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
    for i in range(days):
        d = date + dt.timedelta(days=i)
        t = calc.compute_times(profile.location, d, profile.params,
                               asr_shadow=profile.asr_shadow, adjustments=profile.adjustments)
        print(f"{t.date}  " + "".join(f"{_fmt(getattr(t, k)):>9}" for k in keys))
    return 0


def cmd_methods() -> int:
    width = max(len(k) for k in calc.PRESETS)
    for key, p in sorted(calc.PRESETS.items()):
        isha = f"isha {p.isha_angle} deg" if p.isha_angle is not None else f"isha +{p.isha_interval} min"
        extra = "  jafari-midnight" if p.midnight_from_fajr else ""
        print(f"{key:<{width}}  fajr {p.fajr_angle} deg   {isha:<20}  {p.label}{extra}")
    print("\nOverride any single value in the profile's `method:` block; the preset is a starting point.")
    return 0


def cmd_where(city: str | None, config: Path, write: bool) -> int:
    """Look up the coordinates and the civil clock behind a city name.

    This is the first step of a profile, so it is also the first thing worth
    getting right on purpose rather than by default: the starter's placeholder
    location is a real city's coordinates, and a timetable computed from them
    looks exactly as plausible as yours.
    """
    if not city:
        print(f"`muezzin where <city>` prints the coordinates and time zone behind a city "
              f"name, offline, from a table of {len(places.PLACES)} city centres.")
        print("Names are matched without case, and the region is optional: `orlando` and "
              "`london ontario` both work. Two cities share a name, so `london` asks you "
              "which one instead of choosing for you.")
        print("A time zone only labels the clock. Orlando, Florida and Erie, Pennsylvania "
              "are both America/New_York, and their fajr and maghrib land at different "
              "clock times because the sun sits at a different angle over each of them.")
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

    if not config.exists():
        print(f"{config} not found: run `muezzin init` first, or name the profile with -c",
              file=sys.stderr)
        return 2
    original = config.read_bytes()
    text = original.decode("utf-8")
    try:
        edited = yamledit.set_in_block(text, "location", place.as_config())
    except ValueError as exc:
        print(f"{config}: {exc}", file=sys.stderr)
        return 2
    # Same rule as the panel: the file is only replaced once the result is known
    # to load. A location line that does not parse is worse than no new location.
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


def cmd_devices(timeout: float) -> int:
    from .backends import scan_speakers

    found = scan_speakers(timeout)
    speakers, groups, boxes = found["speakers"], found["groups"], found["boxes"]
    if not speakers and not boxes:
        print("no Cast/Nest speakers and no muezzin boxes found. Check both machines are on the "
              "same LAN/subnet, that mDNS is not blocked (common on 'public' network profiles in "
              "Windows), and that the Wi-Fi is not client-isolated.")
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
        print("warning: no command-line player found (tried mpg123, ffplay, cvlc, aplay).\n"
              "On a Pi: sudo apt install mpg123     or pass --player 'your-command'", file=sys.stderr)
    if not allow_hosts:
        print("note: this box will not fetch URLs. Add --allow-host <address of the machine\n"
              "      that serves your media> if the daemon should hand it URLs instead of bytes.",
              file=sys.stderr)
    print(f"muezzin box {name!r} on port {port} (player: {box.player_name}); Ctrl-C to stop")
    try:
        box.run_forever()
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

    from .scheduler import upcoming

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
        print(f"{sev.when:%a %d %b %H:%M}  {sev.event.name:<16} -> {names}"
              f"   [{' '.join(sev.event.media)}]")
    return 0


def cmd_daemon(config_path: Path, web_port=None, read_only: bool = False,
               allow_hosts: tuple[str, ...] = ()) -> int:
    from .scheduler import Runner

    profile = load_profile(config_path)
    runner = Runner(profile)
    panel = None
    if web_port is not None:
        from .web import WebPanel

        panel = WebPanel(runner, port=web_port, allow_edit=not read_only,
                         allow_hosts=allow_hosts)
        panel.start()
    print(f"muezzin {__version__}: {profile.location.timezone} / {profile.params.label}; "
          f"outputs: {', '.join(o.name for o in profile.enabled_outputs())}")
    for note in starter_warnings(profile):
        log.warning("%s", note)
    if panel:
        host = runner.media.host_ip if runner.media else "127.0.0.1"
        print(f"control panel: http://{host}:{panel.port}"
              f"{' (read-only)' if read_only else ''}")
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
    runner = Runner(profile)
    panel = WebPanel(runner, port=port, allow_edit=not read_only, allow_hosts=allow_hosts)
    panel.start()
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

    def add_config(p):
        p.add_argument("-c", "--config", type=Path, default=Path("muezzin.yaml"))

    p = sub.add_parser("times", help="print the computed timetable")
    add_config(p)
    p.add_argument("-d", "--date", type=lambda s: dt.date.fromisoformat(s), default=dt.date.today())
    p.add_argument("--days", type=int, default=1)

    sub.add_parser("methods", help="list calculation presets and their angles")

    p = sub.add_parser("where", help="look up a city's coordinates and time zone, offline")
    add_config(p)
    p.add_argument("city", nargs="?", help='city name: "orlando", "london ontario", "qom"')
    p.add_argument("--write", action="store_true",
                   help="put the answer into the profile's location: block, instead of "
                        "only printing it")

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
    p.add_argument("--volume", type=float, default=None)
    p.add_argument("media", nargs="*", help="files in media_dir (or absolute paths)")

    p = sub.add_parser("daemon", help="run the scheduler until stopped")
    add_config(p)
    p.add_argument("--web", nargs="?", type=int, const=8020, default=None, metavar="PORT",
                   help="also serve the browser control panel (bare --web means port 8020)")
    p.add_argument("--read-only", action="store_true",
                   help="the web panel may show state but not save config or play test files")
    p.add_argument("--allow-host", action="append", type=_host_arg, default=[], metavar="NAME",
                   help="extra name the panel answers to, if you reach it by a hostname; "
                        "repeat for more than one")

    p = sub.add_parser("web", help="serve the control panel only, without the scheduler")
    add_config(p)
    p.add_argument("--port", type=int, default=8020)
    p.add_argument("--read-only", action="store_true")
    p.add_argument("--allow-host", action="append", type=_host_arg, default=[], metavar="NAME",
                   help="extra name the panel answers to, if you reach it by a hostname; "
                        "repeat for more than one")

    p = sub.add_parser("box", help="run the speaker agent on a Pi or a second machine")
    p.add_argument("--name", default="muezzin-box", help="name to advertise on the LAN")
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--player", default=None,
                   help="command that plays one file (default: mpg123, ffplay, cvlc or aplay)")
    p.add_argument("--allow-host", action="append", type=_host_arg, default=[], metavar="ADDRESS",
                   help="address this box may fetch a recording from; repeat per machine, or "
                        "name .example.com to cover that domain. Without it the box only "
                        "accepts files sent to it directly")

    p = sub.add_parser("init", help="write a starter profile")
    p.add_argument("-c", "--config", type=Path, default=Path("muezzin.yaml"))

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "init":
        if args.config.exists():
            print(f"{args.config} already exists; not overwriting", file=sys.stderr)
            return 1
        (args.config.parent / "media").mkdir(parents=True, exist_ok=True)
        args.config.write_text(STARTER, encoding="utf-8")
        print(f"wrote {args.config} (and a media/ directory - drop your adhan files in it)")
        print("no speakers are configured: run `muezzin where <city> --write` to say where "
              "you are, then `muezzin devices` to see what is on the network and add a "
              "speaker from the panel")
        return 0
    if args.cmd == "methods":
        return cmd_methods()
    if args.cmd == "where":
        return cmd_where(args.city, args.config, args.write)
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
