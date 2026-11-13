# How muezzin works

The long version, for whoever reads the code or the profile and wants to know
why a thing is built the way it is. Start at `README.md` if you are setting this
up; this file is the reference, not the front door.

It covers what the page will and will not answer, how a calculation is expressed
as data, how speakers are found and used, running on a Pi or in a container, and
how the engine is checked against published timetables.
## Who the page answers, and what it refuses to read

An unauthenticated port on a network is a thing other people on that network will
find, so the page is strict about what it will work under:

* **It answers to its own address, and to names you named.** If the Host header
  says something else — `evil.example`, say — the request is refused. This is the
  one that stops DNS rebinding: somebody else's website is made to resolve to your
  LAN address, your browser dutifully sends `Host: evil.example`, and a page that
  only checked the IP would have just handed a stranger your schedule, your
  speakers and a write button. If you serve the page under a name, or behind a
  reverse proxy, say so: `muezzin daemon -c muezzin.yaml --web --allow-host azan.local`.
* **A browser's own headers are checked, and that is all they are good for.**
  `Origin` and `Sec-Fetch-Site` stop a form on a page someone in your house
  happened to visit; `curl` sends neither, so this is a guard against browsers and
  not a way to keep a person out. The Host rule above is the one with teeth.
* **A refused request is refused before its body is used, and the body is still
  drained.** Otherwise the bytes sit on the socket and the browser's *next*
  request — which it sends without waiting — starts in the middle of the last
  one's file. Chunked bodies get a 501 instead: this handler speaks HTTP/1.0 with
  a length, and a chunked body read as if it were not chunked turns one request
  into two.
* **The page will not save YAML that uses anchors and aliases** (`key: &name`,
  `key: *name`). Aliases are ordinary YAML and muezzin reads them happily when you
  put them in the file yourself; what the page refuses is to feed a document full
  of them to a parser over a network port, because PyYAML expands an alias into a
  copy without any limit and a couple of kilobytes of them is enough to finish a
  Pi's memory before the loader can object. Write the values out, or edit the file
  in your editor and press reload — which is also what an editor that cares about
  your comments would do anyway.
* **A speaker scan does not stack.** One is ten seconds of mDNS and a few HTTPS
  round trips, so while one is running the page gets the last result with
  `scanning: true` rather than making the network do it again.

## What the page looks like

Deep green and gold, over a khatam — an eight-point star lattice — drawn into the
page as an inline SVG. Today's card has an arched top, because a rounded top
corner is already the shape of a mihrab and of a dome; there is no figurative
imagery anywhere, and no Qur'anic text used as decoration. Prayer names appear in
Arabic beside the English labels — الفجر، الشروق، الظهر، العصر، المغرب، العشاء،
نصف الليل، الشفع — and the Hijri date sits in the header and on every day row.

Every pixel of that is in the one file the daemon already serves: no font, icon
set, script or tile is fetched from anywhere. That is a requirement rather than a
taste. The page has to work the night the WAN link is down, and it has to work on
a network with no internet at all; and a control panel on your LAN should not
hand a visitor's browser off to a third-party CDN on its way to loading a comma.

## The Hijri date, and why the page says out loud that it is arithmetic

The page shows a **tabular** Hijri date: 354/355-day years, eleven leap years in
a thirty-year cycle, months alternating 30 and 29 days, with an epoch fitted to
published calendars. It is not the moon, and no arithmetic can be. Measured
against published calendars on 26 sampled dates over two years, the pattern is
one-sided: it is **never behind** them and **never more than a day ahead** — 13 of
the 26 land on the same Gregorian day, 13 land one day early, and one printed
calendar day (`30 Sha'ban 1448`) does not exist in this reckoning at all, because
that month is 29 days here. The pytest suite pins those counts, so a future change
to the calendar cannot quietly move the date on your wall.

So the profile has a knob, because your community's calendar — not my integer
arithmetic — is the one you are standing in:

```yaml
hijri_offset: 1     # whole days, -3 to 3; moves the date on the page only
```

It moves nothing else. No prayer time, no event, no playback depends on the Hijri
date; there is a test that asserts exactly that, because a display feature that
quietly shifts Fajr would be the worst kind of feature.

Fixed-date observances are marked on the day rows — Ashura, Arbaeen, the two
Eids, Eid al-Ghadir, the births, Laylat al-Qadr, and so on — coloured by kind:
grey-blue for mourning days, gold for celebrations, teal for the plain ones. They
are decoration on a calendar, not a ruling about when anything is observed, and
the page says so under its own footer. If your community moves a date by local
sighting, that is what the offset is for.

## Choosing the calculation from the page

The Method section is the same table `muezzin methods` prints, in a dropdown, with
the Ja'fari schools in a group of their own — what separates them structurally is
which midnight they count, so the grouping is decided by `midnight_from_fajr`
rather than by a label someone typed. Asr is its own control because the shadow
rule is not a school: a Shafi'i household that prays the later Asr is normal, and
a dropdown that conflated the two would be a quiet way of getting it wrong.

Picking a name rewrites the `preset:` line inside `method:` and leaves the rest of
the file where it was, comments and all. It also leaves alone any angle you wrote
by hand, and says so under the button:

```
in use: ISNA (North America) · your own numbers still in force: fajr_angle
```

The alternative — a dropdown that silently deleted somebody's 12.5° because the
name they clicked says 15° — is a surprise that only arrives at Fajr, which is the
worst possible time to learn about a config change you did not make.

Keeping the comments is the hard part of a panel that writes YAML, and it is why
`yamledit.py` exists. It finds a block by line range and replaces one line inside
it; it never parses the profile into an object and re-renders it, because
re-rendering loses every comment, and those comments are the documentation.

The Hijri offset is two buttons, −1 and +1, for the same reason the knob exists at
all: standing in your kitchen with a phone is not the moment to open a text file.

## A recording per prayer, and one for Fridays

The Sound section lists every time the engine produced, with two clip columns:
what plays all week, and what plays on Friday only. Choosing a clip edits the
`events:` entry that matches instead of appending another one, so pressing the
button twice does not mean Fajr plays twice; choosing *(no clip)* removes that
entry. The Friday column writes the weekday filter the engine already had:

```yaml
  - name: dhuhr-friday
    at: dhuhr
    days: [fri]
    media: [khutbah-reminder.mp3]
```

Only the dropdowns you actually changed are sent, and each one goes through the
same validated write path as the YAML box: `POST /api/audio` with
`{"at": "dhuhr", "friday": true, "media": ["khutbah-reminder.mp3"]}`.

Above the table, a file picker puts a new recording into `media_dir`. The bytes
are the request body (`POST /api/media/upload?name=whatever.mp3`), and two things
about that are deliberate:

* the file is judged by its **first bytes**, not by its extension. A PNG renamed
  `.mp3` is refused, because the failure would otherwise surface as a speaker
  connecting and staying silent.
* an existing name is refused rather than overwritten. Every other write in this
  app can be undone by reloading the file or pressing a toggle; overwriting the
  one recording your family listens to is the edit with no undo.

## Looking at the speakers, including inside a group

**look again** scans with mDNS and shows speakers, groups and boxes, each with a
**use** / **stop using** button. Nothing is cached across a scan, because the
usual reason to ask again is that somebody moved a speaker.

The members column is the interesting one. A Google Home group announces itself
over mDNS with a record that names only the one speaker currently in charge of the
group; there is no member list in the announcement, and the TXT record has no
field for one either. So muezzin asks the *physical speakers* instead — the same
local HTTPS endpoint pychromecast uses for multizone — what groups each of them
considers itself part of, and inverts that. On this LAN the group record names one
speaker while the four speakers name the group, which is where the list comes from:

```
Landing group      192.168.0.21:32002    Landing speaker, Hall speaker
Whole-house group  192.168.0.21:32211    Landing speaker, Study speaker,
                                         Cellar speaker, Hall speaker
```

That inversion is also why the panel distinguishes **unknown** from **empty**. A
speaker that will not answer leaves its groups' membership unknown; printing an
empty list would be a guess, and "nobody is in it" is wrong often enough to be
worth the extra word.

Adding a speaker writes an `outputs:` entry named after a slug of what the device
calls itself; removing one rewrites the `events:` that named it and refuses, naming
the event, if that output was the only place an adhan could reach. Unplugging a
speaker should never be able to silently orphan a Fajr.

Discovery is deliberately narrow. A box is listed, and can be used, only if it
advertises muezzin's own protocol (`_muezzin._tcp`), and `POST /api/box/add` adds
one of those and nothing else. The way to get sound out of a second machine is to
run `muezzin box` on it, not to point muezzin at a device that takes orders from
some other program.

## The calculation is data, not an enum

`muezzin methods` prints the built-in starting points, and the table of them — with
the angles each one uses — is in the README's *Which numbers*, because that is where
someone looking for their own authority will be reading. This section is about the
fields underneath.

**Your authority not in that list is the point.** Any single value can be
overridden, and a preset is only a starting point:

```yaml
method:
  preset: qom
  isha_angle: 13.5          # override one number
  asr_shadow: hanafi        # standard (default) or hanafi
```

or no preset at all — the numbers your masjid publishes:

```yaml
method:
  fajr_angle: 16.5
  isha_angle: 14.0
  isha_interval:            # omit the angle and give minutes after maghrib instead
  maghrib_angle_offset: 3.667   # maghrib at a 4.5° depression instead of at sunset
  midnight_from_fajr: true      # Jafari / Kuwaiti night: sunset -> fajr midpoint
  shurf_angle: 17.0             # optional pre-dawn end time
  high_latitude_rule: one_seventh   # none | middle_of_the_night | one_seventh | angle_based
```

Things the engine gets right that a naive implementation does not:

* `midnight` follows whichever convention the method declares, so `at: midnight`
  means the Jafari night on a Qom profile and the solar midnight on a MWLS one.
  `true_night` always carries the sunset→fajr midpoint if you want both.
* Asr solves the shadow rule (1× or 2×), not a fixed offset.
* Times after midnight are *not* folded back into the day: Isha at `24.4` means
  00:24 the next morning, and the scheduler puts it on the right date.
* High latitudes: with `high_latitude_rule: none` a nonexistent Fajr is reported
  as missing rather than invented; the other rules apply the usual fallbacks.
* Observer elevation moves sunrise earlier and maghrib later (dip correction).
* Per-prayer minute adjustments, like any decent timetable app. They can sit
  under `method:` or at the top level of the profile, and both are read:

  ```yaml
  method:
    preset: isna
    adjustments: {isha: 5}   # nudges that belong to the method you chose
  adjustments:
    fajr: -7                 # nudges that belong to this house, not that method
    maghrib: 3
  ```

  One name in both places is refused rather than guessed at — *"isha is adjusted
  twice, once under method: and once at the top level; keep the one you mean"* —
  and so is a name that is not a prayer time, or a value that is not whole minutes.
  Silently ignoring an adjustment is the failure mode to avoid here: a timetable
  that quietly drops your five minutes looks exactly like a timetable you checked.

## Outputs: which speaker, for which prayer

```yaml
outputs:
  - name: study
    kind: google_cast
    target: Study speaker        # `muezzin devices` prints these names
    volume: 0.4                  # a speaker's level; a computer has none
  - name: house-group
    kind: google_cast
    target: Whole-house group             # Google Home groups work, including one speaker
    volume: 0.25
  - name: pc
    kind: pc_speakers              # this machine's default output, at its own level
  - name: attic-pi
    kind: lan_box
    host: 192.168.0.25            # an `muezzin box`, also at its own level
  - name: hall-pc
    kind: pc_speakers
    enabled: false                 # parked, not deleted
  - name: paper-trail
    kind: file                     # no speaker at all: keeps a copy of what would have played
    host: out/tray                 # a folder, and only ever inside out_dir

out_dir: out                       # the one folder kind: file may write into

events:
  - name: fajr-adhan
    at: fajr                       # fajr|sunrise|dhuhr|asr|maghrib|isha|midnight|true_night|shurf|sunset
    offset_min: -5                 # 5 minutes before Fajr
    media: [fajr.mp3]
    targets: [study, house-group] # per-event: this is the part that is missing elsewhere
    volume: 0.5                  # one level for the cast speakers in this event
  - name: sunrise-tune
    at: sunrise
    media: [dua.mp3]
    targets: [study]
    days: [sat, sun]               # weekday filter
```

No `targets:` means every enabled output. A config typo (`at: fagr`, a target
that does not exist, an event with no media) is rejected when the file is loaded,
because the worst time to discover it is 5 am.

`kind: file` is the output you point at no speaker. It copies the recording that
would have played into a folder, which is how you watch what the schedule actually
does before you let it wake the house, and how a machine with no audio device - a
container, for instance - still produces something you can look at. Its `host:` is
resolved against the folder the config file lives in and has to land inside
`out_dir`, which defaults to `out` next to the config; a file output that names a
path outside it is refused at load time. That limit is deliberate: this is a
program that runs unattended on a LAN with no password in front of it, and the web
page can add outputs, so "writes a copy somewhere" is only safe if "somewhere" is
one folder you chose.

### Google Nest / Chromecast, no Google account

Cast is a local protocol: muezzin finds speakers with mDNS and talks to them
directly on the LAN. No Google account, no cloud API, nothing to enrol.

```bash
muezzin devices --timeout 8
```

```
speaker / group              model                      group  address
Landing group                Google Cast Group          yes    192.168.0.21:32002
                                  members: Landing speaker, Hall speaker
Whole-house group            Google Cast Group          yes    192.168.0.21:32211
                                  members: Landing speaker, Study speaker, Cellar speaker, Hall speaker
Landing speaker              Nest Audio                 -      192.168.0.22:8009
Study speaker                Google Nest Mini           -      192.168.0.23:8009

box                          protocol         player     address
test-box                     muezzin_box      winmm      192.168.0.5:8090
attic-pi                     muezzin_box      mpg123     192.168.0.25:8090
```

The member list is not in the group's own announcement, so it is read back from
the speakers — see *Looking at the speakers* above. A group whose members could
not be asked says so instead of printing nothing. The `player` column is not
something you configure: each box reports what it found on its own machine, which
is how you can tell from the daemon's side that the Pi really does have mpg123.

A Cast speaker plays a **URL it fetches itself**, so the daemon starts a small
HTTP server for `media_dir` (port 8010). That means:

* the **firewall on the machine running the daemon must let the speakers reach
  that port** — this is the most common reason a speaker connects and stays
  silent. Run `muezzin -v daemon` and look for `media http: "GET /fajr.mp3 ...
  200"`; a request that never arrives is a firewall or VLAN problem, not muezzin.
* long recordings never pass through the daemon, so a 20-minute surah is fine.
* mDNS must not be blocked. Windows treats a network as *public* by default and
  blocks it; Nest Minis also answer mDNS inconsistently, which is why muezzin
  rescans for 9 seconds before telling you a speaker is gone.

### Amazon Alexa

Not implemented, and here is the honest reason: pushing audio to an Echo needs
Amazon's *Alexa Web Playback SDK / Devices API* through an **AWS "Alexa Projects"
account, which costs about $20/month**. Nothing local can do it — unlike Cast,
there is no LAN protocol for an Echo. If you want it, budget for that account;
patches are welcome but they will always need it.

## How a machine makes a sound

Everything else in muezzin is written once and runs wherever Python runs. This is
the one part that cannot be, because the operating system is the thing holding the
audio device — and a container has no audio device at all. So the question "how
does this machine make a sound" is answered in one place, once at start-up, and the
answer is printed rather than assumed.

| machine | what plays a recording | what you install |
| --- | --- | --- |
| Windows | winmm, the MCI interface that ships with Windows, called through `ctypes` | nothing |
| macOS | `afplay`, which is part of macOS | nothing |
| Linux | the first of `mpg123`, `ffplay`, `cvlc`, `paplay`, `aplay` that is on PATH | one small package: `sudo apt install mpg123` |
| none of them | a refusal, in words, naming what to install | — |

The same answer serves both places sound can come out of a computer: a
`kind: pc_speakers` output in the daemon, and `muezzin box` on any machine that is
only a speaker. So "the machine's own speakers" means the same thing on a Pi, a
Windows PC and a Mac, and a box is not a Pi-shaped thing — it is whatever the
machine in the cupboard already is.

A box announces its choice: it is printed when the box starts, it is in its mDNS
announcement, and `/status` returns it, which is why the `player:` column in
`muezzin devices` can tell you that the Pi really does have mpg123. A box that
found nothing warns at start-up and refuses a play before it wastes the network's
time fetching a recording.

`--player 'mpg123 -q'` replaces the guess with a command you name; the file to play
is appended as its last argument. That is also how the tests watch a player without
owning a speaker — the "player" is a two-line Python script that writes down what it
was handed.

Three honest limits of this seam:

* it plays through the machine's **default output device**. None of the interfaces
  above can choose a device, so per-room sound means network speakers.
* **a computer's volume is not ours to touch.** The `volume:` knob in a profile
  means one thing: the level of a speaker muezzin is casting to. The machine
  muezzin runs on, and any box on the LAN, play at whatever level that machine is
  already set to, and nothing that arrives over the network changes it. Someone
  chose that level, in that room, and a program that moved it while they were
  asleep would be doing something they never agreed to. There is also no
  portable way to do it: on Windows the MCI level call is one a driver may not
  implement at all - measured here, it answers error 261, "the driver cannot
  recognize the specified command" - and on macOS and Linux there is no
  comparable call. So it is not attempted anywhere. If a profile names a volume
  for an output that is a computer, one line in the log at start-up says so,
  rather than leaving you looking for the knob.
* a command-line player is a separate process, so what comes back from a recording
  it cannot decode is an exit code rather than a diagnosis. `mpg123` and `ffplay`
  cover what a Cast speaker accepts; `paplay` and `aplay` are wav only, which is why
  they sit last in the list.

Nothing here installs anything and nothing here goes online: the players are either
part of the operating system or packages you put there yourself.

## Running on a Raspberry Pi

Two ways, and they are not the same.

**1. The daemon on a Pi** — the Pi is the brain, media lives on it, and it plays
out of any Cast speaker or its own 3.5 mm / USB speakers:

```bash
sudo apt install mpg123          # the only package this needs; on Windows and macOS
                                 # each has its own built-in path, so there is nothing
                                 # to install
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/muezzin daemon -c muezzin.yaml --web   # the page is then on the Pi, so a
                                                # phone on the wifi can drive it
```

**2. `muezzin box` on a Pi** — the box is a dumb, always-on player, and the
machine running the daemon stays the brain:

```bash
muezzin box --name attic-pi --port 8090     # advertises itself with mDNS
```

Then in the daemon's profile:

```yaml
outputs:
  - name: attic-pi
    kind: lan_box
    host: 192.168.0.25      # or leave it out and let discovery find it
    port: 8090
```

The wire protocol is plain HTTP + JSON so you can test it with curl:

```
GET  /ping    -> Pong
GET  /status  -> {"name": "attic-pi", "player": "mpg123", "last": {...}}
POST /play    -> {"urls": ["http://192.168.0.5:8010/fajr.mp3"],
                  "files": {"small.mp3": "<base64>"}}
```

`urls` is the normal path (the box pulls the file). `files` exists for a box that
cannot route back to the daemon. No level crosses this wire: the box plays at the
volume set on the box, and a daemon has no way to change it. The box announces
itself as `_muezzin._tcp.local.`, which is why `muezzin devices` finds it without
an IP.

**Starting a server never waits for name resolution.** The panel, the media
server and a box's own server all listen on `0.0.0.0`, and the standard library's
HTTP server pauses while it binds to ask the operating system this machine's
fully-qualified name. Where nothing resolves that name — a Pi called
`raspberrypi` with no DNS entry, a Mac on a home LAN, a CI runner whose hostname
ends in `.local` — the answer is not "no", it is a timeout. Measured on
2026-11-13 on an arm64 macOS runner, opening a port there took **35.0 seconds**,
and `socket.getfqdn()` on that same machine took 70.0; on Linux and on Windows
the same call took about a second, which is still a second per server started.
So all three servers bind through one class of muezzin's own, `net.LANServer`,
which records the address it actually has. Nothing muezzin sends depends on the
name, and a daemon that says nothing for half a minute before its port opens
looks exactly like a daemon that is broken.

**A box only fetches from a host you named.** `POST /play {"urls": [...]}` is an
instruction to make an HTTP request, and a $25 speaker on everybody's wifi is a
poor place to put that power: pointed at a router's admin page, a cloud metadata
address or your phone, "play this" becomes "read this". So the box refuses any URL
whose host you did not name when you started it:

```bash
muezzin box --name attic-pi --port 8090 --allow-host 192.168.0.5
```

`192.168.0.5` is the machine that serves your media — the daemon's address, which
`muezzin devices` prints. Name it more than once for more than one machine, or
name a leading-dot domain (`.media.home.local`) to cover that name and anything
under it; the dot is what keeps a name from quietly becoming a wildcard. Nothing
else changes about how the box works: it still has no schedule, no settings and no
state beyond the last thing it played. A request is also capped by size and by
count (a couple of dozen files per play, a file under 64 MB), a file that arrives
is verified to be a file before a player is asked to open it, and chunked request
bodies are refused rather than reassembled, because a Pi should not be holding an
unbounded body in memory.

Keeping the box alive (systemd on Raspberry Pi OS):

```ini
# /etc/systemd/system/muezzin-box.service
[Unit]
Description=muezzin speaker box
After=network-online.target
[Service]
ExecStart=/home/pi/muezzin/.venv/bin/muezzin box --name attic-pi --allow-host 192.168.0.5
Restart=always
[Install]
WantedBy=multi-user.target
```

**Why this split matters.** A box that computes its own times has to support your
calculation, and a box built from a fixed list of named methods stops at that
list, however you configure the machine next to it. In muezzin the daemon computes
and the box only plays, so a Ja'fari method or a custom masjid's numbers works on
the Pi exactly as well as it works on Windows: the method lives in one file, on one
machine, and the player never needs to know what it is.

The other reason the box is dumb on purpose is safety. A player that also stores
settings tends to expose routes that rewrite those settings, change the
calculation, or reboot and re-image the machine. muezzin speaks to nothing that
offers those routes. Our box has three — `GET /ping`, `GET /status`, `POST /play` —
and a box fetches a recording only from a host you named with its own
`--allow-host`. There is no route to interrupt a play once it started: a recording
ends when it ends, and the next one waits behind it.

## Running in a container

`docker compose up` builds the image and runs the daemon, the page and the media
server as one process. Your profile lives in `./config`, your audio in `./media`,
nothing personal is baked into the image, and the container runs as an ordinary
user rather than root.

```bash
docker run --rm -v "$PWD/config:/app/config" muezzin:0.1.1 init -c /app/config/muezzin.yaml
# edit location and method. The starter's `media_dir: media` is relative to the
# profile, so in the container it means ./config/media; set it to /app/media to
# use the ./media volume compose mounts. Starters have no outputs — see "speakers
# on your network" for what casting from a container needs.
docker compose up
```

The image starts as `muezzin daemon --web 8020 --read-only`: the page shows the
timetable, the Hijri date and the YAML, and refuses to change anything. A
container that is easy to start should not also be a port that can rewrite your
schedule, and the config folder is a volume, so editing `./config/muezzin.yaml`
on the host and pressing reload works without touching the flags. To drive the
profile from the page instead, override the command in `docker-compose.yml`:

```yaml
services:
  muezzin:
    command: ["daemon", "-c", "/app/config/muezzin.yaml", "--web", "8020"]
```

The compose file mounts `./config`, `./media` and a named volume at `/app/out`;
that last one is `out_dir`, the only folder a `kind: file` output may write into,
and the named volume keeps it out of your source tree.

### The whole compose file, so you can copy it

```yaml
services:
  muezzin:
    build: .                        # or the published image, below
    image: muezzin:0.1.1
    network_mode: host              # required for speaker discovery
    volumes:
      - ./config:/app/config        # your muezzin.yaml lives here
      - ./media:/app/media          # your audio lives here
      - muezzin-out:/app/out        # where kind: file outputs land
    environment:
      # Times come from `location.timezone` in the profile, not from TZ; this
      # only makes the log lines read like your day.
      TZ: America/New_York
    security_opt:
      - no-new-privileges:true
    restart: unless-stopped

volumes:
  muezzin-out:
```

Why `network_mode: host` is not decoration: speakers are *found* with mDNS
(`_googlecast._tcp` for Cast devices, `_muezzin._tcp` for other muezzin boxes),
and mDNS announcements do not cross a bridge network. The alternative in the
checked-in file — a commented `muezzin-lookup-only` service with a `ports:`
mapping — is what you want if you only need the timetable, the page and a `file`
output, because then there is nothing to discover.

### Pulling the image instead of building it

`.github/workflows/image.yml` builds `linux/amd64` and `linux/arm64` when you push
a `v*` tag, and signs in to the registry with the workflow's own `GITHUB_TOKEN`, so
no personal token is involved. The image is published under the **version**, not
the git tag, so pushing `v0.1.1` produces the image `:0.1.1`:

```bash
docker pull ghcr.io/124c41pl/muezzin:0.1.1
```

and in the compose file replace `build: .` / `image: muezzin:0.1.1` with:

```yaml
    image: ghcr.io/124c41pl/muezzin:0.1.1
```

`latest` is published too, and the workflow refuses to build if the tag and the
version in `pyproject.toml` disagree. One thing to know if you publish your own:
the **package** has to be public as well as the repository. ghcr keeps a package
private when it was created while the repository was still private, and
`docker pull` then answers `unauthorized` forever, with a green build next to it.

What was actually run here (Docker 29.9.2 on Windows), so this section is a
report rather than a promise: the image builds at about 200 MB, `muezzin methods`
lists the 18 presets inside it, `muezzin times` for Tehran answers
`fajr 05:26 … isha 18:34` for 2027-01-01, the panel is served and reports the
Hijri date with its Arabic month name, `--read-only` refuses a browser write with
403, and `muezzin play-now` through a `file` output really did leave
`test-tone.wav` (88,244 bytes) in the mounted folder on the Windows side. The
`methods` and `times` checks were run again against the image pulled anonymously
from `ghcr.io`, not against a local build.

What did not work here:

| running as | speakers discovered on this LAN |
| --- | --- |
| the host directly | 6 |
| container, bridge network | 0 |
| container, `--network host` | 0 |

Speakers are *found* with mDNS — `_googlecast._tcp`, and `_muezzin._tcp` for
boxes — and mDNS does not cross a network boundary. Docker Desktop on Windows and
macOS runs the container inside a VM, so `network_mode: host` there is host
networking with the VM, not with your LAN: the speakers stay invisible. On a real
Linux box — a home server, or a Pi — `network_mode: host` is what discovery needs,
and the compose file sets it; I could not measure that from this machine, so
treat that row as expected rather than tested.

Four things that follow from running in a container:

* **`kind: pc_speakers` cannot work inside one.** There is no audio device to
  open. Use `google_cast`, `lan_box` or `file`.
* **`media_dir` must be a volume.** A Cast or a Pi box fetches audio over HTTP
  from the daemon, so it needs the files, and it needs the daemon reachable at
  the address it advertises — which inside a bridge network is a `172.17.x.x`
  your speaker has no route to.
* **Port mappings are ignored under `network_mode: host`.** `ports:` in that case
  is decoration; the daemon is already listening on the host's interfaces.
* **Run `muezzin box` natively on the Pi, not in Docker.** That process is the one
  that needs the machine's own audio device — winmm, afplay, mpg123 — and an mDNS
  registration, which is exactly the pair a container is worst at.

If all you want from the container is the timetable, the page and a `file`
output — a server that answers "what is Fajr tomorrow, and what would it have
played" — it works, and it was verified working here.

## How the engine is checked

Three tiers, and `tests/` is where the interesting ones live:

```bash
python tests/crosscheck.py       # needs `pip install -e .[dev]`
pytest -q                        # 300 tests
```

CI runs the suite and the oracle on ubuntu, windows and macOS, on Python 3.10 and
3.12. Three operating systems because the one part of this program that is
operating-system-specific has to be tested on the three it claims to run on; the
player tests pass a stub command instead of a speaker, so none of it needs audio
hardware on the runner.

1. **Independent oracle.** `tests/crosscheck.py` compares against PyPI's `adhan`
   package (Batoulapps.Adhan's Python twin) over four method / asr-shadow / date
   combinations. Worst deviation **2.1 minutes**; that package's own published
   tolerance is a couple of minutes. The oracle runs at western longitudes only,
   because `adhan` 0.1.1 has a known `abs(longitude)` bug in solar noon — which is
   why eastern-hemisphere sites are checked with invariants instead.
2. **Invariants**, checked at Tehran, Qom, Makkah and Reykjavik in both solstices
   (plus every latitude in the pytest suite, including the Arctic): sunrise and
   sunset symmetric about dhuhr, Fajr and Isha symmetric about the method's
   midnight, monotonic ordering, a midnight-sun day honestly reports missing
   times. Zero failures.
3. **Published timetables** from `api.aladhan.com` (NYC/ISNA, London/Egyptian,
   Qom/Tehran institute). Worst deviation **1.7 minutes** across every row. The
   Tehran row is the interesting one: muezzin reproduces its Fajr 05:10 and Isha
   18:12, and its maghrib 17:24 once you set `maghrib_angle_offset: 3.667`, because
   that source uses a 4.5° depression rather than sunset — a number a fixed list of
   named methods has no field for.

Real-world playback is confirmed end to end on a Google Home group and a single
Nest Mini: with `-v`, the log shows the speaker fetching the file itself
(`media http: "GET /test-chime.wav HTTP/1.1" 200`) and then reporting
`playerState: PLAYING` advancing to `idleReason: FINISHED`, and the chime was
audibly heard from both. Nothing in that path touches Google's cloud.

