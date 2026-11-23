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
.\build.ps1
```

That prints one line that matters: `dist\muezzin-<version>-setup.exe`, about
22 MB, which carries the frozen exe, the service wrapper and the service
definition inside it. The version comes out of `pyproject.toml`, like the image
pipeline, so a UAT report can name what it tested.

## What has actually been run here (Windows 11, Python 3.15.2, PyInstaller 6.22.3, Inno Setup 6.7.3)

The exe builds — 15 MB, one file — and inside it: `--version` says `muezzin
0.1.6`; `methods` lists the presets; `where tehran --write` and `times` compute
real numbers, so the bundled tzdata answers for a non-local zone; the panel
served 200 with its full page on a scratch port; `devices` found this LAN's four
Cast speakers and two groups, so zeroconf works frozen; and `play-now` through a
`kind: file` output wrote `test-chime.wav` (127,934 bytes) to disk. WinSW is
pinned to v2.12.0 and its x64 binary (18,243,033 bytes) downloads and stages
fine — an earlier note here blamed the sandbox for a missing WinSW, which was
wrong: the `releases/latest` URL 404s, and the versioned asset does not. The
`.iss` compiles clean with no warnings.

`muezzin init -c <path>` was run with the frozen exe, because a first install
has to answer it: exit 0 writing the profile and the `media` folder, exit 1 the
second time rather than rewriting it. And `muezzin daemon -c <a file that does
not exist>` exits 2. That second one is why the setup runs `init` for itself
before registering the service: pointed at nothing, the daemon leaves at once,
and under WinSW "leaves at once" reads as a crash — restart at 10 seconds,
restart at 60, and a browser aimed at a port nobody answers on with nothing in
the log to say why. A household that is being built from the page instead of
from a copied profile is the common case, not the exception.

Not run here: the wizard itself, and therefore the install/start/stop cycle, the
boot start, the migration, the first-profile step, the upgrade-over-an-existing-
service path and the firewall rules. Those are Part C of `docs/UAT-CHECKLIST.md`,
on the machine that will host the service.

Two traps the first builds fell into and kept, written where they happened:
analysing `cli.py` as the entry breaks the package's relative imports at start,
and PyInstaller's progress log on stderr kills a `Stop`-preference build script
at its first INFO line.

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
  get compared on the same machine at the same minute.
* **An upgrade replaces files a running service is holding open.** The setup
  stops and unregisters the old service before copying, then re-registers
  (WinSW refuses to register a name that is already taken). If that stop ever
  fails, Windows offers to close the offending process — an honest prompt, not
  a silent overwrite.
* **The exe name doubles as the firewall subject.** PyInstaller's one-file exe
  runs a bootloader that starts a child of the *same* path, so one `netsh
  advfirewall` rule keyed to the exe covers both. If the spec ever moves to
  one-dir, re-check that rule, not just the paths.
* **No code signing, and the service logs sit in the install folder** where
  only an administrator can read them. Both are real gaps for a distribution
  channel; neither is a gap for UAT.
* **MSI/WiX is deferred on purpose.** It is the right answer once this shape
  survives a night on real speakers, and the wrong answer while the shape is
  still moving: an `.iss` is edited in seconds, a WiX tree is not. The macOS
  version, when it comes, reuses this frozen exe's sibling under launchd.
