param(
    [string]$Dir = ""
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$PyScript = Join-Path $PSScriptRoot 'stamp-frontend-build.py'

function Invoke-KrexionStamp {
    param(
        [string[]]$ScriptArgs
    )

    $attempts = @(
        @{ Exe = 'py'; Prefix = @('-3') },
        @{ Exe = 'python3'; Prefix = @() },
        @{ Exe = 'python'; Prefix = @() }
    )

    foreach ($attempt in $attempts) {
        $exe = $attempt.Exe
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
            continue
        }
        $argv = @()
        if ($attempt.Prefix.Count -gt 0) {
            $argv += $attempt.Prefix
        }
        $argv += $PyScript
        if ($ScriptArgs.Count -gt 0) {
            $argv += $ScriptArgs
        }
        & $exe @argv
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
    }

    return $false
}

Push-Location $Root
try {
    if ($Dir) {
        if (-not (Test-Path $Dir)) {
            throw "Frontend build directory not found: $Dir"
        }
        if (-not (Invoke-KrexionStamp @('--dir', $Dir))) {
            throw "Could not stamp frontend build at $Dir"
        }
        Write-Host "Stamped frontend build at $Dir"
        exit 0
    }

    if (-not (Test-Path 'frontend/build/index.html')) {
        Write-Host 'No frontend/build/index.html - skip stamp (fallback rebuild may run)'
        exit 0
    }

    if (-not (Invoke-KrexionStamp @())) {
        throw 'Could not stamp frontend/build artifact'
    }
    Write-Host 'Stamped frontend/build for native installer'
}
finally {
    Pop-Location
}
