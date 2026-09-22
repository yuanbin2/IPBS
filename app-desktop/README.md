# Knowledge Agent Desktop

## 快速启动

### 方法1: 一键启动（推荐）

确保后端和前端已经在运行，然后双击 `launch.bat`。

### 方法2: 完整启动

双击 `start-desktop.bat`，它会自动：
1. 启动后端 Django 服务器
2. 启动前端 Vite 开发服务器
3. 用 Edge 桌面模式打开应用

### 方法3: 手动启动

```bash
# 终端1: 启动后端
cd backend
python manage.py runserver

# 终端2: 启动前端
cd frontend
npm run dev

# 终端3: 打开桌面窗口
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --app=http://127.0.0.1:5173 --window-size=1400,900
```

## 为什么用 Edge App 模式？

这台机器上的 Electron 安装有模块加载问题（`require('electron')` 无法解析内置模块）。Edge App 模式提供了类似的桌面体验：

- ✅ 无地址栏的纯净窗口
- ✅ 独立的用户数据目录
- ✅ 可以固定到任务栏
- ✅ 支持窗口控制
- ✅ 零额外依赖

## 后续改进

如果需要真正的 Electron 桌面应用，可以：
1. 在另一台机器上构建 Electron 应用
2. 使用 GitHub Actions 自动构建
3. 修复当前机器的 Electron 安装问题