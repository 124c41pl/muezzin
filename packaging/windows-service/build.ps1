# Builds the frozen exe and assembles a shippable folder (dist\muezzin-service\).
# Run from this directory. Needs the repo installed in a venv, plus pyinstaller:
#
#   pip install -e ..\..        # the muezzin package
#   pip install pyinstaller
#   .\build.ps1                 # picks ..\..\.venv automatically when it exists
#
# Needs the network the first time, for WinSW itself; if that fetch fails, the
# message says where to put the file by hand rather than building a half folder.

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Join-Path $here "..\.."
$dist = Join-Path $here "dist\muezzin-service"

# Version discipline, the same rule the image workflow uses: what is built must
# name the version it came from, so a UAT report means something afterwards.
$version = (Select-String -Path (Join-Path $root "pyproject.toml") -Pattern '^version = "([^"]+)"').Matches[0].Groups[1].Value

Write-Host "building muezzin $version" -ForegroundColor Cyan

# 1. The frozen app. The spec resolves its own relative paths from the
#    *current* directory, so pyinstaller has to run from here. Prefer the
#    repo's own venv, because that is the interpreter that has muezzin and its
#    dependencies — and a build from a different one fails at Analysis, with a
#    log full of hooks and not one word about the venv you forgot.
$pyinstaller = Join-Path $root ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $pyinstaller)) { $pyinstaller = "pyinstaller" }
# PyInstaller writes its whole progress log to *stderr*. With this script's
# Stop preference that is not progress at all: PowerShell promotes each line to
# an error record and the build dies at the first INFO line — measured, not
# guessed. So the noise is allowed through here, and the exit code below is
# what decides whether the build worked.
$prevPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $pyinstaller --clean --noconfirm (Join-Path $here "muezzin.spec")
$code = $LASTEXITCODE
$ErrorActionPreference = $prevPreference
if ($code -ne 0) { throw "pyinstaller failed (exit $code)" }
$exe = Join-Path $here "dist\muezzin.exe"
if (-not (Test-Path $exe)) { throw "pyinstaller finished but there is no dist\muezzin.exe" }

# 2. WinSW: rename first, because the wrapper decides which service it manages
#    by its own file name — muezzin-service.exe + muezzin-service.xml.
$winswExe = Join-Path $here "winsw\WinSW-x64.exe"
if (-not (Test-Path $winswExe)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $winswExe) | Out-Null
    $url = "https://github.com/winsw/winsw/releases/latest/download/WinSW-x64.exe"
    Write-Host "fetching WinSW from $url"
    try {
        Invoke-WebRequest -Uri $url -OutFile $winswExe -UseBasicParsing
    } catch {
        throw "could not fetch WinSW. Download WinSW-x64.exe from https://github.com/winsw/winsw/releases and put it at $winswExe, then run this again."
    }
}

# 3. Assemble. One folder with the four things that make the service, and the
#    version in its name so a tester cannot install yesterday's build by
#    accident.
$out = Join-Path $dist "muezzin-service-$version"
New-Item -ItemType Directory -Force -Path $out | Out-Null
Copy-Item $exe (Join-Path $out "muezzin.exe") -Force
Copy-Item $winswExe (Join-Path $out "muezzin-service.exe") -Force
Copy-Item (Join-Path $here "muezzin-service.xml") (Join-Path $out "muezzin-service.xml") -Force
Copy-Item (Join-Path $here "install.ps1"), (Join-Path $here "uninstall.ps1") $out -Force

Write-Host ""
Write-Host "assembled: $out" -ForegroundColor Green
Write-Host "next: cd there, then .\install.ps1 (elevated)"
