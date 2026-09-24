using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;

/// <summary>
/// Knowledge Agent 桌面启动器：隐藏窗口运行同目录下的 Knowledge Agent.bat。
/// 取代原 Knowledge Agent.vbs —— exe 可以内嵌应用图标（icon.ico），
/// 而独立的 .vbs 在资源管理器里只能显示文件类型默认图标。
/// 通过 build-launcher.bat 重新编译。
/// </summary>
internal static class Launcher
{
    private static int Main()
    {
        string directory = Path.GetDirectoryName(Assembly.GetEntryAssembly().Location);
        string batch = Path.Combine(directory, "Knowledge Agent.bat");
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
