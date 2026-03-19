param(
    [string]$EntryScript = "Downloader.py",
    [string]$RequirementsFile = "requirements.txt",
    [string]$OutputName = "Downloader",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "== Build Windows EXE =="
Write-Host "Script dir: $scriptDir"

if (-not (Test-Path -LiteralPath $RequirementsFile)) {
    Write-Host "requirements file not found: $RequirementsFile" -ForegroundColor Yellow
    Write-Host "Create it first or edit this script to point at the correct file." -ForegroundColor Yellow
    exit 1
}

Write-Host "Installing requirements from $RequirementsFile..."
python -m pip install --upgrade pip
python -m pip install -r $RequirementsFile

# If Playwright is part of the requirements, ensure the bundled browser is installed.
$hasPlaywright = $false
try {
    $reqLines = Get-Content -LiteralPath $RequirementsFile
    foreach ($l in $reqLines) {
        $line = $l.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { continue }
        if ($line -match "^(playwright)(\s|$|[=<>!~])") {
            $hasPlaywright = $true
            break
        }
    }
} catch {
    $hasPlaywright = $false
}

if ($hasPlaywright) {
    Write-Host "Installing Playwright browser (chromium)..."
    try {
        python -m playwright install chromium
    } catch {
        Write-Host "Warning: Playwright browser install failed. You may need to run: python -m playwright install chromium" -ForegroundColor Yellow
    }
}

$playwrightBrowsersPath = $null
try {
    if ($env:LOCALAPPDATA) {
        $playwrightBrowsersPath = Join-Path $env:LOCALAPPDATA "ms-playwright"
    }
} catch {
    $playwrightBrowsersPath = $null
}

$collectAllArgs = @()

# Build-time-only deps we should not bundle into the runtime EXE.
# Keeping these out avoids unnecessary bloat and prevents PyInstaller from
# importing unrelated modules during hook processing.
$skipCollectAllPkgs = @(
    "pyinstaller"
)

# Read requirement package names and apply --collect-all for each.
# This helps PyInstaller bundle submodules and package data.
Get-Content -LiteralPath $RequirementsFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    if ($line.StartsWith("-r") -or $line.StartsWith("--")) { return }

    # Extract the package name before version/operator/extras.
    # Examples:
    #   playwright==1.40.0  -> playwright
    #   pillow>=10          -> pillow
    #   requests[socks]    -> requests
    if ($line -match "^([A-Za-z0-9_.-]+)") {
        $pkg = $matches[1]
        if ($pkg) {
            if ($skipCollectAllPkgs -contains $pkg.ToLower()) {
                return
            }
            $collectAllArgs += "--collect-all"
            $collectAllArgs += $pkg
        }
    }
}

$distDir = Join-Path $scriptDir "dist"

$pyinstallerArgs = @(
    "--noconfirm"
    "--onefile"
    "--windowed"
    "--name"
    $OutputName
)

if ($Clean) {
    # Avoid PyInstaller's default cleanup of its cached work directory,
    # which can fail with "Access is denied" when some files are locked.
    # Using an isolated work path gives a reliable "clean build" effect.
    $isolatedWorkPath = Join-Path $env:TEMP ("pyinstaller_work_" + [Guid]::NewGuid().ToString())
    Write-Host "Using isolated PyInstaller work dir: $isolatedWorkPath"
    $pyinstallerArgs += @("--workpath", $isolatedWorkPath)
}

# Bundle Playwright browsers so the EXE works without requiring `playwright install` on the target machine.
# Playwright uses the PLAYWRIGHT_BROWSERS_PATH env var when present.
if ($playwrightBrowsersPath -and (Test-Path -LiteralPath $playwrightBrowsersPath)) {
    Write-Host "Bundling Playwright browsers from: $playwrightBrowsersPath"
    $pyinstallerArgs += @("--add-data", "$playwrightBrowsersPath;playwright-browsers")
} else {
    Write-Host "Playwright browsers folder not found; EXE may require running `python -m playwright install chromium` on the target machine." -ForegroundColor Yellow
}

# Make sure we build from the entry script name.
$pyinstallerArgs += $collectAllArgs
$pyinstallerArgs += $EntryScript

Write-Host "Running PyInstaller..."
Write-Host "pyinstaller $($pyinstallerArgs -join ' ')"

# Use python -m pyinstaller to avoid PATH issues.
python -m PyInstaller @pyinstallerArgs

Write-Host ""
Write-Host "Build finished."
if (Test-Path -LiteralPath $distDir) {
    Write-Host "Output should be under: $distDir" -ForegroundColor Green
}

