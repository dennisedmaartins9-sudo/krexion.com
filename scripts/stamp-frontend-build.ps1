param(
    [string]$Dir = ""
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$PyScript = Join-Path $PSScriptRoot 'stamp-frontend-build.py'

function Get-ExpectedVersion {
    $versionFile = Join-Path $Root 'backend/VERSION'
    if (-not (Test-Path $versionFile)) {
        throw "Missing backend/VERSION"
    }
    return (Get-Content $versionFile -Raw).Trim().TrimStart('v', 'V')
}

function Test-AlreadyStamped {
    param(
        [string]$BuildDir
    )

    $stampFile = Join-Path $BuildDir 'build-version.json'
    if (-not (Test-Path $stampFile)) {
        return $false
    }

    try {
        $expected = Get-ExpectedVersion
        $data = Get-Content $stampFile -Raw | ConvertFrom-Json
        $got = ([string]$data.version).Trim().TrimStart('v', 'V')
        return ($got -eq $expected)
    } catch {
        return $false
    }
}

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
        Write-Host "Running: $exe $($argv -join ' ')"
        & $exe @argv
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
        Write-Host "Stamp attempt via $exe failed with exit $LASTEXITCODE"
    }

    return $false
}

Push-Location $Root
try {
    if ($Dir) {
        if ([System.IO.Path]::IsPathRooted($Dir)) {
            $buildDir = $Dir
        } else {
            $buildDir = Join-Path $Root $Dir
        }
        if (-not (Test-Path $buildDir)) {
            throw "Frontend build directory not found: $buildDir"
        }
        $buildDir = (Get-Item -LiteralPath $buildDir).FullName
    } else {
        $buildDir = Join-Path $Root 'frontend/build'
    }

    if (-not (Test-Path (Join-Path $buildDir 'index.html'))) {
        if ($Dir) {
            throw "Missing index.html in $buildDir"
        }
        Write-Host 'No frontend/build/index.html - skip stamp (fallback rebuild may run)'
        exit 0
    }

    if (Test-AlreadyStamped $buildDir) {
        Write-Host "Frontend build already stamped for v$(Get-ExpectedVersion) at $buildDir"
        exit 0
    }

    $args = @()
    if ($Dir) {
        $args = @('--dir', $buildDir)
    }

    if (-not (Invoke-KrexionStamp $args)) {
        throw "Could not stamp frontend build at $buildDir"
    }

    if (-not (Test-AlreadyStamped $buildDir)) {
        throw "Stamp script ran but build-version.json is still missing or mismatched"
    }

    Write-Host "Stamped frontend build at $buildDir"
}
finally {
    Pop-Location
}
