# 实验性 Electron 桌面原型

`desktop/` 是独立于根目录主 Web 应用的 Electron/Vite 原型。它有单独的 `package.json`、renderer、Electron 主进程和打包脚本，**不是根 README 所述的受支持启动路径，也没有在本轮文档整理中完成打包/登录/API 兼容验收**。

## 当前可核对的脚本与限制

依赖锁文件存在时可在此目录执行 `npm ci`。可用脚本以 `package.json` 为准：`npm run dev`、`npm run build`、`npm run package` 及 `package:win/mac/linux`。开发 renderer 的 `vite.config.js` 绑定 `127.0.0.1:5174`，API 代理写死 `http://127.0.0.1:8000`；根目录 `restart.bat` 当前后端为 `8001`，因此两者默认不匹配。Electron 入口、主进程和 Vite 配置也存在独立迭代，启动/打包结果需单独验证。

主要博客与知识 Agent 的推荐本地启动路径是根目录 `start.bat` / `restart.bat`，桌面窗口可用 `app-desktop/launch.bat` 打开当前 Web 应用。该 Edge App 启动器与本原型不是同一程序。

历史 Quickstart、实现总结和变更记录仅供原型开发背景参考，不表示当前发行包已发布或功能已验收。通用项目入口见[根 README](../README.md)和[文档索引](../docs/README.md)。
