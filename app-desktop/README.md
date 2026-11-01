# Windows Edge App 启动器

`app-desktop` 是 Windows 快捷窗口启动工具，不是单独的 Electron 应用，也不负责准备后端依赖或数据库。

## 推荐启动

从仓库根目录运行 `start.bat` 启动本地博客（`http://127.0.0.1:8001/`）。需要双服务热更新时按根 README 使用 `restart.bat`，随后可双击本目录 `launch.bat` 打开 Edge App 窗口（固定访问 `http://127.0.0.1:5174`）。如端口未启动，`launch.bat` 只会打开地址，不会启动服务。

本目录内 `start-desktop.bat` / `start-desktop.ps1` 是旧脚本：仍假设 Django 使用 8000 端口，并且 BAT 退出时会结束所有 `python.exe`、`node.exe` 进程；不要用它启动或停止项目服务。使用根目录有进程归属检查的 `restart.bat` / `restart.sh` 管理开发服务。

测试、构建和功能限制见根 [README](../README.md) 与[文档索引](../docs/README.md)。
