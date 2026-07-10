# Day 10: MCP 工具接入

## 学习目标

把外部工具统一抽象为 MCP Tool Registry，让 Agent 不只做 RAG，还能调用受控工具完成任务。

## 本日实现

- 新增 `MCPTool` 工具注册模型。
- 新增 MCP 工具 API：
  - `GET /api/agent/mcp-tools/`
  - `PATCH /api/agent/mcp-tools/<id>/`
  - `POST /api/agent/mcp-tools/<id>/execute/`
- 新增前端工具管理页：`/mcp-tools`。
- Supervisor 新增 `MCP Tool Agent` 路由。

## 默认注册工具

```text
local_file_search     本地文件搜索
git_repo_info         Git 仓库信息
web_search            网页搜索占位，默认禁用
safe_database_stats   安全数据库统计
```

## 工具治理

每个工具记录：

- 工具名称
- 展示名称
- 分类
- 权限范围
- 是否启用
- 是否需要审批
- 最近调用时间

管理员可以在 `/mcp-tools` 启用或禁用工具，也可以把工具设为需要审批。

## Agent 调用路径

```text
用户提问
  -> Supervisor Agent
  -> MCP Tool Agent
  -> 查询 MCPTool 注册表
  -> 检查启用状态 / 审批要求
  -> 调用本地 MCP-style adapter
  -> 返回工具结果
```

## 当前产出

Agent 已具备基础外部工具接入能力。后续可以把这些本地 adapter 替换为真正的 `langchain-mcp-adapters` 连接器或远程 MCP Server。
