param(
    [string]$EntryScript = "Downloader.py",
    [string]$OutputName = "SnapMem",
    [string]$Version = "",
    [switch]$NoBrowser,
    [switch]$SkipInstall
)

# Builds dist\<OutputName>.exe with `flet pack` (PyInstaller, one file, no console).
#   -Version 1.2.3   writes sc_memories_downloader\_version.py and the EXE file version
#   -NoBrowser       skips bundling Playwright Chromium (sign-in then needs Edge or a local install)
#   -SkipInstall     uses the packages already installed in the current Python

# flet and PyInstaller log to stderr; failures are caught through $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "== Build SnapMem EXE =="

if (-not $SkipInstall) {
    python -m pip install --upgrade pip
    python -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

$versionFile = Join-Path $scriptDir "sc_memories_downloader\_version.py"
if ($Version) {
    $clean = $Version.TrimStart("v")
    Set-Content -LiteralPath $versionFile -Value "__version__ = `"$clean`"" -Encoding utf8
} else {
    $clean = "0.0.0"
}
$parts = @($clean.Split(".") | ForEach-Object { if ($_ -match "^\d+$") { $_ } else { "0" } })
while ($parts.Count -lt 4) { $parts += "0" }
$fileVersion = ($parts[0..3] -join ".")

$packArgs = @(
    "pack", $EntryScript,
    "--name", $OutputName,
    "--icon", "assets\icons\app-icon.ico",
    "--add-data", "assets\svg:assets\svg",
    "--add-data", "assets\icons:assets\icons",
    "--product-name", "SnapMem",
    "--file-description", "SnapMem - Snapchat Memories downloader",
    "--product-version", $clean,
    "--file-version", $fileVersion,
    "--copyright", "SnapMem contributors",
    "-y"
)

if (-not $NoBrowser) {
    python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw "playwright install chromium failed" }
    $dry = python -m playwright install --dry-run chromium | Out-String
    $match = [regex]::Match($dry, "Install location:\s+(\S*[\\/]chromium-\d+)")
    if (-not $match.Success) { throw "Could not find the Playwright Chromium folder in: $dry" }
    $chromium = $match.Groups[1].Value
    $leaf = Split-Path -Leaf $chromium
    Write-Host "Bundling $chromium"
    $packArgs += @("--add-data", "${chromium}:playwright-browsers\$leaf")
}

Write-Host "flet $($packArgs -join ' ')"
flet @packArgs
if ($LASTEXITCODE -ne 0) { throw "flet pack failed" }

$exe = Join-Path $scriptDir "dist\$OutputName.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "Expected $exe" }

Write-Host "Running self-test..."
$report = Join-Path $scriptDir "dist\self-test.txt"
$proc = Start-Process -FilePath $exe -ArgumentList "--self-test", "--self-test-report", $report -Wait -PassThru
Get-Content -LiteralPath $report -ErrorAction SilentlyContinue
if ($proc.ExitCode -ne 0) { throw "Self-test failed (exit $($proc.ExitCode))" }

Write-Host "Built $exe" -ForegroundColor Green
