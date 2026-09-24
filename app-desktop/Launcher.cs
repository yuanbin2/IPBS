using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;

/// <summary>
/// 智能个人博客系统桌面启动器：隐藏窗口运行同目录下的 智能个人博客系统.bat。
/// 取代原 VBS 启动器 —— exe 可以内嵌应用图标（icon.ico），
/// 而独立的 .vbs 在资源管理器里只能显示文件类型默认图标。
/// 通过 build-launcher.bat 重新编译。
/// </summary>
internal static class Launcher
{
    private static int Main()
    {
        string directory = Path.GetDirectoryName(Assembly.GetEntryAssembly().Location);
        string batch = Path.Combine(directory, "\u667a\u80fd\u4e2a\u4eba\u535a\u5ba2\u7cfb\u7edf.bat");
        if (!File.Exists(batch))
        {
            return 2;
        }

        var startInfo = new ProcessStartInfo("cmd.exe", "/c \"" + batch + "\"")
        {
            WorkingDirectory = directory,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            UseShellExecute = false,
        };
        Process.Start(startInfo);
        return 0;
    }
}
