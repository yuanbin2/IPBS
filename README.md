# 智能个人博客与知识 Agent

这是一个 Django + Vue 的个人博客与知识助手项目。仓库包含博客/草稿、私有笔记、知识库检索、Agent 对话与审批、浏览器剪藏扩展，以及浏览器本地截图 OCR 校对。功能实现情况和未验收范围以[缺陷跟踪表](docs/缺陷跟踪表V2.0.md)为准。

## 快速启动

### Windows

安装 Python 3.12+、Node.js 20+，在仓库根目录运行：

```bat
start.bat
```

首次启动脚本会创建 `.venv`、安装 `backend/requirements.txt` 与前端依赖、构建前端、迁移本地 SQLite，然后在 `http://127.0.0.1:8001/` 启动 Django。脚本明确设置 `BLOG_LOCAL_MODE=true`，此模式仅适合本地开发/演示，不代表 PostgreSQL、异步 worker 或生产安全配置已验收。

Linux/macOS 使用 `./start.sh`（需先 `chmod +x start.sh`），同样使用 SQLite 本地模式和 8001 端口。

### 前端热更新开发

首次按上面的步骤准备依赖后，Windows 可运行 `restart.bat`，Linux/macOS 可运行 `./restart.sh`。脚本启动后端 `127.0.0.1:8001` 与 Vite `127.0.0.1:5174`，访问 `http://127.0.0.1:5174/blog`。它会先检查端口，只结束本项目记录且可验证的旧进程；如果端口被其他程序占用会停止并提示。

也可在两个终端手动启动：

```powershell
# 终端 1：仓库根目录；已有本地虚拟环境及依赖
$env:BLOG_LOCAL_MODE = 'true'
.venv\Scripts\python.exe backend\manage.py runserver 127.0.0.1:8001

# 终端 2：仓库根目录
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

`frontend` 单独运行 `npm run dev` 的默认端口是 5173，默认 API 代理目标为 8000；需要本地完整博客时优先使用 `restart.bat` / `restart.sh`，或按上面命令显式设置匹配端口与代理。

## Docker Compose

Docker Compose 启动 Nginx/Vue、Django、PostgreSQL 16 + pgvector、Redis、RabbitMQ、Celery worker 与 beat。默认只把 HTTP 入口绑定到宿主机 `127.0.0.1:8080`，供已配置的 TLS 代理转发；内部数据库、缓存和消息队列不发布宿主机端口。PowerShell 首次准备：

```powershell
if (Test-Path .env) { throw '已有 .env；不要覆盖' }
Copy-Item .env.example .env
# 私下配置 DJANGO_SECRET_KEY、数据库/RabbitMQ 密码、站点域名与已验证的 TLS 代理标志。
docker compose config --quiet
docker compose up -d --build
```

POSIX shell 应先检查 `.env` 不存在再创建。不要提交 `.env`，也不要运行会输出解析后密钥的 `docker compose config`（应加 `--quiet`）。停止容器可用 `docker compose down`；**不要使用 `docker compose down -v`，它会删除数据库及媒体卷。**调试端口覆盖文件、TLS 代理契约与安全检查见[部署说明](docs/deployment.md)。Railway、对象存储、多实例及生产恢复行为仍需按缺陷表实站验收。

## 主要功能与边界

- 博客文章、版本修订、草稿和审核发布；新用户注册为 visitor，不会因公开注册获得 operator/admin 权限。
- 私有笔记按用户和工作空间隔离；私有笔记图片经认证读取，不由 Nginx 公开静态暴露。公开博客图片使用受控读取路径。
- 通用网页剪藏扩展默认交接到私有笔记草稿，可显式选博客文章草稿；扩展仅在用户操作时读取当前页面。安装和截图流程见[扩展说明](browser-extension/README.md)。
- HTML 文件可经校验、预览后导入博客草稿；外链图片会按当前预览/确认流程处理。它不是任意网页的无审核直发工具。
- 力扣链接预览/刷题文章辅助与领域目录可用；站点全文抓取、未授权题面/题解获取不提供。领域目录外部批量迁移见相应设计状态。
- 截图 OCR 在浏览器本地处理，支持扩展截图交接及本地图片、拼接图校对、候选配图确认、手动裁剪。OCR/像素候选不保证召回；CSS 背景、canvas 等区域可显示像素建议，仍需用户核对。截图原图不会因识别而自动保存或发布；只有用户确认裁图后才上传图片，文章发布仍须主动提交审核。详情见[长截图 OCR 说明](docs/长截图OCR转Markdown与私有笔记设计V3.0.md)和[跨屏图片设计及限制](docs/截图OCR跨屏图片识别设计V3.1.md)。
- 个人知识库、文档解析与向量检索可在本地演示；生产 pgvector、worker、embedding 供应商、真实语料和答案质量仍以缺陷表验收状态为准。

## 测试与构建

从仓库根目录运行：

```powershell
npm --prefix frontend run test:unit
npm --prefix frontend run build:check
$tests = Get-ChildItem browser-extension/tests -Filter '*.test.js' | Select-Object -ExpandProperty FullName
node --test $tests
```

Playwright 端到端测试：

```powershell
$env:E2E_BROWSER_CHANNEL = 'msedge'
$env:E2E_FRONTEND_PORT = '54327'
npm --prefix frontend run test:e2e -- e2e/screenshot-handoff.spec.ts
```

具体浏览器安装、服务启动与单个测试筛选见[文档索引](docs/README.md)。合成样本回归不代表真实网页识别率或生产部署验收。

## 文档入口

从[文档索引](docs/README.md)进入当前使用/开发文档、API、架构、数据库、部署与测试、进行中的设计和历史资料。扩展、长截图 OCR、私有图片、HTML 导入、领域目录和各测试入口均有专门链接。
