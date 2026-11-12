# Smart Azan Windows 3.0.0.3 — teardown findings

Source: `SmartAzanSetup.exe` (Inno Setup 6.3.0), unpacked with innounp into `extracted2/`.
Not obfuscated, debug builds, PDBs included — the app is fully readable from the DLLs.

## What it is

- WPF app on .NET (the main binary ships under the giveaway name
  `Google.Cast.DesktopV2.exe`, i.e. the vendor's app is derived from the Google Cast
  C# sample). Core logic lives in `SmartAzan.Shares.Service.dll`, entities in
  `SmartAzan.Shared.Domain.dll`, persistence (EF Core + Dapper + SQLite) in
  `SmartAzan.Shared.Data.dll`.
- Scheduling: Quartz jobs (`PrayerTimesExecuter`, `AdhanPlayerExecuter`).
- Dev leftover: the shipped DLLs carry PDB paths from the vendor's own build
  machine (`C:\Users\<vendor developer>\source\repos\SmartAzan.Shared\...`).
  Username generalised here; it is the vendor's, not ours, and it tells you
  nothing the finding does not already tell you.

## Why the calculations are "ideologically narrow" — root cause found

The engine is **Batoulapps.Adhan** (a .NET port of the adhan library). Its
`CalculationMethod` enum has exactly 11 values:

```
MUSLIM_WORLD_LEAGUE, EGYPTIAN, KARACHI, UMM_AL_QURA, DUBAI,
MOON_SIGHTING_COMMITTEE, NORTH_AMERICA, KUWAIT, QATAR, SINGAPORE, OTHER
```

- **No Shia Ithna-Asheri / Ja'fari. No Qom. No Tehran.** The port itself predates the
  Shia method that upstream `adhan` libraries (JS/Python/Java) ship.
- The `settings` table stores `CalcMethod` as a single string and `AsrMEthod` as a single
  string — no twilight-angle fields, no midnight-convention field, no maghrib offset.
  Only a coarse `PrayerAdjustment` table (±minutes per prayer) exists.
- So the gap isn't a missing dropdown entry — the data model can't represent the methods.

## Why the audio is inflexible — root cause found

- `adhan_media_files` = literally **one row**: `fajrurl`, `otherurl`, `previewurl`.
  Two audio URLs for the whole app (Fajr vs everything else).
- Media is always a **URL** (external CDN), never a local file or playlist.
- `settings.SpeakerType` = one global int; `settings.ChromeSpeakerName` = one global
  Cast speaker name. `adhan_queue` (mediaUrl, playOrder, enabled) exists in the schema
  but only supports enable/disable + URL swap — no per-prayer routing, no multi-device.
- `surahSettings` = one scheduled surah (one file, one frequency, one volume).
- Playback paths in code: `ChromeCast.Play(playerName, mediaUrls, volume)` and
  `AudioPlayer(...)`; the Pi gets *URLs*, it doesn't receive audio.

## The Pi ("Raspberry Pi") link — how it actually works

- `Components.Zeroconf.Connect.FindRaspberryPi(serviceType, serviceName)` uses the
  **Zeroconf** NuGet package (mDNS/NSD): the Pi advertises a service, the Windows app
  browses for it, then stores `RaspiConfig { ip, DisplayName, port }` and talks HTTP to
  that ip:port (HttpClient everywhere; protobuf-net is also referenced).
- The Pi-side firmware is **not** in the installer, so the exact wire format still needs
  capture (easy: run the app + watch the port, or sniff mDNS).
- This confirms the architecture the user described: Windows app = brain, Pi = dumb
  networked speaker. Our design inverts it: the daemon on the Pi *is* the brain.

## Verdict: fork vs rewrite

The app's whole domain surface is 7 entity types and ~15 service methods — tiny.
The two things that must change (calculation model, audio-routing model) are exactly
the two things baked into its database schema and its prayer-time dependency.
A fork means migrating an SQLite schema, replacing the adhan dependency with a
different library, and rewiring every Quartz job anyway — while staying Windows-only.
**Greenfield rewrite wins**, reusing Smart Azan's *concepts* (adhan queue, per-prayer
adjustments, Pi-on-LAN) but not its code. Python daemon (adhan-python + pychromecast +
zeroconf) runs identically on Windows and Pi.

## Things worth keeping from Smart Azan (ideas, not code)

- Per-prayer ±minute adjustments (`PrayerAdjustment`) — masjid-convention friendly.
- The adhan queue concept (pre-adhan intro, dua before/after adhan, surah scheduling).
- mDNS discovery of LAN audio endpoints — generalize it to *any* discovered device.
- Volume-per-adhan (`AdhanVolume` table).

## The Pi protocol, captured live (2026-11-10)

The wire format was recovered without touching the box's write paths, by
advertising enumeration and read-only GETs against the Pi on the LAN where this
was researched (its address and mDNS name are left out on purpose; `research/`
holds the probes, and `probe_smartazan_pi.py` needs the host named on the
command line so it can never point at somebody's house by accident).

**What the box advertises**

* `_smartazan._tcp.local.` instance `Raspberry Pi Azan (11)` on **port 9874**.
* A stale `_http._tcp.local.` record `Adhan Player (5051)` pointing at port 5500,
  which refuses connections - a leftover from an older image. mDNS alone is not
  enough; you have to try the records.

**Port 9874 is ASP.NET Core / Kestrel** (this is the newer, Windows-Pi-image
generation of the app). Read-only replies:

| request | reply |
|---|---|
| `GET /api/Settings/ping` | `Pong` |
| `GET /api/Settings/getjobs` | plain-text job log: `20261108-DUHUR`, `20261110-MAGRIB`, `20261109-ISHA`, and lines like `syncMainAdhanViaLatLngLinux  will play at: Tuesday, 10 November 2026 18:00:00 was played at: 11/10/2026 5:00:00 PM` |

The job names are spelled `DUHUR` / `MAGRIB`, and each job carries a *will play
at* / *was played at* pair - so the Pi holds its own schedule and its own clock
of what it has already fired. The Windows binary's strings confirm the client
uses `http://{0}:{1}/api/Settings/` and `/api/Settings/getjobs`.

A TRACE-based route sweep (315 candidate paths) returned **no 405s**, which means
every remaining verb is POST-only. Those were deliberately not probed: POSTing to
an unknown route could make the box play audio, rewrite its settings, or reboot.

**The older public image is documented in the open**: `github.com/highwingers/RaspBerryPiAdhan`
is a Flask app exposing `GET /api/getData?id=`, `GET /api/getAdhanSettings?id=`,
`POST /api/updateAdhanSettings` (form field `AdhanSettings`, JSON),
`POST /api/addCustomSchedule`, `POST /api/configureDevice` (fields `address`,
`speaker`, `speakername`, **`method`**, `timezone`, **`asr`**),
`POST /api/deleteJob`, `POST /api/exeCommand {"query":1}` (reboot),
`POST /api/updateSoftware` (`git reset --hard` + pull), `/api/bluetooth/*`, and
blueprint routes `GET /speaker/api/speakerlist` and
`GET /speaker/api/playMedia?deviceName=&mediaUrl=` - i.e. the Pi drives its own
Chromecast and Bluetooth speakers. `exeCommand`, `updateSoftware` and `playMedia`
must never be called by a third party.

**Design consequence, and it is the important one.** Both Pi generations are
*self-scheduling*: the box stores `method` and `asr` and computes its own times
with its own PrayTimes.py. So the missing-Shia-method problem exists on the Pi
too, one layer below the Windows app - configuring a Pi for a method its copy of
PrayTimes.py does not contain is not possible no matter what the PC does.
muezzin inverts this: the daemon computes, the box only plays (`POST /play` with
URLs or base64 files, `_muezzin._tcp` for discovery). Any method the daemon can
express, the Pi can play.

**Compatibility decision.** `muezzin devices` lists `_smartazan._tcp` boxes so
they are visible, but muezzin does not command them. Their only audio route is a
`mediaUrl` the *Pi* fetches on a schedule the *Pi* owns, and their settings routes
rewrite the box's prayer configuration. Speaking our own protocol on a Pi that
already runs Smart Azan's image is cleaner than reverse-engineering a write API
whose worst case is `git reset --hard`.

