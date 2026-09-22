# Contributing to Knowledge Agent Desktop

感谢您对 Knowledge Agent Desktop 项目的关注！本文档将帮助您了解如何参与项目开发。

## 开发环境设置

### 前置要求

- Node.js 18+ (推荐使用 LTS 版本)
- npm 或 yarn
- Git
- Python 3.10+ (用于后端开发)

### 克隆项目

```bash
git clone <repository-url>
cd Blog/desktop
```

### 安装依赖

```bash
npm install
```

### 启动开发服务器

```bash
npm run dev
```

## 项目结构

```
desktop/
├── electron/              # Electron 主进程代码
│   ├── main.ts           # 主进程入口
│   ├── preload.ts        # 预加载脚本
│   └── ipc-handlers.ts   # IPC 处理器
├── src/                  # 渲染进程代码 (Vue 应用)
│   ├── desktop/          # 桌面特定功能
│   │   ├── components/   # 桌面组件
│   │   ├── stores/       # 桌面状态管理
│   │   └── utils/        # 工具函数
│   ├── api/              # API 客户端
│   ├── components/       # 共享组件
│   ├── features/         # 功能模块
│   ├── router/           # 路由配置
│   ├── stores/           # 状态管理
│   └── views/            # 页面视图
├── build/                # 构建资源 (图标等)
├── package.json          # 项目配置
└── electron-builder.json # 打包配置
```

## 开发流程

### 1. 创建功能分支

```bash
git checkout -b feature/your-feature-name
```

### 2. 开发功能

- 在 `src/features/` 下创建新功能模块
- 在 `src/views/` 下创建页面视图
- 在 `src/router/index.ts` 中添加路由
- 如需桌面特定功能，在 `src/desktop/` 下扩展

### 3. 测试功能

```bash
# 运行开发服务器
npm run dev

# 类型检查
npm run typecheck

# 构建测试
npm run build
```

### 4. 提交代码

```bash
git add .
git commit -m "feat: add your feature description"
```

### 5. 推送并创建 PR

```bash
git push origin feature/your-feature-name
```

## 代码规范

### TypeScript

- 使用 TypeScript 进行类型安全
- 避免使用 `any` 类型
- 为复杂类型定义接口

### Vue 组件

- 使用 Composition API (`<script setup>`)
- 组件名使用 PascalCase
- Props 使用 TypeScript 接口定义

### 样式

- 使用 CSS 变量进行主题定制
- 遵循现有的设计系统
- 响应式设计优先

### 命名规范

- 文件名: kebab-case (`my-component.vue`)
- 组件名: PascalCase (`MyComponent`)
- 变量/函数: camelCase (`myVariable`)
- 常量: UPPER_SNAKE_CASE (`MY_CONSTANT`)

## IPC 通信

### 添加新的 IPC 处理器

1. 在 `electron/ipc-handlers.ts` 中添加处理器：

```typescript
ipcMain.handle('your:handler', async (event, data) => {
  // 处理逻辑
  return result
})
```

2. 在 `electron/preload.ts` 中暴露 API：

```typescript
contextBridge.exposeInMainWorld('api', {
  yourMethod: (data) => ipcRenderer.invoke('your:handler', data)
})
```

3. 在 Vue 组件中使用：

```typescript
const result = await window.api.yourMethod(data)
```

## 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

- `feat:` 新功能
- `fix:` 修复 bug
- `docs:` 文档更新
- `style:` 代码格式调整
- `refactor:` 代码重构
- `test:` 测试相关
- `chore:` 构建/工具相关

示例：

```bash
git commit -m "feat: add system tray support"
git commit -m "fix: window close button not working"
git commit -m "docs: update README installation guide"
```

## 问题反馈

### 提交 Issue

使用 GitHub Issues 报告问题或提出建议：

1. 使用清晰的标题描述问题
2. 提供详细的复现步骤
3. 包含错误信息和截图
4. 说明您的环境信息

### 功能请求

使用 Issue 模板提交功能请求：

1. 描述功能需求
2. 说明使用场景
3. 提供设计草图（如有）

## 发布流程

### 版本号

使用 [Semantic Versioning](https://semver.org/)：

- MAJOR.MINOR.PATCH
- 例如: 1.0.0, 1.1.0, 1.1.1

### 发布步骤

1. 更新 `package.json` 中的版本号
2. 更新 CHANGELOG.md
3. 创建 Git 标签
4. 推送到 GitHub
5. GitHub Actions 自动构建并发布

## 联系方式

如有问题，请通过以下方式联系：

- GitHub Issues
- Email: <your-email>
- Discord: <your-discord>

感谢您的贡献！🎉
