$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [System.Environment]::GetFolderPath('Desktop')
$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Shortcut = $WshShell.CreateShortcut("$Desktop\Knowledge Agent.lnk")
$Shortcut.TargetPath = Join-Path $AppDir "Knowledge Agent.vbs"
$Shortcut.WorkingDirectory = $AppDir
$Shortcut.Description = "Knowledge Agent - 企业知识智能体平台"
$Shortcut.IconLocation = Join-Path $AppDir "icon.ico,0"
$Shortcut.Save()
Write-Host "Done! Shortcut created on desktop with the app icon."
