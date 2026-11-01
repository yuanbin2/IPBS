# I-017：公开文章直达页与分享信息

日期：2026-10-24。范围仅为默认 workspace 中已发布文章的公开 URL。以下是本地源码、隔离数据库和浏览器测试证据；没有生产爬虫、搜索结果页或分享平台抓取记录。

## 检查证据与实际缺口

| 检查点 | 修改前证据 | 本轮结果 |
| --- | --- | --- |
| 直达 `/blog/:slug` 的原始 HTML | `frontend/dist/index.html` 为 412 字节，只有通用 `<title>智能个人博客系统</title>` 与空 `#app`；Django `spa_index` 和 Nginx `try_files` 均返回该壳。 | Django 按请求读取同版本入口，查询默认 workspace 的 `published` 行，返回文章标题、描述、canonical、OG/Twitter、发布时间及安全封面，并在 `#app` 先显示标题和摘要。Vue 接管后继续走原 API 和交互。 |
| 加载与首屏 | 原始 HTML 无文章文字，必须下载 JS 并请求文章 API 才有内容。 | HTML 首包已有标题和摘要；隔离测试在文章有摘要时记录为 1 次数据库查询，且不读取正文大字段。没有测得真实首屏/LCP、弱网或生产负载收益。正文阅读仍由 Vue 加载，HTML 预览不代表完整服务端渲染。 |
| 索引与分享 | Nginx 静态 `robots.txt` 允许抓取，但 Django 单端口原先把 `/robots.txt` 落入 SPA 兜底；无文章专用元信息、canonical 或动态 sitemap。 | 已发布页返回可抓取元信息；两种部署入口现由 Django 返回包含 sitemap 地址的 `robots.txt`，sitemap 仅列默认 workspace 当前已发布文章。未发布、撤回、其他 workspace 或不存在的单篇 URL 返回 404 通用壳与 `X-Robots-Tag: noindex, nofollow`，不含私有正文。 |
| 更新与撤回 | 构建壳与数据库状态无关；分享平台可能缓存旧预览。 | 每次请求取当前发布记录并设置 `Cache-Control: no-store`；本地回归覆盖修改、刷新和撤回。第三方平台既有分享卡片缓存不能由源站响应保证清除。 |
| 构建产物 | Vite 静态入口不包含数据库文章。 | 构建仍只含通用壳；公开内容只在请求时从数据库读取。测试覆盖私有草稿、跨 workspace 和待审批修订内容未进入公开 HTML。 |

## 决策

| 方案 | 收益 | 成本与限制 | 决定 |
| --- | --- | --- | --- |
| 维持纯 SPA | 无部署变化 | 直达 HTML 缺文章标题、描述、分享信息和首屏文字 | 不采用 |
| 文章页局部按请求预渲染 | 沿用 Django 发布权限和 Vue，修改/撤回即时生效；只处理单篇公开路由 | 每次请求一次数据库查询；后端镜像须包含同版本前端入口；正文仍由 JS 渲染 | **本轮采用** |
| SSG | 首包可包含完整正文，静态服务快 | 发布/修订/撤回需构建或可靠增量失效，私有内容误入构建的边界更难控制 | 暂不采用 |
| 全站 SSR / Nuxt | 可服务端渲染完整文章和更多路由 | 迁移路由、鉴权、编辑器及部署，成本明显高于当前已确认缺口；没有性能/收录证据支撑 | 暂不采用 |

后续若真实抓取显示正文索引不足，再考虑仅对公开文章输出完整服务端正文；若实测首屏指标或路由规模需要，再重评 SSG/SSR。聊天、私有笔记与登录后工具页面不参与公开预渲染。

## 运行路径与回退

- 本地 Django 单端口与 Compose Nginx 的单段 `/blog/:slug` 请求进入同一视图；`/blog/collections`、`/blog/settings` 和多段目录仍走 SPA。`/robots.txt` 与 `/sitemap.xml` 也由 Django 现查当前发布状态。Nginx 将原始 URL 与代理协议传给 Django。
- 前后端镜像从相同源码分别构建；Compose 后端镜像增加 Node 构建阶段，只复制 `dist/index.html`，Nginx 镜像继续服务 CSS/JS。根目录独立 Django `Dockerfile` 复制完整 `dist`，以便它自身的静态资源路由能服务入口引用的文件。构建时间与镜像/缓存占用增加（本地 `dist` 约 90 MB）；发布时应核对两镜像的发布 ID、入口中的资源哈希及 Nginx 资源 200。单独回滚一侧可能造成资源哈希不匹配。
- 更新/撤回无需重新构建，但必须验证代理/CDN 不覆盖 `no-store`。搜索平台和社交平台的旧缓存需要按平台机制另行刷新。
- 回退时同时恢复前后端镜像的同一发布版本，并恢复原 Nginx 文章路由配置；无需数据库迁移。

## 验证与未验证

- 后端隔离 Django 测试：`test_blog`、`test_blog_seo` 与 `apps.core` 共 59/59；新增 `test_blog_seo` 6/6。覆盖直达 HTML、转义、canonical、更新、撤回、动态 sitemap/robots、草稿/跨空间/待审批修订隔离及保留路由。其中一个用例通过本地 LiveServer 真实 HTTP 请求验证 200、404、首包 HTML 与缓存头；仍使用临时前端壳和测试数据库，没有操作用户文章，也不是生产代理或搜索平台抓取。Ruff/Black 检查通过。
- 前端：`npm run build:check -- --logLevel error`、`npm run test:unit`；隔离 Edge E2E 覆盖从列表打开文章时标题/OG/canonical 更新、返回时清理。Vite E2E 验证的是浏览器端路由行为，不验证生产 Nginx 代理。
- 尚未完成：Docker Engine 不可用，未实际构建/启动 Compose 镜像或运行 `nginx -t`；未用真实公网 URL 测抓取、分享预览、收录、LCP/P95；未验证 CDN 缓存失效与跨浏览器。当前 sitemap 为单文件，文章量接近 5 万 URL 时须增加分片。关闭 I-017 前需用隔离部署的公开样本做 `curl -i /blog/<slug>/`、刷新、修改与撤回，同时核对 `/robots.txt`、`/sitemap.xml`，再以至少一个分享平台抓取工具及浏览器性能记录实测。
