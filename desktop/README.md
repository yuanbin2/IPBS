# Knowledge Agent Desktop

企业知识智能体平台 - 桌面应用程序

基于 Electron + Vue 3 构建的桌面应用，提供原生桌面体验。

## 功能特性

- 🖥️ **原生桌面体验** - 自定义标题栏、系统托盘、窗口控制
- 🤖 **多智能体对话** - 支持 SSE 流式对话，实时显示思考过程
- 📝 **博客管理** - Markdown 编辑器，文章管理
- 📚 **知识库** - 文档上传、向量检索、知识问答
- 🔧 **MCP 工具** - 工具管理、执行、审批流程
- 📊 **可观测性** - Agent 运行指标、评估测试
- 🔒 **安全审计** - 敏感输入检测、输出脱敏、人工审批

## 技术栈

- **前端**: Vue 3 + TypeScript + Element Plus + Pinia + Vue Router
- **桌面框架**: Electron 28
- **构建工具**: Vite 5 + electron-vite
- **后端**: Django 5 + DRF + LangGraph (需单独运行)

## 快速开始

### 前置要求

- Node.js 18+
- npm 或 yarn
- Python 3.10+ (用于后端)

### 安装依赖

```bash
cd desktop
npm install
```

### 开发模式

```bash
npm run dev
```

这将启动 Electron 开发环境，支持热重载。

### 构建应用

```bash
# 构建所有平台
npm run build

# 打包 Windows 安装包
npm run package:win

# 打包 macOS 安装包
npm run package:mac

# 打包 Linux 安装包
npm run package:linux
```

## 项目结构

```
desktop/
├── electron/                    # Electron 主进程
│   ├── main.ts                 # 主进程入口
│   ├── preload.ts              # 预加载脚本
│   └── ipc-handlers.ts         # IPC 处理器
├── src/                        # 渲染进程 (Vue 应用)
│   ├── desktop/                # 桌面特定代码
│   │   ├── components/         # 桌面组件
│   │   ├── stores/             # 桌面状态管理
│   │   └── utils/              # 工具函数
│   ├── api/                    # API 客户端
│   ├── components/             # 共享组件
│   ├── features/               # 功能模块
│   │   ├── blog/              # 博客功能
│   │   ├── chat/              # 对话功能
│   │   └── knowledge/         # 知识库功能
│   ├── router/                 # 路由配置
│   ├── stores/                 # 状态管理
│   ├── views/                  # 页面视图
│   ├── App.vue                 # 根组件
│   ├── main.ts                 # 应用入口
│   ├── style.css               # 全局样式
│   └── index.html              # HTML 模板
├── package.json                # 项目配置
├── electron-builder.json       # 打包配置
├── vite.config.ts              # Vite 配置
├── tsconfig.json               # TypeScript 配置
├── tsconfig.node.json          # Node.js TypeScript 配置
└── tsconfig.web.json           # Web TypeScript 配置
```

## 配置说明

### 后端连接

默认连接到 `http://127.0.0.1:8000`。可以通过以下方式修改：

1. 环境变量 `VITE_API_BASE_URL`
2. 修改 `src/desktop/utils/backend.ts` 中的配置

### 构建配置

打包配置在 `electron-builder.json` 中，支持：

- **Windows**: NSIS 安装包
- **macOS**: DMG 镜像
- **Linux**: AppImage 和 DEB 包

## 开发指南

### 添加新功能

1. 在 `src/features/` 下创建功能模块
2. 在 `src/views/` 下创建页面视图
3. 在 `src/router/index.ts` 中添加路由
4. 如需桌面特定功能，在 `src/desktop/` 下扩展

### IPC 通信

桌面应用通过 IPC 与主进程通信：

```typescript
// 渲染进程
const result = await window.api.backend.status()

// 主进程
ipcMain.handle('backend:status', async () => {
  // 处理逻辑
})
```

### 样式定制

全局样式在 `src/style.css` 中，使用 CSS 变量：

```css
:root {
  --color-primary: #276678;
  --color-bg-sidebar: #17262e;
  /* ... */
}
```

## 故障排除

### Electron 启动失败

```bash
# 清除缓存重新安装
rm -rf node_modules
rm -rf out
npm install
```

### 后端连接失败

1. 确保后端服务正在运行
2. 检查端口 8000 是否被占用
3. 验证防火墙设置

### 构建失败

```bash
# 检查 TypeScript 错误
npm run typecheck

# 重新构建
npm run build
```

## 相关链接

- [Vue 3 文档](https://vuejs.org/)
- [Electron 文档](https://www.electronjs.org/)
- [Element Plus 文档](https://element-plus.org/)
- [electron-vite 文档](https://electron-vite.org/)

## 许可证

MIT License
