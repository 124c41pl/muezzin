# muezzin

Play the adhan on the speakers you already own, using the calculation your family
actually follows.

One small daemon, one YAML profile, and a control page that runs on your own
network. The profile says where you are, which numbers you use, which recording
plays, and which speaker it comes out of — per prayer, per day of the week, per
volume.

Two decisions do most of the work:

* **The calculation is data, not a dropdown.** A preset is a starting point, and
  any one of the numbers underneath it can be replaced with the ones your own
  authority publishes. A list of named methods is not the same thing as a
  calculation, and it is not the thing you are supposed to live inside.
* **Playback is per prayer, per speaker.** Fajr softly in the study and through
  the landing group, a different recording on Fridays, nothing after Isha —
  expressible, because an output is a row in a file and not one global setting.

* **Language / shape:** Python daemon plus one small LAN web page, configured by a
  single YAML profile. Runs on Windows, Linux, macOS, a Raspberry Pi, or in a
  container.
* **License:** MIT. The calculation engine is written here from scratch;
  `THIRD-PARTY.md` lists what it stands on and what each licence asks of you.
* **Status:** working, used against real hardware, and young. See *Limits*.

```
   muezzin.yaml  ──>  muezzin daemon  ──>  pc_speakers   (this machine)
   location             scheduler          google_cast   (Nest / Chromecast / groups)
   method               media server       lan_box       (muezzin box, any machine)
   events                                  file          (copy somewhere)
                         |
                    http://this-host:8020   your browser: times, schedule,
                                            speakers, and the YAML itself
```

## Start here: four steps

Get the location right, choose the calculation, find the speakers, give each
prayer a recording. In that order, because each step is measured by the one
before it.

### 1. Where you are

```bash
muezzin init                            # starter profile: five prayers, no speakers yet
muezzin where orlando                   # prints the coordinates behind a city name
muezzin where --write orlando           # ...and puts them in the profile
muezzin where --online "SW1A 1AA"       # ask OpenStreetMap for something the table lacks
muezzin where --coords 42.1292,-80.0851 # what those numbers are near, nobody asked
muezzin times                           # does this look like your local timetable?
```

Location comes first because everything else is computed from it. A time zone only
decides how the clock is *labelled*: Orlando, Florida and Erie, Pennsylvania share
`America/New_York`, and their Fajr and Maghrib land at different clock times
because the sun sits at a different angle over each of them. Latitude, longitude
and — if you want it — elevation are what move the numbers; the zone just names
them.

`muezzin where` knows 79 city centres and works with the network off. A
city centre is a starting point, not your street: a couple of kilometres is a few
seconds, and if you want the times for your address rather than for the middle of
town, type your own numbers into the profile. Until you do, the starter's
placeholder location is announced out loud — `muezzin times` and `muezzin daemon`
print a note, and the page shows a gold band under the header — because a location
nobody chose produces no error at all, just wrong times.

`--online` is the one place in muezzin where words you typed leave your network, and
it is a flag you type rather than a default. It asks Nominatim — the address search
the OpenStreetMap project runs — once, in a request that carries this program's name
instead of an account, and keeps nothing: no cache, no log, and a bad answer is not
quoted back. No lookup anywhere in here needs an API key, because a search you can
only run after registering a card with somebody is a search most households will not
run. What comes back usually carries a time zone; when it does not, muezzin borrows
the zone of the nearest city it knows within 150 km and prints which city it
borrowed, or says there is no honest guess and leaves that line to you. The times
themselves never depend on either service being up.

### 2. Which numbers

```bash
muezzin methods                         # every starting point and the angles it uses
```

Pick one and change nothing, or pick one and change one number, or name no preset
at all. The 18 presets below are starting points, not a menu you are stuck with:

| preset | Fajr | Isha | notes |
|---|---|---|---|
| `mwls` | 18° | 17° | Muslim World League |
| `isna` | 15° | 15° | ISNA, North America |
| `egyptian` | 19.5° | 17.5° | Egyptian General Authority |
| `karachi` | 18° | 18° | Univ. of Sciences, Karachi |
| `umm_al_qura`, `makkah_interval`, `qatar` | 18.5° / 18° | maghrib + 90 min | interval methods |
| `kuwait` | 18° | 17.5° | |
| `dubai` | 18.2° | 18.2° | |
| `singapore` | 20° | 18° | MUIS |
| `turkey` | 18° | 17.5° | Diyanet |
| `france` | 12° | 12° | Muslim Council of France |
| `moonsighting` | 18° | 17° | |
| **`tehran`** | **17.7°** | **14°** | Institute of Geophysics, Tehran — Jafari midnight |
| **`qom`** | **19°** | **14°** | Qom (Khamenei / Khoei variant) — Jafari midnight |
| **`qom_khamenei_12`** | **12°** | **15°** | Qom, 12/15 variant — Jafari midnight |
| **`shia_ithna_ashari`** | **16°** | **14°** | Jafari — Jafari midnight |
| `othman_local` | 19.5° | maghrib + 75 min | *example* of a local masjid's own numbers |

```yaml
method:
  preset: qom
  isha_angle: 13.5          # override one number
  asr_shadow: hanafi        # standard (default) or hanafi
```

The page has the same choice as a dropdown, with the Ja'fari methods grouped apart
and the Asr rule beside it, and the calendar on the page follows whatever you pick.
What the other fields mean — midnight conventions, maghrib by angle instead of by
sunset, high-latitude fallbacks, elevation, per-prayer minute nudges — is in
`docs/HOW-IT-WORKS.md`.

### 3. Which speakers

```bash
muezzin devices                         # speakers, groups and boxes found on the LAN
```

The starter names no speaker on purpose: an output pointed at a device you do not
own is an error at every prayer time. `muezzin devices` only reports, and a scan
never writes anything to your profile, so the list is only ever what you chose.

The usual way in is the page: **look again**, then **use** beside a device. Groups
are spelled out with their members, so a whole-house group and the two speakers
inside it are three different things you can point Fajr at. If you would rather
edit the file, the starter leaves the entries commented out under `outputs:`.

```yaml
outputs:
  - name: landing-group
    kind: google_cast
    target: Landing group             # spelled exactly as `muezzin devices` prints it
    volume: 0.5                  # that speaker's level; the machine's own stays yours
```

An event with no `targets:` reaches every enabled output, which is why adding a
speaker to a working household needs no edit to the events.

### 4. Which recording

```bash
cp ~/Downloads/fajr.mp3 media/         # your own audio; any file, any qari
```

The page gives every prayer its own clip, plus a second column for Fridays, and a
file picker that puts a new recording into `media_dir` (judged by its first bytes,
and never overwriting a file that already exists). Before you assign one, press
**hear it here** beside the list: that plays the clip out of the computer you are
looking at, at whatever level that computer is already at, and nothing on the
network hears it — so you can compare recitations with the speakers silent. The
level on your computer is yours to set and muezzin never touches it; a level in the
profile means a speaker muezzin casts to. The two files in `media/` are short test
tones generated for this repo: `muezzin play-now media/test-chime.wav` makes a
noise, so you find out now rather than at 5 am whether the wiring is right.

### Then run it

```bash
muezzin next                           # what will fire, when, and to which output
muezzin daemon --web                   # leave it running, with the page on :8020
```

`muezzin next` is the one to trust: it shows the schedule as the daemon sees it —
wall clock, weekday filter, and which output each event resolves to.

## Install

Python 3.10+ (3.11 through 3.15 are what it is tested on), on Windows, Linux or
macOS - whichever machine the house already has. Those three differ in exactly
one place: what plays a recording through a machine's own speakers. Windows and
macOS need nothing installed; a Linux box wants one small player package, and
`muezzin box` tells you which one it found.

```bash
git clone <your fork> muezzin
cd muezzin
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .                   # -e .[dev] also installs pytest and the oracle
muezzin init                       # writes muezzin.yaml and a media/ directory
```

On Windows, if `python -m venv .venv` appears to do nothing, you are hitting the
`WindowsApps` stub on PATH; use the real interpreter, e.g.
`C:\Python315\python.exe -m venv .venv`.

## The page

`muezzin daemon --web` serves one page on port 8020 (`--web 8080` for another
port). Open `http://<the machine's LAN address>:8020` from a phone on the same
wifi — which is how you stand in the kitchen and find out whether the speaker you
just added is actually reachable.

On it: three days of times for the method in the profile; the next events and
which output each resolves to; every output with an on/off switch and a **test**
button; the method dropdown; a clip per prayer and a Friday column; what is on the
LAN right now, with **use** / **stop using**; a **Where** section — type numbers and
press **check these numbers** to be told the nearest names and what clock they would
keep, with nobody being asked anything, or type words and press **find it**, which
asks OpenStreetMap once; and the profile YAML itself with a save button. A band above
it says out loud whatever is still missing — a location nobody chose, no speakers, or
every speaker switched off.

Put `map_tiles: osm` in the profile and a small map appears behind those numbers. The
squares are fetched by the daemon and kept on disk, so the page still only ever talks
to this address, and the credit "© OpenStreetMap contributors" sits under the map.
Without that line there is no map, and the page asks nothing of anybody.

Saving re-validates before writing, and a bad edit is never written to disk: the
error you see is the one the CLI would print. A good one is picked up without a
restart. The **test** button reports what the speaker said rather than what
muezzin hoped, so a speaker that cannot fetch or decode the clip answers with an
error of its own.

Toggles are for the running daemon; the YAML is what persists. There is no hidden
database, so nothing can drift between what the page believes and what
`muezzin times` computes. There is no login: the page binds the LAN interface and
belongs on a network you trust, and `--read-only` serves it with saving and test
playback disabled. `muezzin web -c muezzin.yaml` runs the page by itself, which is
handy for editing a profile on a laptop while the real daemon keeps playing
somewhere else.

## Other machines

**Raspberry Pi.** Either run the whole daemon on the Pi, or run `muezzin box`
there as a dumb always-on player and keep the brain on the machine you already
use. A Pi is a real Linux machine, so the container path works there too, host
networking and all. The systemd unit, the player packages and what mDNS does and
does not see on a Pi are in `docs/HOW-IT-WORKS.md`.

**Container.** `docker compose up` builds it; or pull what CI publishes:

```bash
docker pull ghcr.io/124c41pl/muezzin:0.1.2
```

Your profile goes in `./config` and your audio in `./media`; nothing personal is
baked into the image, and the container runs as an ordinary user. Speaker
discovery needs `network_mode: host`, which Docker Desktop on Windows or macOS
cannot really provide — the measured numbers, and the two things a container is
bad at here, are in `docs/HOW-IT-WORKS.md`. On a real Linux machine, host
networking is one line and works.

**Any other machine** can be a speaker too: a second PC, an old laptop, a Mac in
the hall cupboard. Run `muezzin box --name attic-box` on it and it shows up in
the device list, along with the player it picked for itself.

## Limits, honestly

* Sound from the machine muezzin runs on goes to that machine's **default output
  device**, on all three systems: winmm on Windows, afplay on macOS, whichever
  small player a Linux box has. None of them route per device, so per-room sound
  means network speakers. And muezzin never changes a computer's volume: the
  `volume:` knob is for the speakers it casts to, while the machine it runs on —
  and any box on the LAN — plays at whatever level you set on that machine.
* On macOS the firewall asks whether Python may receive incoming connections the
  first time you run a daemon or a box. Say allow, or the page will not answer and
  discovery will not work.
* The daemon is a foreground process. There is no Windows service installer or
  tray icon yet; a Task Scheduler entry or `systemd` unit is what people use.
* No Alexa, and no Bluetooth-target backend.
* The page has no login and binds the LAN interface, so it belongs on a network
  you trust; `--read-only` removes its ability to write or make noise. It can
  change anything the YAML can express, and nothing else. `SECURITY.md` states that
  model in full, including what it does not defend against and how to tell me about
  one privately instead of in a public issue.
* The page answers to the address it is served on and to any name given with
  `--allow-host`, and to nothing else; a box likewise fetches a recording only from
  a host named with its own `--allow-host`. Neither is a substitute for
  authentication: they stop a stranger's *website* reaching a LAN port, which is a
  different problem from a stranger on the LAN.
* A prayer time that falls inside a daylight-saving gap — the hour spring forward
  deletes — comes out an hour off. One event per year at most, at the latitudes
  that change clocks.
* If a prayer time does not exist at your latitude, the event is skipped rather
  than moved.
* Prayer times are the *computed* times for your coordinates. A masjid down the
  road that rounds to the minute, adds a few minutes of precaution, or follows a
  printed table will differ, and neither one of us is wrong about the sky.
  Adjustments exist for exactly this.
* Group membership is measured, not read from a directory: it is what the speakers
  say when asked. A speaker that will not answer leaves the members *unknown*, and
  a group you rearranged in the phone app shows the truth on the next **look
  again**, not before it.
* An upload is one request: 64 MB, no resume, no transcoding. The recording has to
  be something the speaker can decode by itself.
* The media server that hands files to a Cast speaker is deliberately boring: it
  serves what the profile names, lists no folders, and does not answer `Range`
  requests, so a client that insists on seeking before it plays will be annoyed
  rather than served. The browser preview in the page has the same limit: a clip
  starts at the beginning.
* One adhan at a time per box; overlapping events queue.
* `lan_box` discovery by name instead of a required `host:` is not wired in yet;
  giving the host explicitly always works.
* The Hijri date is tabular arithmetic, not a sighting, and `hijri_offset` is there
  because the moon decides, not an integer. It is display only: no prayer time
  reads it.
* In a container, mDNS discovery and local audio are the weak points: the image
  has no audio device, and on Docker Desktop (Windows or macOS) host networking is
  not really available either. As the brain that drives network speakers, a
  container is fine.

## Who wrote this

Written by Alexander Ortiz, with an AI assistant. That is who to argue with when
the Fajr time is wrong for your street.

If you fork it, put your own name in the profile and the page will say it:

```yaml
attribution: "your name or handle"
```

The author field names a person on purpose. A person can be asked why Fajr is
computed that way, can be told the time is wrong for their street, can be asked to
add a method and can say no to one. Whoever runs this project is the one who owes
you an answer, so the credit is yours to put there.

## Licensing

MIT — see `LICENSE`. Use it, fork it, ship it on your own hardware.

* The astronomy is implemented here from the definitions. No code from any
  proprietary prayer-time product is in this repository, and nothing proprietary is
  shipped in the image.
* `adhan` (PyPI) is LGPLv3 and is used **only** as a development-time oracle in
  `tests/crosscheck.py`. It is a dev extra, never imported by muezzin itself, and
  not one line of it was copied.
* `zeroconf`, which finds your speakers, is **LGPL 2.1 or later**. That is not a
  problem for a normal `pip install` or a container image, but it is the one
  dependency worth knowing the name of before you redistribute a bundled build.
* `pychromecast` and PyYAML are MIT; `tzdata`, which Windows needs because it
  carries no zone database of its own, is Apache-2.0.

Nothing is fetched from the internet at runtime: the page is one file served by the
daemon, with no CDN, no web fonts and no analytics. The only URLs the program ever
fetches are the ones in your own profile.

## Development

```bash
pip install -e .[dev]
pytest -q                    # engine, config, scheduler, box protocol, web panel,
                             # and the editor that keeps a file's comments
python tests/crosscheck.py   # oracle + invariants + published timetables
```

Layout: `calc.py` (astronomy and the method table), `places.py` (the city table
`muezzin where` reads), `config.py` (the YAML is the interface), `scheduler.py`
(times → wall-clock events), `backends.py` (one class per kind of speaker, plus
what is found on the LAN), `localplay.py` (the one platform-specific seam: which
player this machine has, and how it gets asked for sound), `media.py` (the HTTP
server speakers fetch from), `box.py` (the player agent), `web.py` (the LAN page and
its JSON API),
`yamledit.py` (writing one line of the profile without disturbing the rest of it),
`cli.py` (the commands you type).

More detail — what the page will and will not answer, every field in the profile,
the box protocol, running on a Pi or in a container, and how the engine is checked
against published timetables: **`docs/HOW-IT-WORKS.md`**. The profile's own
comments are in `config/README.md`; `SECURITY.md` is the threat model;
`THIRD-PARTY.md` is the licence picture.
