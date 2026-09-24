$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [System.Environment]::GetFolderPath('Desktop')
$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Shortcut = $WshShell.CreateShortcut("$Desktop\智能个人博客系统.lnk")
$Shortcut.TargetPath = Join-Path $AppDir "智能个人博客系统.exe"
$Shortcut.WorkingDirectory = $AppDir
$Shortcut.Description = "智能个人博客系统"
# exe 内嵌了应用图标；显式指向它，项目移动后也不会丢图标
$Shortcut.IconLocation = (Join-Path $AppDir "智能个人博客系统.exe") + ",0"
$Shortcut.Save()
Write-Host "Done! Shortcut created on desktop with the app icon."
