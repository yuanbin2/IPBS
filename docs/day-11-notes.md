# 第 11 天：可观测性 + 评估集

## 目标

把 Agent 从“能回答”推进到“能证明效果”：每次运行都有 trace、耗时、工具调用、失败原因，管理端可以用评估集持续验证效果。

## 后端能力

- 新增 `AgentObservation`：记录输入、回答、路由、选中的 Agent、trace、工具调用、引用来源、token usage、耗时、工具成功率和失败原因。
- 新增 `EvaluationCase`：内置 30 条评估问题，覆盖博客类、知识库类、复杂推理类、越权攻击类。
- 新增 `EvaluationRun`：保存每次评估结果和指标。
- `/api/agent/chat/` 自动写入观测记录，异常时也会记录失败原因。
- 新增接口：
  - `GET /api/agent/observability/`
  - `GET /api/agent/evaluation-cases/`
  - `POST /api/agent/evaluation-runs/`

## 评估指标

- `answer_correctness`：参考关键词命中 + 预期 Agent 路由。
- `faithfulness`：回答是否保持在知识库、引用、审批、安全拒答等可解释范围内。
- `citation_accuracy`：需要引用时是否给出 sources。
- `latency_ms`：端到端耗时。
- `tool_success_rate`：工具调用是否成功返回。

## 前端能力

新增 `/observability` 页面：

- 指标卡片：运行次数、成功率、平均耗时、工具成功率。
- 运行记录：查看输入、选中 Agent、trace、工具数、引用数和失败原因。
- 评估集：按类型筛选 30 条评估题。
- 可单题评估，也可以一键跑前 5 题。

## LangSmith 接入策略

当前项目默认不强依赖外部服务。后端会读取：

- `LANGSMITH_API_KEY`
- `LANGSMITH_PROJECT`

如果后续配置 LangSmith tracing，可以把本地 `AgentObservation` 与 LangSmith run id 对齐；没有 Key 时，本地观测和评估仍然完整可用。

## 验收

- 后端测试覆盖观测记录、评估集、评估运行。
- 前端构建需要通过 `npm run build`。
- 数据库需要执行迁移到 `0010_observability_evaluation`。
