# Builds muezzin-setup.exe: the frozen exe, the service wrapper, and the
# installer around them, all under the version in pyproject.toml. Run from
# this directory. What it needs:
#
#   pip install -e ..\.. ; pip install pyinstaller     # once, in a venv
#   Inno Setup 6                                       # winget install --id JRSoftware.InnoSetup
#
# The output is one file in dist\. The assembled scaffolding folder (the
# install.ps1 route testers used before the installer existed) is built
# alongside it, because that route is still how the mechanism gets poked at.

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Join-Path $here "..\.."

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

# 2. WinSW. Pinned, not "latest": a release build that silently picks up a new
#   wrapper is a UAT result about something nobody tested. And the fetch is
#   pinned-tag first, because this repo's experience is that the
#   "releases/latest/download" URL answers 404 for WinSW — that is what made
#   the very first build here fail, and it read like a network refusal until
#   the same machine fetched a tagged URL in three seconds.
$winswExe = Join-Path $here "winsw\WinSW-x64.exe"
if (-not (Test-Path $winswExe)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $winswExe) | Out-Null
    $urls = @(
        "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe",
        "https://github.com/winsw/winsw/releases/latest/download/WinSW-x64.exe"
    )
    $got = $false
    foreach ($url in $urls) {
        try { Invoke-WebRequest -Uri $url -OutFile $winswExe -UseBasicParsing; $got = $true; break } catch { }
    }
    if (-not $got) {
        throw "could not fetch WinSW. Download WinSW-x64.exe from https://github.com/winsw/winsw/releases and put it at $winswExe, then run this again."
    }
}

# 3. The scaffolding folder: the install.ps1 route, still useful for a tester
#    who wants to see the four moving parts separately.
$out = Join-Path $here "dist\muezzin-service\muezzin-service-$version"
New-Item -ItemType Directory -Force -Path $out | Out-Null
Copy-Item $exe (Join-Path $out "muezzin.exe") -Force
Copy-Item $winswExe (Join-Path $out "muezzin-service.exe") -Force
Copy-Item (Join-Path $here "muezzin-service.xml") (Join-Path $out "muezzin-service.xml") -Force
Copy-Item (Join-Path $here "install.ps1"), (Join-Path $here "uninstall.ps1") $out -Force

# 4. The installer: a stage folder with exactly what the .iss asks for under
#    stable names, then Inno's compiler. The stage is a build leftover, which
#    is why .gitignore already covers it; keeping the wrapper under its own
#    name there and letting the .iss rename it to muezzin-service.exe at
#    install time means the renaming is written down in one place, not two.
$stage = Join-Path $here "stage"
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item $exe (Join-Path $stage "muezzin.exe") -Force
Copy-Item $winswExe (Join-Path $stage "WinSW-x64.exe") -Force
Copy-Item (Join-Path $here "muezzin-service.xml") (Join-Path $stage "muezzin-service.xml") -Force

$iscc = $null
foreach ($p in @(
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)) { if (Test-Path $p) { $iscc = $p; break } }
if (-not $iscc) { $iscc = "iscc" }

# ISCC, like pyinstaller, writes its progress to stderr: same guard as above.
$ErrorActionPreference = "Continue"
& $iscc "/DVersion=$version" "/DStageDir=$stage" (Join-Path $here "muezzin-setup.iss")
$code = $LASTEXITCODE
$ErrorActionPreference = $prevPreference
if ($code -ne 0) { throw "iscc failed (exit $code)" }

Write-Host ""
Write-Host "installer: $(Join-Path $here "dist\muezzin-$version-setup.exe")" -ForegroundColor Green
Write-Host "scaffolding (the install.ps1 route): $out"
