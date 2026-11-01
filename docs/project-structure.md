# 当前代码目录

以当前目录树为准。根目录 `agent/` 是旧实验代码目录；当前 Django Agent/RAG 实现在 `backend/apps/agent_api/` 与 `backend/agent/`。新开发应优先沿当前路由、服务、模型和测试模块定位，不应按旧日程笔记寻找源码。

```text
backend/
  config/                         Django 设置、根 URL、ASGI/WSGI、Celery
  apps/core/                      健康检查与平台基础能力
  apps/agent_api/
    api_urls/                     认证、Agent、知识、治理、博客、项目路由
    views/                        DRF 请求/权限层
    services/                     博客、RAG、导入、媒体与业务服务
    models/                       按领域拆分的 ORM 模型
    migrations/                   数据库 schema 迁移
    tasks.py                      Celery 任务
frontend/src/
  api/                            API 客户端
  features/blog/                  博客、私有笔记、HTML/截图导入功能
  views/                          页面级组件
browser-extension/                Manifest V3 剪藏与截图采集扩展
app-desktop/                      Windows Edge App 模式启动器
desktop/                          单独的实验性 Electron 项目
 docs/                            当前说明、计划、验收与历史材料
```

## 主要入口

- Django URL：`backend/config/urls.py` → `/api/agent/` → `backend/apps/agent_api/api_urls/`。
- 博客路由：`backend/apps/agent_api/api_urls/blog.py`；具体权限和字段由 View、Serializer、测试定义。
- 数据库：`backend/apps/agent_api/models/` 与 `migrations/`。
- 前端路由：`frontend/src/router/`；主要页面 `frontend/src/views/`。
- Vite 脚本和测试：`frontend/package.json`。
- 本机一键入口：仓库根 `start.bat` / `start.sh`；热更新重启入口：`restart.bat` / `restart.sh`。
- Compose 服务定义：根 `docker-compose.yml`。

此处是代码导航，不是架构承诺。异步、权限、存储和实站验收边界见[架构](architecture.md)、[部署](deployment.md)和[缺陷跟踪表](缺陷跟踪表V2.0.md)。
