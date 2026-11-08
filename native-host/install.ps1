<#
.SYNOPSIS
  Register the scholar-search native messaging host for Edge and Chrome.
.DESCRIPTION
  Builds the launcher executable, writes the native messaging manifest, and
  registers the per-user key under HKCU. No elevation required.
  Use -Uninstall to remove the registration.
#>
param(
  [string]$ExtensionId = "gmaimbocfjkolcpljeekjcomakipoaph",
  [string]$Python,
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$hostName = "com.scholar.search"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = Split-Path -Parent $here

if (-not $Python) {
  $venvPython = Join-Path $project ".venv\Scripts\python.exe"
  if (Test-Path $venvPython) {
    $Python = $venvPython
  } else {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if (-not $command) {
      $command = Get-Command python3 -ErrorAction SilentlyContinue
    }
    if ($command) { $Python = $command.Source }
  }
}

$manifestPath = Join-Path $here "$hostName.json"
$launcher = Join-Path $here "scholar-host.exe"
$pythonPathFile = Join-Path $here "python-path.txt"

if ($Uninstall) {
  foreach ($browser in @("Microsoft\Edge", "Google\Chrome")) {
    $key = "HKCU:\Software\$browser\NativeMessagingHosts\$hostName"
    if (Test-Path $key) { Remove-Item $key -Recurse -Force }
  }
  Remove-Item $manifestPath, $launcher, $pythonPathFile -Force -ErrorAction SilentlyContinue
  Write-Host "removed $hostName"
  exit 0
}

if (-not (Test-Path $Python)) {
  throw "python not found: $Python (pass -Python <path>)"
}

$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $launcher)) {
  if (-not (Test-Path $csc)) {
    throw "csc.exe not found; cannot build $launcher"
  }
  & $csc /nologo /target:exe /out:$launcher (Join-Path $here "launcher.cs") | Out-Null
}
Set-Content -Path $pythonPathFile -Value $Python -Encoding ascii

# The browser launches the host at low integrity. Keep the runtime tree inside
# the documented HOME boundary and label it so that host can still write.
$runtimeHome = if ($env:SCHOLAR_SEARCH_HOME) {
  $env:SCHOLAR_SEARCH_HOME
} else {
  Join-Path $env:LOCALAPPDATA "scholar-search"
}
Set-Content -Path (Join-Path $here "runtime-home.txt") -Value $runtimeHome -Encoding ascii
$runtime = Join-Path $runtimeHome "host"
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
try {
  & icacls $runtime /setintegritylevel "(OI)(CI)L" | Out-Null
} catch {
  Write-Warning "could not lower integrity on $runtime; the host may not be able to write there"
}

$manifest = @{
  name            = $hostName
  description     = "scholar-search native bridge"
  path            = ($launcher -replace "\\", "/")
  type            = "stdio"
  allowed_origins = @("chrome-extension://$ExtensionId/")
} | ConvertTo-Json -Compress

# Written without a BOM on purpose: Chrome parses the native-messaging manifest as
# JSON, and `-Encoding utf8` on Windows PowerShell 5.1 prepends one, which makes the
# host register but never launch. UTF8Encoding($false) is BOM-free on both 5.1 and 7.
[System.IO.File]::WriteAllText($manifestPath, $manifest, (New-Object System.Text.UTF8Encoding($false)))

foreach ($browser in @("Microsoft\Edge", "Google\Chrome")) {
  $key = "HKCU:\Software\$browser\NativeMessagingHosts\$hostName"
  New-Item -Path $key -Force | Out-Null
  Set-ItemProperty -Path $key -Name "(Default)" -Value $manifestPath
}

Write-Host "registered $hostName"
Write-Host "  manifest : $manifestPath"
Write-Host "  launcher : $launcher"
Write-Host "  ext id   : $ExtensionId"


