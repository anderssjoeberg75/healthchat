$WScriptShell = New-Object -ComObject WScript.Shell
$DesktopPath = [System.Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path -Path $DesktopPath -ChildPath "HealthChat Desktop.lnk"
$Shortcut = $WScriptShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "pythonw.exe"
$Shortcut.Arguments = """D:\projekt\healthchat\healthchat\HealthChatDesktop.py"""
$Shortcut.WorkingDirectory = "D:\projekt\healthchat\healthchat"
if (Test-Path "D:\projekt\healthchat\healthchat\app_icon.ico") {
    $Shortcut.IconLocation = "D:\projekt\healthchat\healthchat\app_icon.ico"
}
$Shortcut.Description = "HealthChat Desktop Application"
$Shortcut.Save()
Write-Host "✅ Genvägen 'HealthChat Desktop' har skapats på ditt Skrivbord!"
