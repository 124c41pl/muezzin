# muezzin as a Windows service — proof of concept

Not a shipping installer yet. This is the smallest thing that proves the shape:
a frozen `muezzin.exe`, wrapped by WinSW, starting at boot, over the same
`config`/`media` folders the container users already have. The decision record
is the comment at the bottom of `muezzin-service.xml`; read that first.

## What is here

| File | What it is |
|---|---|
| `muezzin.spec` | PyInstaller: the console script becomes one self-contained `muezzin.exe` |
| `muezzin-service-entry.py` | The frozen build's entry: the same `muezzin.cli:main` the console script runs |
| `muezzin-service.xml` | WinSW's whole service definition: what starts, when, and what happens when it dies |
| `build.ps1` | Builds the exe and assembles a folder you could ship |
| `install.ps1` | Creates `%ProgramData%\muezzin`, migrates an existing profile, installs and starts the service, opens the two firewall ports |
| `uninstall.ps1` | Stops and removes the service; leaves every folder it made, on purpose |

## What has actually been run (Windows 11, Python 3.15.2, PyInstaller 6.22.3)

The exe builds (15 MB, one file) and inside it: `--version` says `muezzin
0.1.6`; `methods` lists the presets; `where tehran --write` and `times` compute
real numbers, so the bundled tzdata answers for a non-local zone; the panel
served 200 with its full page on a scratch port; `devices` found this LAN's
four Cast speakers and two groups — zeroconf works frozen; and `play-now`
through a `kind: file` output wrote `test-chime.wav` (127,934 bytes) to disk.
Two traps the first builds fell into and kept, written into the spec and the
scripts where they happened: analysing `cli.py` as the entry breaks the
package's relative imports at start, and PyInstaller's progress log on stderr
kills a `Stop`-preference build script at its first INFO line.

Not run here: WinSW itself (its download is a fetch from GitHub that this
machine's sandbox refused — put `WinSW-x64.exe` in `winsw\` by hand and re-run
`build.ps1`), and therefore the service install/start/stop cycle, the boot
start, and the firewall rules. Those are the UAT half of this PoC, on the
machine that will host the service.

## Build and try it

```powershell
pip install -e ..\.. ; pip install pyinstaller   # once, in a venv (build.ps1 finds ..\..\.venv itself)
.\build.ps1          # builds dist\muezzin.exe and assembles a folder you could ship
.\install.ps1        # elevated; see -ConfigSource / -MediaSource below
# open http://<this machine>:8020 and finish setup the way the README says
.\uninstall.ps1
```

`install.ps1` copies a profile and audio into `%ProgramData%\muezzin` only if
you point it at some (`-ConfigSource`, `-MediaSource`) or unless that folder
already exists — it never overwrites a profile, the same rule the container's
entrypoint follows.

## What this PoC deliberately does not settle

* **`pc_speakers` is expected not to work as a service.** A Windows service
  runs in Session 0, and the winmm path in `localplay.py` is not reliable
  there. `google_cast`, `lan_box` and `file` are what this shape is for. If
  PC speakers turn out to matter, the answer is a scheduled task in the user
  session, not a service — measure before choosing.
* **No GUI installer, no upgrade path, no code signing.** A real one is MSI
  (WiX) around these same pieces, or an Inno Setup script; WinSW has
  `uninstall` + `install` for a manual upgrade, which is enough for UAT.
* **The exe name doubles as the firewall subject.** PyInstaller's one-file exe
  runs a bootloader that starts a child of the *same* path, so one
  `netsh advfirewall` rule keyed to the exe covers both. If we ever switch the
  spec to one-dir, re-check that rule, not just the paths.
* **`latest` still means nothing here.** Build numbers come from the git tag,
  like the image pipeline, so a UAT report names the version it tested.
