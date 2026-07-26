param(
    [Parameter(Mandatory = $true)]
    [string]$ReplayPath,
    [Parameter(Mandatory = $true)]
    [string]$MoviePath,
    [string]$GameDir =
        "C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2"
)

$ErrorActionPreference = "Stop"
$exe = Join-Path $GameDir "SlayTheSpire2.exe"
if (-not (Test-Path $exe)) {
    throw "Game executable not found: $exe"
}
if (-not (Test-Path $ReplayPath)) {
    throw "Combat replay not found: $ReplayPath"
}

$movieDir = Split-Path -Parent $MoviePath
New-Item -ItemType Directory -Force -Path $movieDir | Out-Null

$env:STS2_REPLAY_PATH = $ReplayPath
Push-Location $GameDir
try {
    & $exe `
        --bootstrap `
        --write-movie $MoviePath `
        --fixed-fps 60 `
        --resolution 1280x720 `
        --windowed `
        --disable-vsync
    # Godot can clear LASTEXITCODE while exiting normally under Windows
    # PowerShell, so only treat an explicit non-zero value as failure.
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "Replay renderer exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
    Remove-Item Env:\STS2_REPLAY_PATH -ErrorAction SilentlyContinue
}
