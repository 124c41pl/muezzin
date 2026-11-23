# Removes the service. It stops leaving what it was given to keep: the profile,
# the audio and the logs under %ProgramData%\muezzin stay exactly where they
# are, because those folders are the household's, not the installer's. Delete
# them by hand if you mean to; say so in the bug report if you did not mean to.

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"
$svcExe = Join-Path ${env:ProgramFiles} "muezzin\muezzin-service.exe"
if (-not (Test-Path $svcExe)) { throw "no service at $svcExe; nothing to remove" }

& $svcExe stop
# stop exits nonzero when the service was already stopped: that is success here.
& $svcExe uninstall
if ($LASTEXITCODE -ne 0) { throw "winsw uninstall failed ($LASTEXITCODE)" }

Get-NetFirewallRule -DisplayName "muezzin panel", "muezzin media" -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
Write-Host "service removed. Your profile and audio are still in $env:ProgramData\muezzin."
