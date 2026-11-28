# PyInstaller spec: muezzin's console script as one self-contained muezzin.exe.
#
# Why one file: the service wrapper's job is to start *a path*, and the
# firewall rule in install.ps1 is keyed to that path too. One directory to
# ship is one less thing an installer script can get wrong. The cost is real
# and stated here rather than hidden: a one-file exe unpacks to a temp folder
# on every start, so boot-to-listening is a couple of seconds slower, and
# antivirus scans are harder on it. If that ever measures badly, the one-dir
# form is a two-line change at the EXE call below — but re-check the firewall
# rule then: in one-file mode the bootloader and its child are the same path,
# and in one-dir mode what you ship is a folder, not that path.
#
# The entry point is muezzin-service-entry.py, which calls the same
# muezzin.cli:main pyproject's console script names. It is a file rather than
# the module path because the first build proved the point: analysing
# src/muezzin/cli.py directly makes it a top-level script, its package-relative
# imports fail at start, and nothing in the build says so.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import os

# zeroconf carries a compiled extension (_dnssd / _Cy) and submodules it picks
# per platform at import time; listing the lot is cheaper than being sorry.
hiddenimports = collect_submodules("zeroconf")

# tzdata is the zone database Windows does not have, and zoneinfo reads it as
# data files at lookup time — frozen, missing zones fail late (at the first
# prayer in an odd zone), which is the worst place to find out.
datas = collect_data_files("tzdata")

# Which try at a release this build is, carried inside the exe.
#
# build.ps1 writes a one-line stamp (`0.1.6-r7`) next to this spec right before it
# compiles, and the stamp travels *inside* the exe rather than beside it: the installed
# program folder is replaced whole on every upgrade, and a loose file next to the exe is
# one more thing that can be left behind or overwritten by an older build. Read back out
# by muezzin.release_version(), which is what the panel's bottom line and the daemon's
# first log line print - the only two places a machine nobody can walk over to says what
# it is holding. A build with no stamp here - a checkout, pip install, the container
# image - carries none and says its plain version.
#
# The name is muezzin.RELEASE_FILE; a test keeps this spelling from drifting away from it.
_stamp = os.path.join(os.path.dirname(os.path.abspath(SPEC)), "MUEZZIN-RELEASE.txt")
if os.path.exists(_stamp):
    datas += [(_stamp, ".")]

# The picture the exe wears.
#
# With no icon line PyInstaller puts its own Python logo in the exe's resources, which is
# what every build here did until somebody pointed out that a folder of muezzin was
# showing a picture of Python. The file is drawn in this folder by make-icon.py - the
# panel's own palette, one geometry, seven sizes - and the name is spelled as an absolute
# path for the reason the stamp above is: the build script may be standing anywhere when
# it hands this spec over, and a bare name would be looked up there instead of here.
#
# Unlike the stamp there is no "if it exists" here, and that is deliberate: a missing
# stamp is honest for a build that was never a candidate, while a missing icon is a build
# that quietly ships wearing somebody else's face. Better to fail at compile time.
# The .iss names the same file for the setup program, and the page embeds a second render
# of the same drawing as its tab icon: one mark, four places it can be seen.
_icon = os.path.join(os.path.dirname(os.path.abspath(SPEC)), "muezzin.ico")

a = Analysis(
    ["muezzin-service-entry.py"],
    pathex=["..\\..\\src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Everything muezzin does not touch at all. Listing exclusions is how this
    # stays honest as dependencies grow: a build that carries less is a build
    # that failed to import something, and the excludes below are all modules
    # this program never names.
    excludes=["tkinter", "matplotlib", "PIL", "numpy", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="muezzin",
    debug=False,
    strip=False,          # Windows: strip is a no-op; left out of the debate by saying so
    upx=False,            # upx gets builds quarantined by exactly the AV that UAT machines run
    console=True,         # WinSW captures stdout as the service log; a windowless build loses that
    icon=_icon,           # drawn by make-icon.py; without it this is a Python logo on a muezzin exe
    disable_windowed_traceback=False,
    onefile=True,
)
