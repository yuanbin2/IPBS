# Knowledge Agent Desktop - 快速开始指南

## 5 分钟快速启动

### 前置要求

确保已安装：
- Node.js 18+ (下载地址: https://nodejs.org/)
- Python 3.10+ (用于后端)

### 步骤 1: 安装依赖

**Windows:**
```cmd
cd desktop
npm install
```

**macOS/Linux:**
```bash
cd desktop
npm install
```

### 步骤 2: 启动开发服务器

**Windows:**
```cmd
npm run dev
```

**macOS/Linux:**
```bash
npm run dev
```

应用将自动打开，显示桌面界面。

### 步骤 3: 连接后端

确保后端服务正在运行：

```bash
# 在项目根目录
cd backend
python manage.py runserver
```

桌面应用将自动连接到 `http://127.0.0.1:8000`。

## 常见问题

### Q: 应用无法启动？

**A:** 尝试以下步骤：
1. 清除缓存：`rm -rf node_modules out`
2. 重新安装：`npm install`
3. 检查 Node.js 版本：`node --version`

### Q: 无法连接后端？

**A:** 检查以下几点：
1. 后端服务是否正在运行
2. 端口 8000 是否被占用
3. 防火墙设置

### Q: 构建失败？

**A:** 尝试：
1. 类型检查：`npm run typecheck`
2. 查看错误信息
3. 检查 TypeScript 配置

## 下一步

### 开发新功能

1. 在 `src/features/` 下创建功能模块
2. 在 `src/views/` 下创建页面视图
3. 在 `src/router/index.ts` 中添加路由

### 构建安装包

```bash
# Windows
npm run package:win

# macOS
npm run package:mac

# Linux
npm run package:linux
```

安装包将生成在 `release/` 目录。

### 查看文档

- [README.md](README.md) - 完整文档
- [CONTRIBUTING.md](CONTRIBUTING.md) - 贡献指南
- [CHANGELOG.md](CHANGELOG.md) - 更新日志

## 获取帮助

- 查看 [Issues](https://github.com/your-repo/issues) 获取帮助
- 阅读 [Electron 文档](https://www.electronjs.org/)
- 阅读 [Vue 3 文档](https://vuejs.org/)

## 示例代码

### 添加新页面

```vue
<!-- src/views/MyView.vue -->
<script setup lang="ts">
import { ref } from 'vue'

const message = ref('Hello from MyView!')
</script>

<template>
  <div class="my-view">
    <h1>{{ message }}</h1>
  </div>
</template>
```

### 添加路由

```typescript
// src/router/index.ts
const MyView = () => import('../views/MyView.vue')

const routes = [
  // ... 现有路由
  {
    path: '/my-view',
    name: 'my-view',
    component: MyView
  }
]
```

### 使用 IPC 通信

```typescript
// 在 Vue 组件中
const result = await window.api.backend.status()
console.log('Backend status:', result)
```

## 技术支持

如有问题，请通过以下方式联系：
- GitHub Issues
- Email: your-email@example.com

祝您使用愉快！🎉
