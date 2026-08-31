# Sign Krexion native installer payloads + final Setup.exe (Smart App Control / SAC).
# Modes (first match wins):
#   1. KREXION_CODESIGN_PFX_PATH + KREXION_CODESIGN_PFX_PASSWORD
#   2. KREXION_CODESIGN_THUMBPRINT (cert in LocalMachine\My or CurrentUser\My)
#   3. AZURE_CODESIGN_DLIB + AZURE_CODESIGN_METADATA_JSON (Artifact Signing)
#
# See deployment/CODESIGN-SETUP.md for one-time credential setup.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Find-SignTool {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe",
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x86\signtool.exe",
        "${env:ProgramFiles(x86)}\Microsoft SDKs\ClickOnce\SignTool\signtool.exe"
    )
    foreach ($pattern in $candidates) {
        $hit = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "signtool.exe not found. Install Windows SDK (Signing Tools for Desktop Apps)."
}

function Test-ValidAuthenticode {
    param([string]$Path)
    try {
        $sig = Get-AuthenticodeSignature -LiteralPath $Path
        return ($sig.Status -eq 'Valid')
    } catch {
        return $false
    }
}

function Invoke-KrexionSignFile {
    param(
        [string]$SignTool,
        [string]$FilePath,
        [scriptblock]$SignCommand
    )
    if (-not (Test-Path -LiteralPath $FilePath)) { return }
    if (Test-ValidAuthenticode -Path $FilePath) {
        Write-Host "  [skip already signed] $FilePath"
        return
    }
    Write-Host "  [sign] $FilePath"
    & $SignCommand.Invoke($FilePath)
    if ($LASTEXITCODE -ne 0) {
        throw "signtool failed ($LASTEXITCODE) for $FilePath"
    }
    if (-not (Test-ValidAuthenticode -Path $FilePath)) {
        throw "Signature not valid after signing: $FilePath"
    }
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repoRoot

$signTool = Find-SignTool
Write-Host "Using signtool: $signTool"

$timestampUrl = if ($env:KREXION_CODESIGN_TIMESTAMP) { $env:KREXION_CODESIGN_TIMESTAMP } else { 'http://timestamp.digicert.com' }
$signMode = $null
$signBlock = $null

if ($env:KREXION_CODESIGN_PFX_PATH -and (Test-Path -LiteralPath $env:KREXION_CODESIGN_PFX_PATH)) {
    if (-not $env:KREXION_CODESIGN_PFX_PASSWORD) { throw 'KREXION_CODESIGN_PFX_PASSWORD is required with PFX path' }
    $pfx = $env:KREXION_CODESIGN_PFX_PATH
    $pass = $env:KREXION_CODESIGN_PFX_PASSWORD
    $signMode = 'pfx'
    $signBlock = {
        param($FilePath)
        & $signTool sign /fd SHA256 /td SHA256 /tr $timestampUrl /f $pfx /p $pass $FilePath
    }.GetNewClosure()
} elseif ($env:KREXION_CODESIGN_THUMBPRINT) {
    $thumb = $env:KREXION_CODESIGN_THUMBPRINT
    $signMode = 'thumbprint'
    $signBlock = {
        param($FilePath)
        & $signTool sign /fd SHA256 /td SHA256 /tr $timestampUrl /sha1 $thumb $FilePath
    }.GetNewClosure()
} elseif ($env:AZURE_CODESIGN_DLIB -and $env:AZURE_CODESIGN_METADATA_JSON) {
    if (-not (Test-Path -LiteralPath $env:AZURE_CODESIGN_DLIB)) {
        throw "AZURE_CODESIGN_DLIB not found: $($env:AZURE_CODESIGN_DLIB)"
    }
    $metaPath = Join-Path $env:TEMP 'krexion-azure-codesign-metadata.json'
    Set-Content -Path $metaPath -Value $env:AZURE_CODESIGN_METADATA_JSON -Encoding UTF8
    $dlib = $env:AZURE_CODESIGN_DLIB
    $azureTs = 'http://timestamp.acs.microsoft.com'
    $signMode = 'azure'
    $signBlock = {
        param($FilePath)
        & $signTool sign /v /debug /fd SHA256 /td SHA256 /tr $azureTs /dlib $dlib /dmdf $metaPath $FilePath
    }.GetNewClosure()
} else {
    throw @'
No code-signing credentials configured.
Add GitHub secrets (see deployment/CODESIGN-SETUP.md):
  • KREXION_CODESIGN_PFX_BASE64 + KREXION_CODESIGN_PFX_PASSWORD
    OR
  • KREXION_CODESIGN_THUMBPRINT (cert on self-hosted runner)
    OR
  • AZURE_CODESIGN_* for Azure Artifact Signing
'@
}

Write-Host "Signing mode: $signMode"

$bundleRoots = @(
    'build\dist\krexion-backend.dist',
    'build\mongo-portable',
    'build\nssm-portable',
    'build\chromium-bundle'
)

$signed = 0
foreach ($root in $bundleRoots) {
    if (-not (Test-Path $root)) {
        Write-Host "Bundle root missing (skip): $root"
        continue
    }
    Write-Host "=== Signing EXEs under $root ==="
    Get-ChildItem -Path $root -Recurse -File -Include *.exe -ErrorAction SilentlyContinue | ForEach-Object {
        Invoke-KrexionSignFile -SignTool $signTool -FilePath $_.FullName -SignCommand $signBlock
        $script:signed++
    }
}

Write-Host "Signed (or skipped-already-signed) $signed executable(s) under bundle roots."

if ($args.Count -gt 0) {
    foreach ($installer in $args) {
        if (-not (Test-Path -LiteralPath $installer)) {
            throw "Installer not found: $installer"
        }
        Write-Host "=== Signing installer: $installer ==="
        Invoke-KrexionSignFile -SignTool $signTool -FilePath (Resolve-Path $installer).Path -SignCommand $signBlock
    }
}

Write-Host "Code signing complete."
