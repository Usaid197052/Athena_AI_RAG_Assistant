# Build Athena onedir package with PyInstaller.
#   powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing .venv. Create it first."
}

& $Python -m pip install -q pyinstaller pillow pystray
& $Python (Join-Path $Root "scripts\make_icon.py")
& $Python -m PyInstaller (Join-Path $Root "Athena.spec") --noconfirm

$Dist = Join-Path $Root "dist\Athena"
if (-not (Test-Path (Join-Path $Dist "Athena.exe"))) {
    throw "Build failed: Athena.exe not found in dist\Athena"
}

$CopyMap = @{
    ".env.example" = ".env.example"
    "config\permissions.yaml" = "config\permissions.yaml"
    "README.md" = "README.md"
    "INSTRUCTIONS.txt" = "INSTRUCTIONS.txt"
    "LICENSE" = "LICENSE"
}

foreach ($src in $CopyMap.Keys) {
    $from = Join-Path $Root $src
    $to = Join-Path $Dist $CopyMap[$src]
    $toDir = Split-Path -Parent $to
    if (-not (Test-Path $toDir)) { New-Item -ItemType Directory -Force -Path $toDir | Out-Null }
    if (Test-Path $from) { Copy-Item $from $to -Force }
}

# Optional runtime assets
foreach ($dir in @("skills", "data\memory", "data\application_registry")) {
    $from = Join-Path $Root $dir
    $to = Join-Path $Dist $dir
    if (Test-Path $from) {
        if (-not (Test-Path $to)) { New-Item -ItemType Directory -Force -Path $to | Out-Null }
        Copy-Item (Join-Path $from "*") $to -Recurse -Force -ErrorAction SilentlyContinue
    }
}

foreach ($dir in @("data\cache", "data\logs", "data\sessions", "data\application_registry", "data\memory", "logs", "memory")) {
    $path = Join-Path $Dist $dir
    if (-not (Test-Path $path)) { New-Item -ItemType Directory -Force -Path $path | Out-Null }
}

# Prefer local .env for a runnable package; otherwise seed from example.
$distEnv = Join-Path $Dist ".env"
$rootEnv = Join-Path $Root ".env"
if (Test-Path $rootEnv) {
    Copy-Item $rootEnv $distEnv -Force
} elseif (-not (Test-Path $distEnv)) {
    $example = Join-Path $Dist ".env.example"
    if (Test-Path $example) { Copy-Item $example $distEnv }
}
Write-Host ""
Write-Host "Build complete:"
Write-Host "  $Dist\Athena.exe"
Write-Host "Start tray:       dist\Athena\Athena.exe"
Write-Host "Start voice:      dist\Athena\Athena.exe --voice"
Write-Host "Open dashboard:   dist\Athena\Athena.exe --dashboard"
Write-Host "Health:           dist\Athena\Athena.exe --health"
