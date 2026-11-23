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

# zeroconf carries a compiled extension (_dnssd / _Cy) and submodules it picks
# per platform at import time; listing the lot is cheaper than being sorry.
hiddenimports = collect_submodules("zeroconf")

# tzdata is the zone database Windows does not have, and zoneinfo reads it as
# data files at lookup time — frozen, missing zones fail late (at the first
# prayer in an odd zone), which is the worst place to find out.
datas = collect_data_files("tzdata")

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
    disable_windowed_traceback=False,
    onefile=True,
)
