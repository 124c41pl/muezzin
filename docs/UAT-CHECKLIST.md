# UAT checklist

Three halves, because on Docker Desktop on Windows the container, a native run
and the installed service cover different things. The measured reason is in
`docs/HOW-IT-WORKS.md`
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
half that touches sound, in a console in your own session. The same rows against
the installed service are Part C.

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

B8 is the one that proves the deployment story: the container, the console run,
and the service in Part C are the same program over the same folders.

## Part C — the installed service (installer UAT)

Built per `packaging/windows-service/README.md`; the file under test is
`dist\muezzin-<version>-setup.exe`, and every row starts at a double-click. No
PowerShell, no `pip`, no Python on the machine. **Stop any console daemon first**
— the service wants :8020 and :8010 for itself, and a daemon already holding
them makes the service look broken when nothing is broken.

| # | Check | Expected | Pass |
|---|---|---|---|
| C1 | Double-click | Licence, folder, and at most one UAC prompt; the wizard never asks for a terminal | |
| C2 | Layout | `%ProgramFiles%\muezzin\` holds exe, wrapper and service definition; `%ProgramData%\muezzin\` holds `media\` and `out\`; a service named `muezzin`, Automatic, registered | |
| C3 | A household from nothing | Install with no profile anywhere: the setup writes a starter to `%ProgramData%\muezzin\muezzin.yaml` (the same first act as the container's entrypoint), the service **stays running**, and the page's "write it" lands in that file. Without that starter the daemon exits on a missing profile and the service just restarts forever | |
| C4 | Page from another device | `http://<this machine>:8020` answers across the LAN — the one thing Part A could not show | |
| C5 | Migration | A `muezzin.yaml` in the checkout or beside the setup file is offered, copied, and left where it was; when `%ProgramData%\muezzin\muezzin.yaml` already exists, the page is not shown at all | |
| C6 | Never overwrite | Re-running the setup leaves the existing profile byte-identical (hash it before and after) | |
| C7 | `devices` as a service | Compare with B1 on the same machine in the same minute. If the console finds speakers and the service finds none, that is the LocalSystem question: retry with the service-account page filled in and record which of the two worked | |
| C8 | Firewall | `netsh advfirewall firewall show rule name="muezzin panel"` and `...media` exist, pointing at the installed exe, `Profile=Any` and `RemoteAddress=LocalSubnet`. Not `Profile=Private`: measured on a household machine, both real adapters were filed **Public**, and a Private-only rule left the speakers stranded while a browser on the same machine still reached :8020 over loopback | |
| C9 | Reboot | The machine comes back, the service comes up by itself, the next event fires unattended, and `muezzin.out.log` in the install folder shows it | |
| C10 | Upgrade | Run a newer setup over an installed one: old service stopped and unregistered, files replaced, service registered and started, no "file in use" fight, `%ProgramData%` untouched. The setup's log has all three lines — `muezzin: asked the existing service to stop`, `muezzin: unregistered the existing service`, and `muezzin: upgrade: nothing named muezzin was holding C:\Program Files\muezzin` (or `ended N process(es) …`, which means the sweep had to end something the stop did not). `Get-Process muezzin* -ErrorAction SilentlyContinue` afterwards is empty. And `netsh advfirewall firewall show rule name="muezzin panel"` prints **one** rule, not two — the setup deletes both names before adding them | |
| C11 | Uninstall | Service gone and both firewall rules gone; `%ProgramData%\muezzin` still there, with the message saying so. And `%ProgramFiles%\muezzin` is **gone**, not half-emptied: `Test-Path "$env:ProgramFiles\muezzin"` is `False`, and `Get-Process muezzin*` names nobody. The setup's log ends its uninstall section with `muezzin: uninstall: nothing named muezzin was holding …` or `ended N process(es) …`, and after that a line about the service's own logs — `muezzin: uninstall: deleted N log file(s) the service had been writing in C:\Program Files\muezzin, needing M wait(s) of 750 ms`. Those logs and not the service are what kept the folder alive the first time this was uninstalled on a real machine: the exes went, and `muezzin-service.err.log`, `.out.log` and `.wrapper.log` stayed behind still open by the wrapper on its way out. If the line instead reads `1 of 4 log file(s) … would not delete in 9 tries`, something had a log open when the uninstall ran; the closing message says the same thing, and a restart plus deleting that folder by hand finishes it — file the log either way. A third closing message is worth knowing about because it is the one that means nothing went wrong: `muezzin is removed, but C:\Program Files\muezzin is still there because it is not empty: <up to three names>. None of that is muezzin, and none of it is your profile …` — that is the installer keeping a folder that holds something you put there, and naming it rather than leaving you to wonder. One more thing to look for rather than fix: uninstall from a script (`unins000.exe /VERYSILENT`) and the closing words appear **in the log only**, which is deliberate — a message box nobody is looking at never gets answered, and the uninstaller then never exits | |
| C12 | Service account | Install with a name typed on the account page: `sc qc muezzin` shows that account as the LogOn and the service starts. Then run a newer setup over it with both fields empty: `sc qc muezzin` **still** shows that account — the `<serviceaccount>` block is carried across the upgrade rather than falling back to LocalSystem | |
| C13 | Restart on crash | With the service running, `taskkill /F` the `muezzin.exe` process: the service comes back by itself within about ten seconds (`sc query muezzin` twice, a minute apart). This is what the `<onfailure>` lines in the service definition are for | |
| C14 | A speaker a person actually set up | From the page only: location, **look again**, **use** a Cast speaker, upload a recording, give one prayer that recording or **random**, then press **test** on that speaker's row. Sound comes out of the speaker. If it does not, the daemon's log now says which URL it was handed — that address has to be on the speakers' network, and :8010 has to be open to them (row C8) | |
| C15 | A machine attached to something else too | On a machine with a mesh VPN (Tailscale, ZeroTier) or a WSL / vEthernet adapter: with a speaker playing, the log line for a silent speaker names an address on the speakers' own network and not the VPN's (`100.64.x`). This is the failure the row exists for — discovery fine, levels fine, app launched, house silent, because the adapter that owns the default route was asked which address to publish | |

| C16 | A daemon nobody can ask politely | The failure this row exists for. With the service running, `sc stop muezzin`, then `Get-Process muezzin*`: if a daemon is still there after the service said it stopped — seventeen minutes later on the first machine this shipped to — run the uninstaller straight away. It ends the orphan (`muezzin: uninstall: ended 1 process(es) named muezzin that were holding C:\Program Files\muezzin`), deletes the whole folder, and closes with the plain message. If the stop does release the process on your machine, stage it by hand: `taskkill /F /IM muezzin-service.exe` leaves the daemon running with nothing left that can stop it, which is the state a half-finished uninstall leaves behind. Either way, `%ProgramFiles%\muezzin` is gone afterwards and running the setup again copies without a "file in use" complaint — on that first machine the leftovers were two exes with no service, no uninstaller and no way to remove them, and the new setup could not start | |

| C17 | A stop button that stays put | Press **test** on a speaker's row and, while the recording is still coming out, move that group's level slider or press **same as the group** under it: the row's **stop** button is still on that row afterwards, and still there after a reload of the page. Forty seconds in, press it — the speaker goes quiet and the page says `asked <name> to stop`. The other half of this row is the half that was unreliable rather than missing: press **stop** about a second after **test**, before any sound has started, and the page still says `asked <name> to stop`, and nothing begins playing a moment later. That ask used to be thrown away while the connection to the speaker was still being made, which is why the button seemed to work only once a file had already begun | |
| C18 | The page says which build it is | Look at the foot of the panel: on a candidate build it names the try as well as the release — `muezzin 0.1.6-r8 · MIT ·`, not `muezzin 0.1.6 · MIT ·`. `muezzin --version` and the line the daemon writes when it starts say the same number, and that number is the one in the name of the setup file that was run. | The one question a report about a machine nobody can walk over to is able to answer. Before it, the bottom line said `0.1.6` about the fourth try and the seventh try alike, and the only thing that told them apart was the name of a setup file that machine may not still be holding. |

If the page never answers, two files say why: the setup's own log — written by
itself into `%TEMP%\Setup Log*.txt`, since the installer asks for it; pass
`/LOG=setup.log` if you want it somewhere you chose — where
every line the wizard wrote begins `muezzin:`, and
`%ProgramFiles%\muezzin\muezzin-service.wrapper.log` from the wrapper. `muezzin-
service.exe status` and `sc query muezzin` are the two commands worth typing, and
the setup's log names both.

C7 and C10 are the two rows this branch cannot answer on its own: one is a fact
about your LAN, the other is a fact about upgrading something you already
trust. C3 is the row that a fresh install either passes or wastes your evening
on. C14 and C15 are the two that only a real speaker on a real network can
answer, and they are the rows that failed first, on the author's own machine,
with the whole install otherwise green. C16 is the row that a leftover file
answers for you: if `muezzin.exe` is sitting in `%ProgramFiles%\muezzin` after an
uninstall, that row has failed, and its log line is the thing to paste into a bug
report. C17 is the one row with no log line to read at all: it is about the page and
the speaker at once, and what it failed at was leaving a house with sound coming out
of it and nothing on the page to ask for quiet.

## Filing results

For each failure: the image tag or commit, the row number, what the row said,
what you saw, and the log lines (`docker logs muezzin-uat`, or the daemon's
stdout). One issue per row unless rows share a cause.
