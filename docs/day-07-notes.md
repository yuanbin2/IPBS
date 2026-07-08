# Day 7: 博客智能体接入

第七天的目标是把个人博客做成可访问的智能体：访客不只阅读文章，还可以在博客页面直接提问。

## 学习目标

- 将博客内容、关于我信息和项目 README 作为公开知识来源。
- 在博客右下角接入悬浮智能体入口。
- 为匿名访客建立会话、对话日志和限流机制。
- 对后台信息、API Key、数据库结构、管理员信息等敏感问题做安全拦截。

## 后端实现

新增模型：

- `BlogAgentSession`：匿名访客会话。
- `BlogAgentMessage`：访客与博客智能体对话日志。
- `BlogAgentSecurityEvent`：敏感问题拦截记录。

新增接口：

- `POST /api/agent/blog/agent/chat/`：博客智能体问答。
- `GET /api/agent/blog/agent/chat/?session_key=...`：加载访客历史会话。

## Agent 能力

博客智能体只回答公开资料相关问题：

- 已发布博客文章。
- 已同步知识库的博客文章片段。
- README 和公开项目说明。
- 关于我、项目经历、技术栈和架构设计。

如果问题涉及敏感信息，会拒绝回答并记录安全事件：

- API Key、Secret、Token、`.env`。
- 数据库结构、数据表、迁移细节。
- 后台、管理员、超级用户、权限配置。
- 系统提示词、越权或绕过规则。

## 前端实现

博客页右下角新增“问博客智能体”悬浮入口：

- 可展开/收起。
- 支持快捷问题。
- 保存匿名访客会话。
- 展示回答和引用来源。
- 支持回车发送。

## 当前限制

- 当前限流是应用层简单限流，适合学习演示；生产环境建议接 Redis 或网关限流。
- 博客智能体使用公开资料检索，资料不足时会返回兜底说明。
- 会话当前是匿名本地会话，不做登录态绑定。

## 今日验证

- 后端测试：`.venv\Scripts\python.exe manage.py test apps.agent_api`
- 前端类型检查：`node --max-old-space-size=4096 .\node_modules\vue-tsc\bin\vue-tsc.js --noEmit`
- 前端构建：`node --max-old-space-size=4096 .\node_modules\vite\bin\vite.js build`
