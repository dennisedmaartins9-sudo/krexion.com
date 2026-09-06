# ════════════════════════════════════════════════════════════════════════
# Krexion — One-Click Local Windows Build Script
# ════════════════════════════════════════════════════════════════════════
# Run this ON YOUR WINDOWS MACHINE (VPS or local PC) to build the full
# Krexion-Setup.exe without ANY GitHub Actions involvement.
#
# What it does:
#   1. Downloads Python 3.11 embeddable distribution
#   2. pip-installs all backend requirements (filters Linux-only deps)
#   3. Compiles backend .py → .pyc and DELETES the source
#   4. Downloads MongoDB Portable + NSSM
#   5. Builds the React frontend (requires Node.js installed)
#   6. Installs Inno Setup if missing
#   7. Compiles Krexion-Setup.exe
#   8. Outputs to: installer\Output\Krexion-Setup-1.0.0.exe
#
# Prerequisites on the Windows machine:
#   • Python 3.11 installed   (https://www.python.org/downloads/)
#   • Node.js 20+ installed   (https://nodejs.org/)
#   • Yarn installed          (npm install -g yarn)
#   • PowerShell 5.1+         (default on Windows 10/11)
#   • Internet connection
#   • Admin rights (for Inno Setup auto-install)
#
# Usage:
#     1. Open PowerShell as Administrator
#     2. cd C:\path\to\krexion-repo
#     3. Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#     4. .\Build-Krexion-Windows.ps1
#     5. ~20-30 minutes later → installer\Output\Krexion-Setup-1.0.0.exe ready!
# ════════════════════════════════════════════════════════════════════════

[CmdletBinding()]
param(
    [string]$Version = "1.0.0",
    [switch]$SkipFrontend,
    [switch]$SkipChromium,
    [switch]$SkipInnoSetup
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ── Pretty output ─────────────────────────────────────────────────────
function Step($n, $total, $msg)  { Write-Host ""; Write-Host "[$n/$total] $msg" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Info($m) { Write-Host "  [..]   $m" -ForegroundColor Gray }
function Die($m)  { Write-Host "  [ERR]  $m" -ForegroundColor Red; exit 1 }

# ── Paths ─────────────────────────────────────────────────────────────
$RepoRoot = Get-Location
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$BuildDir = Join-Path $RepoRoot "build"
$DistDir = Join-Path $BuildDir "dist"
$TargetDir = Join-Path $DistDir "krexion-backend.dist"
$InstallerDir = Join-Path $RepoRoot "installer"
$InstallerOut = Join-Path $InstallerDir "Output"

# Banner
Clear-Host
Write-Host ""
Write-Host "  KREXION WINDOWS BUILD — Local one-click compilation" -ForegroundColor Magenta
Write-Host "  Version: $Version" -ForegroundColor Gray
Write-Host "  Repo:    $RepoRoot" -ForegroundColor Gray
Write-Host ""

# ── Prerequisite check ───────────────────────────────────────────────
Step 0 9 "Prerequisite check"
$pythonExe = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonExe) { Die "Python not found. Install Python 3.11 from python.org" }
Info "Python:  $((python --version) -replace 'Python ','')"

if (-not $SkipFrontend) {
    $nodeExe = Get-Command node -ErrorAction SilentlyContinue
    if (-not $nodeExe) { Die "Node.js not found. Install Node.js 20+ from nodejs.org" }
    Info "Node:    $(node --version)"
    $yarnExe = Get-Command yarn -ErrorAction SilentlyContinue
    if (-not $yarnExe) { Die "Yarn not found. Run: npm install -g yarn" }
    Info "Yarn:    $(yarn --version)"
}
Ok "All prerequisites present"

# ── Step 1: Run the embedded-Python backend build ────────────────────
Step 1 9 "Building backend bundle (embedded Python + pyc compile)"
$buildScript = Join-Path $BuildDir "build-backend.py"
if (-not (Test-Path $buildScript)) { Die "build/build-backend.py missing — pull latest from main branch" }
python $buildScript
if ($LASTEXITCODE -ne 0) { Die "Backend build failed (see output above)" }
if (-not (Test-Path $TargetDir)) { Die "Expected output $TargetDir not produced" }
Ok "Backend bundle ready"

# ── Step 2: Download MongoDB Portable ────────────────────────────────
Step 2 9 "Downloading MongoDB Portable"
$mongoPortable = Join-Path $BuildDir "mongo-portable"
if (-not (Test-Path "$mongoPortable\bin\mongod.exe")) {
    $mongoUrl = "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-7.0.14.zip"
    $mongoZip = Join-Path $BuildDir "mongo.zip"
    Info "Downloading MongoDB 7.0.14..."
    Invoke-WebRequest -Uri $mongoUrl -OutFile $mongoZip -UseBasicParsing
    $extract = Join-Path $BuildDir "mongo-extract"
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    Expand-Archive -Path $mongoZip -DestinationPath $extract -Force
    $src = Get-ChildItem $extract -Filter "mongodb-*" -Directory | Select-Object -First 1
    if ($src) {
        New-Item -ItemType Directory -Force -Path $mongoPortable | Out-Null
        Copy-Item -Path "$($src.FullName)\*" -Destination $mongoPortable -Recurse -Force
    }
    Remove-Item $mongoZip, $extract -Recurse -Force -ErrorAction SilentlyContinue
}
Ok "MongoDB Portable: $mongoPortable"

# ── Step 3: Download NSSM ────────────────────────────────────────────
Step 3 9 "Downloading NSSM (service wrapper)"
$nssmPortable = Join-Path $BuildDir "nssm-portable"
if (-not (Test-Path "$nssmPortable\nssm.exe")) {
    $nssmZip = Join-Path $BuildDir "nssm.zip"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $nssmZip -UseBasicParsing
    $extract = Join-Path $BuildDir "nssm-extract"
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    Expand-Archive -Path $nssmZip -DestinationPath $extract -Force
    New-Item -ItemType Directory -Force -Path $nssmPortable | Out-Null
    Copy-Item -Path "$extract\nssm-2.24\win64\nssm.exe" -Destination "$nssmPortable\nssm.exe" -Force
    Remove-Item $nssmZip, $extract -Recurse -Force -ErrorAction SilentlyContinue
}
Ok "NSSM: $nssmPortable\nssm.exe"

# ── Step 4: Download Playwright Chromium + WebKit ───────────────────
Step 4 9 "Downloading Playwright Chromium + WebKit (Android + iOS engines)"
if (-not $SkipChromium) {
    $chromiumBundle = Join-Path $BuildDir "chromium-bundle"
    $needChromium = -not (Test-Path "$chromiumBundle\chromium-*\chrome-win\chrome.exe")
    $needWebkit = -not (Test-Path "$chromiumBundle\webkit-*")
    if ($needChromium -or $needWebkit) {
        $env:PLAYWRIGHT_BROWSERS_PATH = $chromiumBundle
        # The build-backend already pip-installed playwright into the embedded
        # python. We need to run `playwright install` from THAT install.
        $embedPython = Join-Path $TargetDir "python.exe"
        $browsers = @()
        if ($needChromium) { $browsers += @("chromium", "chromium-headless-shell") }
        if ($needWebkit) { $browsers += "webkit" }
        if ($browsers.Count -eq 0) { $browsers = @("chromium", "chromium-headless-shell", "webkit") }
        Info ("Installing Playwright browsers: " + ($browsers -join ", "))
        if (Test-Path $embedPython) {
            & $embedPython -m playwright install @browsers
        }
        else {
            python -m playwright install @browsers
        }
    }
    Ok "Browser-engine bundle (Chromium + WebKit): $chromiumBundle"

# ── Step 4b: Bundle Cloak C++ Krexion Kernel (AdsPower-class) ─────────────
Step "4b" 9 "Bundling Cloak C++ Krexion Kernel (AdsPower-class headed profiles)"
$kernelDest = Join-Path $BuildDir "krexion-kernel"
New-Item -ItemType Directory -Force -Path $kernelDest | Out-Null
$embedPython = Join-Path $TargetDir "python.exe"
if (-not (Test-Path $embedPython)) { $embedPython = "python" }
& $embedPython -m pip install -q "cloakbrowser>=0.5.0"
& $embedPython (Join-Path $PSScriptRoot "backend/scripts/bundle_krexion_kernel.py") --dest $kernelDest --platform windows-x64
if ($LASTEXITCODE -ne 0) { Die "Krexion Kernel (Cloak C++) bundle failed" }
if (-not (Test-Path (Join-Path $kernelDest "chrome.exe"))) { Die "krexion-kernel/chrome.exe missing" }
Ok "Krexion Kernel: $kernelDest"

}
else {
    Warn "Skipped Chromium/WebKit download (per -SkipChromium)"
}

# ── Step 5: Build React frontend ─────────────────────────────────────
Step 5 9 "Building React frontend"
if (-not $SkipFrontend) {
    $frontendBuild = Join-Path $BuildDir "frontend-build"
    Push-Location $FrontendDir
    try {
        "REACT_APP_BACKEND_URL=http://127.0.0.1:8001" | Out-File -FilePath ".env.production" -Encoding ASCII
        Info "Running yarn install..."
        yarn install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { Die "yarn install failed" }
        Info "Running yarn build..."
        yarn build
        if ($LASTEXITCODE -ne 0) { Die "yarn build failed" }
        if (Test-Path $frontendBuild) { Remove-Item $frontendBuild -Recurse -Force }
        Copy-Item -Path (Join-Path $FrontendDir "build") -Destination $frontendBuild -Recurse -Force
    }
    finally {
        Pop-Location
    }
    Ok "Frontend bundle: $frontendBuild"
}
else {
    Warn "Skipped frontend build (per -SkipFrontend)"
}

# ── Step 6: Ensure Inno Setup is installed ───────────────────────────
Step 6 9 "Checking Inno Setup"
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    if (-not $SkipInnoSetup) {
        Info "Inno Setup not found. Installing via Chocolatey..."
        $choco = Get-Command choco -ErrorAction SilentlyContinue
        if (-not $choco) {
            Info "Installing Chocolatey first..."
            Set-ExecutionPolicy Bypass -Scope Process -Force
            Invoke-Expression ((New-Object Net.WebClient).DownloadString("https://chocolatey.org/install.ps1"))
        }
        choco install innosetup -y --no-progress
    }
    if (-not (Test-Path $iscc)) {
        Die "Inno Setup install failed. Install manually from https://jrsoftware.org/isinfo.php"
    }
}
Ok "Inno Setup: $iscc"

# ── Step 7: Compile Krexion-Setup.exe ────────────────────────────────
Step 7 9 "Compiling Krexion-Setup.exe with Inno Setup"
$issFile = Join-Path $InstallerDir "krexion-setup.iss"
if (-not (Test-Path $issFile)) { Die "installer/krexion-setup.iss missing" }
New-Item -ItemType Directory -Force -Path $InstallerOut | Out-Null
& $iscc /Qp $issFile "/DAppVersion=$Version"
if ($LASTEXITCODE -ne 0) { Die "Inno Setup compilation failed" }
$setupExe = Get-ChildItem $InstallerOut -Filter "Krexion-Setup-*.exe" | Select-Object -First 1
if (-not $setupExe) { Die "Krexion-Setup-*.exe not produced" }
Ok "Installer: $($setupExe.FullName)"

# ── Step 8: Summary ──────────────────────────────────────────────────
Step 8 9 "Build summary"
$sizeMB = [math]::Round($setupExe.Length / 1MB, 1)
Info "File:    $($setupExe.Name)"
Info "Size:    $sizeMB MB"
Info "Path:    $($setupExe.FullName)"

# ── Step 9: Optional — open output folder ────────────────────────────
Step 9 9 "Done!"
Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host "  KREXION-SETUP.EXE READY FOR CUSTOMER" -ForegroundColor Green
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host ""
Write-Host "  Send this file to customers:" -ForegroundColor White
Write-Host "    $($setupExe.FullName)" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Or upload to your GitHub Releases manually:" -ForegroundColor White
Write-Host "    1. Go to https://github.com/dennisedmaartins9-sudo/krexion.com/releases" -ForegroundColor Gray
Write-Host "    2. Click 'Draft a new release'" -ForegroundColor Gray
Write-Host "    3. Tag: v$Version  | Title: Krexion v$Version" -ForegroundColor Gray
Write-Host "    4. Drag $($setupExe.Name) into the 'Attach binaries' box" -ForegroundColor Gray
Write-Host "    5. Click 'Publish release'" -ForegroundColor Gray
Write-Host ""

# Open the folder for the user
Start-Process explorer.exe -ArgumentList $InstallerOut
