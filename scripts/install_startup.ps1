# Install Athena to start with Windows (current user Startup folder).
#   powershell -ExecutionPolicy Bypass -File scripts\install_startup.ps1

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "Athena.lnk"

$DistExe = Join-Path $ProjectRoot "dist\Athena\Athena.exe"
$Pythonw = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (Test-Path $DistExe) {
    $Target = $DistExe
    $TargetArgs = ""
    $WorkingDir = Split-Path -Parent $DistExe
} elseif (Test-Path $Pythonw) {
    $Target = $Pythonw
    $TargetArgs = "`"$ProjectRoot\app.py`""
    $WorkingDir = $ProjectRoot
} elseif (Test-Path $Python) {
    $Target = $Python
    $TargetArgs = "`"$ProjectRoot\app.py`""
    $WorkingDir = $ProjectRoot
} else {
    $Target = (Get-Command py -ErrorAction SilentlyContinue).Source
    if (-not $Target) { throw "Python / Athena.exe not found. Build or create .venv first." }
    $TargetArgs = "`"$ProjectRoot\app.py`""
    $WorkingDir = $ProjectRoot
}

$Wsh = New-Object -ComObject WScript.Shell
$Shortcut = $Wsh.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Target
$Shortcut.Arguments = $TargetArgs
$Shortcut.WorkingDirectory = $WorkingDir
$Shortcut.WindowStyle = 7
$Shortcut.Description = "Athena local AI assistant tray"
$Shortcut.Save()

Write-Host "Installed Athena startup shortcut:"
Write-Host "  $ShortcutPath"
Write-Host "Launch target:"
Write-Host "  $Target $TargetArgs"
