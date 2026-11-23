# UAT checklist

Two halves, because on Docker Desktop on Windows the container and a native run
cover different things. The measured reason is in `docs/HOW-IT-WORKS.md`
("Running in a container"): with Docker Desktop on this machine the speaker scan
found 6 devices natively and 0 from a container, bridge network **and**
`--network host` alike, because the container sits in a VM and mDNS never leaves
it. So do not mark a speaker row "failed" in Part A — it is not testable there.
Mark it "n/a, see Part B".

Version discipline: **pin the tag** (`ghcr.io/124c41pl/muezzin:0.1.6`), never
`latest`, so a UAT report means something after the next release. Record the tag,
the Docker version and the OS for every run.

## Part A — the container (image UAT)

Setup, from an empty folder:

```powershell
mkdir uat; cd uat; mkdir config; mkdir media
# copy or record at least one clip into .\media before the first start
docker pull ghcr.io/124c41pl/muezzin:0.1.6
docker run -d --name muezzin-uat -p 127.0.0.1:8080:8020 `
  -v "${PWD}\config:/app/config" -v "${PWD}\media:/app/media" `
  ghcr.io/124c41pl/muezzin:0.1.6 `
  daemon -c /app/config/muezzin.yaml --web 8020 --allow-host 127.0.0.1
```

(On a Linux box swap `-p` for `--network host` and the `--allow-host` flag away;
that is the shape production uses, and it is the one this checklist's Part A
rows were written for. The published-port shape above is what a Windows tester
actually has, and it is exactly the bridge variant the compose file documents —
including why `--allow-host` is not decoration.)

| # | Check | Expected | Pass |
|---|---|---|---|
| A1 | First run on an empty `config` | Log says it wrote a starter; `config/muezzin.yaml` exists on the Windows side; container stays up | |
| A2 | Restart with the profile present | The starter is **not** rewritten: a hand-edited comment or a `#` line survives `docker restart` | |
| A3 | Page loads | `http://127.0.0.1:8080` answers from the same machine; header, Events card, gold band naming the placeholder location | |
| A4 | Location | "find it" with a postal code answers; **write it** lands lat/lon/timezone in `muezzin.yaml` | |
| A5 | Method | Dropdown changes `method:`; one manual override (e.g. `isha_angle`) survives a save | |
| A6 | Times agree | `docker exec muezzin-uat muezzin times -c /app/config/muezzin.yaml` matches what the page shows | |
| A7 | `next` | `docker exec ... muezzin next` shows events, weekday filter, and the outputs each resolves to | |
| A8 | Upload | A clip ≤64 MB from the page lands in the mounted `media` folder; an existing name is never overwritten; over-64 MB is refused with words | |
| A9 | Library | The folder listing shows the clip; the Random switch writes/erases `library: exclude:`; Event column appends to an event's list | |
| A10 | YAML editor | A valid edit saves and the daemon picks it up **without a restart**; an invalid edit is refused and the file on disk is unchanged | |
| A11 | Hijri | Date shows with the Arabic month name; `hijri_offset` moves it | |
| A12 | Map tiles | Squares arrive, are credited, and are kept in `muezzin-tiles/` beside the profile; `map_tiles: off` draws from numbers alone | |
| A13 | `--read-only` | Start a second container with `--read-only`: every save is a 403, the page still shows times | |
| A14 | Ports from the environment | `-e MUEZZIN_WEB_PORT=8021` moves the page without touching the command; a command-line number still wins | |
| A15 | `kind: file` output | `play-now` leaves the file under `/app/out` (compose) or the mounted out folder | |
| A16 | Stop behaviour | `docker stop` ends the container in seconds, not after the 10s kill timeout (the entrypoint `exec`s the daemon) | |
| A17 | Non-root | `docker exec muezzin-uat id` says uid 10001 | |

Not applicable in Part A — expected, not failures:

| Item | Why |
|---|---|
| Speaker scan / Cast / `lan_box` discovery | mDNS cannot cross the Docker Desktop VM. 0 devices is the measured, correct answer there |
| `pc_speakers` | A container has no audio device by design |
| Media URL routable to a speaker | The advertised address is `172.17.x.x`, which a speaker has no route to |

## Part B — native Windows run (audio-delivery UAT)

Same image does not apply here: this half runs the checkout, because it is the
half that touches sound. Future note: once the service installer lands
(`packaging/windows-service/`), the same rows run against the service instead of
a console window.

| # | Check | Expected | Pass |
|---|---|---|---|
| B1 | `muezzin devices` | The LAN's Cast devices/groups/boxes appear | |
| B2 | Page "look again" / "use" | A discovered speaker becomes an output row with a name you chose | |
| B3 | `test` button | Reports what the **speaker** said, including its own errors, not what muezzin hoped | |
| B4 | `play-now` through each kind | Sound actually comes out, and the lead-time note in `next` is consistent with what you heard | |
| B5 | Group levels | Asking a group moves rooms for the length of the call and hands each back its owner's level afterwards | |
| B6 | Volume honesty | The PC's own volume never moves; `volume:` only touches speakers muezzin casts to | |
| B7 | Reboot | With whatever keep-alive you use, the daemon is back and the next event fires unattended | |
| B8 | Same profile as Part A | The YAML written in the container loads natively with no edits | |

B8 is the one that proves the deployment story: the container and the native
run, and later the Windows service, are the same program over the same folders.

## Filing results

For each failure: the image tag or commit, the row number, what the row said,
what you saw, and the log lines (`docker logs muezzin-uat`, or the daemon's
stdout). One issue per row unless rows share a cause.
