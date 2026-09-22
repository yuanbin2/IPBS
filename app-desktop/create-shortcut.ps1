$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [System.Environment]::GetFolderPath('Desktop')
$Shortcut = $WshShell.CreateShortcut("$Desktop\Knowledge Agent.lnk")
$Shortcut.TargetPath = "E:\Desktop\MyProject\Blog-fixed-20260727\Blog\app-desktop\Knowledge Agent.vbs"
$Shortcut.WorkingDirectory = "E:\Desktop\MyProject\Blog-fixed-20260727\Blog\app-desktop"
$Shortcut.Description = "Knowledge Agent - 企业知识智能体平台"
$Shortcut.Save()
Write-Host "Done! Shortcut created on desktop."