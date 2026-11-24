# Installs the PoC service. Run from the assembled folder (the one build.ps1
# printed), elevated:
#
#   .\install.ps1
#   .\install.ps1 -ConfigSource C:\path\muezzin.yaml -MediaSource C:\path\media
#
# The rule this script obeys, the same one the container's entrypoint obeys:
# %ProgramData%\muezzin\muezzin.yaml is either absent or yours, never
# half-written over. With no config present and none given, the service writes
# its own starter on first start and says so in the log — the container trick,
# unchanged.

#Requires -RunAsAdministrator

param(
    [string]$ConfigSource = "",
    [string]$MediaSource = "",
    [switch]$Force   # replace an existing profile, instead of leaving it alone
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$data = Join-Path $env:ProgramData "muezzin"
$installDir = Join-Path ${env:ProgramFiles} "muezzin"
$svcExe = Join-Path $installDir "muezzin-service.exe"
$appExe = Join-Path $installDir "muezzin.exe"

New-Item -ItemType Directory -Force -Path $data, (Join-Path $data "media") | Out-Null

# --- the profile, without ever overwriting one --------------------------------
$configPath = Join-Path $data "muezzin.yaml"
if ($ConfigSource) {
    if (-not (Test-Path $ConfigSource)) { throw "no profile at -ConfigSource: $ConfigSource" }
    if ((Test-Path $configPath) -and -not $Force) {
        Write-Warning "leaving the existing $configPath alone; delete it by hand if you really mean to replace it"
    } else {
        Copy-Item $ConfigSource $configPath
        Write-Host "profile installed at $configPath"
    }
} elseif (-not (Test-Path $configPath)) {
    Write-Host "no profile yet: the service will write a starter on first start, then finish setup on the page"
}

# --- the audio: never overwrite, the same rule the page's upload box keeps ----
if ($MediaSource) {
    if (-not (Test-Path $MediaSource)) { throw "no folder at -MediaSource: $MediaSource" }
    Get-ChildItem $MediaSource -File | ForEach-Object {
        $dest = Join-Path (Join-Path $data "media") $_.Name
        if (Test-Path $dest) { Write-Host "keeping existing $($_.Name)" }
        else { Copy-Item $_.FullName $dest }
    }
}

# --- the payload: exe + wrapper + xml, one folder, disposable -----------------
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Copy-Item (Join-Path $here "muezzin.exe")        $appExe         -Force
Copy-Item (Join-Path $here "muezzin-service.exe") $svcExe        -Force
Copy-Item (Join-Path $here "muezzin-service.xml") (Join-Path $installDir "muezzin-service.xml") -Force

# --- the service ---------------------------------------------------------------
& $svcExe install
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 1) { throw "winsw install failed ($LASTEXITCODE)" }
& $svcExe start

# --- the firewall: two rules, keyed to the app exe's path ----------------------
# The page and the media server listen on 0.0.0.0 (README, "Ports"), so the
# rules say who may reach them: the local subnet, on any profile. The profile
# boundary was tried first and failed on a real household machine where Windows
# had filed both adapters as Public — the speakers were found, added and handed
# a URL they could not fetch. 8020 is the page, 8010 the clip a Cast device
# pulls; both are needed from a phone on the wifi, which is the whole point of
# the setup flow. Delete-and-add rather than "skip if it exists", so an upgrade
# to different wording is not silently kept on the old rule.
foreach ($spec in @(
    @{ name = "muezzin panel"; port = 8020 },
    @{ name = "muezzin media"; port = 8010 }
)) {
    Remove-NetFirewallRule -DisplayName $spec.name -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $spec.name -Direction Inbound -Action Allow `
        -Program $appExe -Protocol TCP -LocalPort $spec.port `
        -Profile Any -RemoteAddress LocalSubnet | Out-Null
    Write-Host "firewall: $($spec.name) on :$($spec.port) (local subnet, any profile)"
}

# --- tell the tester what to dial, in the same words the container log uses ---
$lan = (Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and
                       $_.PrefixOrigin -ne "WellKnown" } |
        Select-Object -First 1).IPAddress
Write-Host ""
Write-Host "service installed. The page answers at http://${lan}:8020 from anything on this network." -ForegroundColor Green
Write-Host "the log lives in this folder (out.log / err.log), rolled by size."
