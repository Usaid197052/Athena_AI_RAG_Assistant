# Remove Athena from Windows Startup.
$ErrorActionPreference = "Stop"
$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "Athena.lnk"

if (Test-Path $ShortcutPath) {
    Remove-Item $ShortcutPath -Force
    Write-Host "Removed $ShortcutPath"
} else {
    Write-Host "No Athena startup shortcut found."
}
