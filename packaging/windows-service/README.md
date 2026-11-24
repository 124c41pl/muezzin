# muezzin as a Windows service

The thing a user runs is one file: `dist\muezzin-<version>-setup.exe`, compiled
from `muezzin-setup.iss`. Double-click, answer three pages, and the daemon is a
service that starts with the machine, over the same profile and media folders
the container users already have. The decision record for the shape is the
comment at the top of `muezzin-service.xml`; read that first.

The `.ps1` files here are **not** for users and never will be. They are the
scaffolding that builds and debugs the pieces the installer ships, kept because
rebuilding the exe by hand is faster than arguing with a wizard while you are
testing one.

## What is here

| File | What it is |
|---|---|
| `muezzin-setup.iss` | **The product path.** Inno Setup: the wizard, the migration ticks, the service account page, the firewall rules, the service install and uninstall |
| `muezzin.spec` | PyInstaller: the console script becomes one self-contained `muezzin.exe` |
| `muezzin-service-entry.py` | The frozen build's entry: the same `muezzin.cli:main` the console script runs |
| `muezzin-service.xml` | WinSW's whole service definition: what starts, when, and what happens when it dies |
| `build.ps1` | Scaffolding: builds the exe, fetches WinSW, stages `stage\`, runs `ISCC` on the `.iss` |
| `install.ps1` | Scaffolding: the same steps the installer does, in a window you can read line by line |
| `uninstall.ps1` | Scaffolding: stops and removes the service; leaves every folder it made, on purpose |

## Build it

Inno Setup 6 has to exist on the build machine (`winget install JRSoftware.InnoSetup`);
everything else `build.ps1` needs is the repo's own venv plus PyInstaller.

```powershell
pip install -e ..\.. ; pip install pyinstaller   # once; build.ps1 finds ..\..\.venv by itself
.\build.ps1          # the release itself: muezzin-0.1.6-setup.exe
.\build.ps1 -RC 7    # the seventh try at it: muezzin-0.1.6-r7-setup.exe
```

That prints one line that matters: `dist\muezzin-<version>-setup.exe`, or
`dist\muezzin-<version>-r<N>-setup.exe` when `-RC` is given — about 22 MB either
way, carrying the frozen exe, the service wrapper and the service definition
inside it. The version comes out of `pyproject.toml`, like the image pipeline, so
a UAT report can name what it tested.

The candidate number is not only a filename. `-RC 7` also writes
`MUEZZIN-RELEASE.txt` next to this script, which `muezzin.spec` swallows *inside*
the exe; `muezzin.release_version()` reads it back out, and it is what the panel's
bottom line prints (`muezzin 0.1.6-r7 · MIT · …`) and what the daemon's first log
line says. The same string goes to the installer as `/DVersion=`, so the setup
file's name and the version Programs and Features lists are the same words the
running machine uses about itself. That is the point: a household in another
building can be asked one question — *what does the bottom of the page say?* — and
a report means something. Run without `-RC` and the stamp is deleted instead of
carried over from the last candidate, so a release build cannot inherit a number
it was never built as.

## What has actually been run here (Windows 11, Python 3.15.2, PyInstaller 6.22.3, Inno Setup 6.7.3)

The exe builds — 15 MB, one file — and inside it: `--version` says `muezzin
0.1.6`, or `muezzin 0.1.6-r8` in the build made with `-RC 8` — which is also what
that build handed the page: `/api/state` on a scratch port answered
`"version": "0.1.6-r8"`, from a `dist\muezzin-0.1.6-r8-setup.exe` that Inno named
for the same string; `methods` lists the presets; `where tehran --write` and `times` compute
real numbers, so the bundled tzdata answers for a non-local zone; the panel
served 200 with its full page on a scratch port; `devices` found this LAN's four
Cast speakers and two groups, so zeroconf works frozen; and `play-now` through a
`kind: file` output wrote `test-chime.wav` (127,934 bytes) to disk. WinSW is
pinned to v2.12.0 and its x64 binary (18,243,033 bytes) downloads and stages
fine — an earlier note here blamed the sandbox for a missing WinSW, which was
wrong: the `releases/latest` URL 404s, and the versioned asset does not. The
`.iss` compiles clean, and the `[Code]` section it ships was run: compiled
straight out of the file into a probe installer with no `[Run]` and no `[Dirs]`
sections, run `/VERYSILENT`, exit 0, log showing the welcome/migration/account
pages built, `ssPreInstall` and `ssPostInstall` both reached and the account
fallback written. That probe is how the crash below was found and how the fix
was checked, and it installed a text file into a temp folder.

The first builds of that wizard did crash, on a tester's screen and not in the
build log: asking for `{app}` in `InitializeWizard` aborts the whole setup with
"An attempt was made to expand the 'app' constant before it was initialized",
because the install folder has not been chosen yet. Reproduced here with a
three-line installer whose only job was that call, so the cause is measured.
Nothing in the wizard's construction asks where the program went any more.

`muezzin init -c <path>` was run with the frozen exe, because a first install
has to answer it: exit 0 writing the profile and the `media` folder, exit 1 the
second time rather than rewriting it. And `muezzin daemon -c <a file that does
not exist>` exits 2. That second one is why the setup runs `init` for itself
before registering the service: pointed at nothing, the daemon leaves at once,
and under WinSW "leaves at once" reads as a crash — restart at 10 seconds,
restart at 60, and a browser aimed at a port nobody answers on with nothing in
the log to say why. A household that is being built from the page instead of
from a copied profile is the common case, not the exception.

Part C has since been run for real, by its author, on the machine that will host
the service, and the setup installed: the service is registered Automatic and
running, `%ProgramFiles%\muezzin` holds the exe, the wrapper and the definition,
`%ProgramData%\muezzin` holds `media`, `out`, `muezzin-tiles` and a starter
`muezzin.yaml`, both firewall rules are there pointing at the
installed exe, :8020 answers, and the daemon's own log named the next event
fifty minutes out. It also put a number on the one thing that felt slow, from the
wrapper's log and the daemon's side by side: the service was registered at
17:02:20.9 and its process started at 17:02:21.9, a second before the setup
wrote the starter profile, so the first daemon exited 2 on the missing profile
and the service's own ten-second restart delay covered the mistake — second
start at 17:02:33.3, panel answering at 17:02:34.1. Eleven of those twelve
seconds were the delay, and they were this file's bug, not a property of
services: `[Run]` entries run *before* `ssPostInstall`, measured rather than
looked up, so everything in that step happened after the service had already
tried to start. Registering and starting are now the last thing `ssPostInstall`
does, after the profile and after the account, and the same measurement says why
that also mattered for the account page — a named account written in that step
would have reached the file after the service had already started without it.

:8010 was not listening in that same check, and that is the program rather than
the install: `cli.py` starts the media server only when something needs media
URLs, and a household with no speakers configured needs none. The rule for that
port is still correct to have.

That machine was then used as a household would use it, and it failed twice in a
way no fixture had predicted. The profile was built from the page — a location,
one Cast group, five prayers drawing at random, one recording uploaded. The
speakers were found, added, given their levels and launched into the media app,
and the house stayed silent, twice, with the log reading like a delivered adhan.
Two separate things were wrong, and the second is the one that belongs to this
folder.

The first was an address. The log said `media server serving … at
http://100.64.100.6:8010`, which is this machine's mesh-VPN adapter; the old code
picked a local address by asking which one it reaches the *internet* from, and the
VPN owns the default route. Nothing on the speakers' wifi has a route into
100.64.0.0/10, so every hand-off was a URL the speaker could not fetch, while the
Ethernet adapter on the speakers' own network — 192.168.0.8 — was never consulted.
The same trick, asked about the speaker instead of about the internet, answers the
question that matters, and that is what `backends.py` and `media.py` do now, per
device, with the old question kept as the fallback when there is no route to the
device at all.

The second was this file's. `Get-NetConnectionProfile` reports both real adapters
on that machine as **Public**, and the rules the setup had opened were
`profile=private`. With the firewall's default inbound action at Block, :8010 was
therefore closed to every speaker on the network — and :8020 still answered in a
browser on the same machine, because loopback is not filtered by profile, which is
what made the symptom look like a speaker problem rather than a rule problem. the rules are now `profile=any remoteip=localsubnet`: the boundary is address space
rather than Windows' opinion of the network, and it is narrower than a port-range
rule would have been — a speaker on a *different* subnet or VLAN is now refused
where the Private-profile rule would have let it through, which is the tradeoff, and
a segmented house adds its own rule for the network its speakers live on. Both
names are deleted before they are added, because
`add rule` accumulates and an upgrade that only added would leave the previous
wording in force beside the new one.

What is *not* yet measured is the fix: the rules above were written from the
diagnosis, and the check that closes them is the next install on that machine —
row C14, which is this exact failure written as a row so that it gets run rather
than remembered.

That machine was then uninstalled, and it failed again in a different way. The
uninstaller asked the wrapper to stop at 20:49:55.797 and the wrapper wrote
"stopped successfully" six milliseconds later; the service's own stop action ran
— its `taskkill` helper appears as pid 32080 — and WinSW logged
`WaitForProcessToExit 21072+32080`; 450 ms after that, the uninstall step wrote
`WARN - Service ... is started. It may be impossible to uninstall it`. The last
line of that wrapper log is `Finished muezzin`, stamped 21:06:45: seventeen
minutes after the stop was asked for. In between, the uninstaller deleted its own
uninstaller, the service definition and everything else it could reach, and left
behind precisely the two files a live process holds open — `muezzin.exe`
(15,408,917 bytes) and `muezzin-service.exe` (18,243,033 bytes). Installing the
next package then failed on a file in use.

So the installer ends the process instead of trusting the service control
manager's answer, in `SweepOwnProcesses`: up to six seconds for anything named
`muezzin*` whose image path is under the install folder to leave on its own, then
what is left is ended, and the counts come back packed into one exit code because
that is the only channel between the check and the log. A service running under
another account does not tell this session where its image is, so a process with
no reported path counts as one of ours; the price is that a daemon started by hand
from a checkout is ended too, and a muezzin living in some other folder is left
alone either way.

And the hook that teardown was hung on never fires. The whole block — carry the
service account over, stop, unregister, sweep — was written on
`CurStepChanged(ssPreInstall)`, and Inno Setup 6.7.3 accepts that constant and
then never sends it: a probe that logged every call printed ordinals 1, 2 and 3,
none of them `ssPreInstall`, and the shipped help names only `ssInstall`,
`ssPostInstall` and `ssDone` as the steps that fire. Every install of this
package so far therefore took nothing down before the copy, which is how an
upgrade reached a running service and stopped at the lock. The block lives in
`PrepareToInstall` now, measured running before the RestartManager scan (`Found 1
files to register with RestartManager`) and before the first `Dest filename` line
— the earliest point at which the lock can be released by choice rather than met
as an error.

Both sides were then probed rather than assumed, with decoy copies of
`System32\cmd.exe` and `ping.exe` installed as `muezzin.exe` and left running in
the target folder. Upgrade, with two holders inside the install folder and one in
a different folder: `muezzin: upgrade: ended 2 process(es) named muezzin that
were holding <folder>`, the one elsewhere left running, and then `Successfully
installed the file` over the path that had been locked. Uninstall, over a running
holder of the installed file: `muezzin: uninstall: ended 1 process(es) named
muezzin …`, then `Deleting file: …\muezzin.exe`, the folder gone,
`UninstallHeld=0`. Still unmeasured is the same sequence against a real
LocalSystem service in session 0 — there the sweep catches the process on its
no-reported-path branch, which no probe on this account could produce.

Not run here: the wizard as a person experiences it (its pages were built and its
steps ran, but nothing was clicked), and therefore the boot start, the migration
and the service-account registration. The upgrade-over-an-existing-service path
is half-run: its teardown was exercised against decoy processes in the folders
above, but never against a service registered by a previous setup. Those are Part
C of `docs/UAT-CHECKLIST.md`, on the machine that will host the service.

Three traps the first builds fell into and kept, written where they happened:
analysing `cli.py` as the entry breaks the package's relative imports at start;
PyInstaller's progress log on stderr kills a `Stop`-preference build script at
its first INFO line; and `{app}` does not exist during `InitializeWizard`, which
is a runtime abort with no line number, not a compile error. One more is a word
that does not exist: this version's `MsgBox` types are `mbInformation`,
`mbConfirmation`, `mbError` and `mbCriticalError`, and `mbWarning` — the one a
person reaches for by reflex — is "Unknown identifier", caught at compile time
here only because the build script checks the compiler's exit code.

Two more, both about the wrapper's spelling rather than Inno's, and both found by
running or reading the pinned v2.12.0 rather than by trusting a memory of the
current release: the restart-on-crash actions are repeated
`<onfailure action="restart" delay="10 sec"/>` elements (a `<failure>` element
with nested `<action>`/`<delay>` is the v3 config format, and an element this
version does not read is a silent way to lose "comes back when it dies"); and
there is no command in it that sets a log-on account — `--help` lists install,
uninstall, start, stop, stopwait, restart, restart!, status, test, testwait,
version, help, and nothing else. So the setup writes `<serviceaccount>` into the
service definition itself, in `ssPostInstall`, which runs after the files land
and before that same step registers the service. A fourth trap, visible only on
an installed machine and in no log this side could produce: `[Run]` entries run
*before* `ssPostInstall`, so a service registered there is up before anything
the code step does — which is how a fresh install launched a daemon one second
before the profile it points at existed. An earlier draft of this file
claimed the setup could set an account by calling `muezzin-service.exe user`,
which is not a command and would have done nothing while the wizard said
otherwise.

## What this shape does not do

* **It does not schedule this machine's own speakers, and that is a decision
  rather than a gap.** A service runs in Session 0. Hosting muezzin as a
  service is for sending the adhan somewhere else — `google_cast`, `lan_box`,
  `file`. `pc_speakers` stays what it always was: the output you use from a
  console in your own session.
* **Whether LocalSystem can see the LAN is measured, not assumed.** The
  installer offers a page that names a service account, because a service
  running as LocalSystem may not reach the interfaces or the firewall profile
  Cast discovery needs. Row C7 is where native `devices` and service `devices`
  get compared on the same machine at the same minute, and row C12 checks that
  the account named there is really the one `sc qc muezzin` reports — and that a
  later upgrade keeps it instead of sliding back to LocalSystem, which is what
  `CarryAccountBlock` in the `.iss` is for.
* **A named account's password is stored in cleartext**, in
  `%ProgramFiles%\muezzin\muezzin-service.xml`, because that is how WinSW takes
  an account and that folder is readable by every local user on the machine.
  The wizard says so on the page that asks for it. This is why leaving the page
  empty is the default worth measuring first, and why a dedicated service user
  should be a user with no other privileges, not the account you read your mail
  from. WinSW can also hold a DPAPI-encrypted password; wiring the setup to
  produce one is work nobody has done yet.
* **An upgrade replaces files a running service is holding open.** The setup
  stops and unregisters the old service before copying, then re-registers
  (WinSW refuses to register a name that is already taken). If that stop ever
  fails, Windows offers to close the offending process — an honest prompt, not
  a silent overwrite.
* **The exe name doubles as the firewall subject.** PyInstaller's one-file exe
  runs a bootloader that starts a child of the *same* path, so one `netsh
  advfirewall` rule keyed to the exe covers both. If the spec ever moves to
  one-dir, re-check that rule, not just the paths.
* **No code signing**, and the service's own logs sit in the install folder —
  which every local user can read, not only an administrator, along with the
  profile path and any account name the setup was given. Both are real gaps for
  a distribution channel; neither is a gap for UAT.
* **MSI/WiX is deferred on purpose.** It is the right answer once this shape
  survives a night on real speakers, and the wrong answer while the shape is
  still moving: an `.iss` is edited in seconds, a WiX tree is not. The macOS
  version, when it comes, reuses this frozen exe's sibling under launchd.
