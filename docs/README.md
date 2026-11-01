# 项目文档索引

从仓库 [README](../README.md) 开始。**使用步骤和当前实现看“当前使用与开发”**；设计文件说明功能边界及阶段状态，不自动代表验收完成；已完成度和外部验收看[缺陷跟踪表](缺陷跟踪表V2.0.md)。模型、路由、迁移和配置是事实来源。

## 使用与开发

| 主题 | 当前入口 |
| --- | --- |
| 本地启动、Compose、测试脚本 | [根 README](../README.md)、[部署说明](deployment.md) |
| API 与权限边界 | [API 索引](api.md)、`backend/apps/agent_api/api_urls/` 与 View 权限 |
| 当前系统拓扑 | [架构概览](architecture.md) |
| 数据表与媒体安全边界 | [当前数据库概览](database-current.md)、`backend/apps/agent_api/models/` 与 `migrations/` |
| 目录结构与开发参考 | [项目结构](project-structure.md)、[代码规范草案](coding-conventions.md)（包含日期化迁移计划，路径与状态须核对源码）、[模型包说明](../backend/apps/agent_api/models/README.md) |
| 浏览器扩展安装、网页剪藏、截图 | [扩展使用说明](../browser-extension/README.md) |
| Windows Edge App 窗口 | [app-desktop 启动器](../app-desktop/README.md)；实验性 Electron 原型见[单独说明](../desktop/README.md) |

## 功能设计、限制与当前状态

| 功能 | 参考文档 | 状态核对 |
| --- | --- | --- |
| 长截图 OCR → Markdown、逐块校对、私有笔记/草稿 | [长截图 OCR V3.0](长截图OCR转Markdown与私有笔记设计V3.0.md) | 已有本地实现；真实样本质量门槛见 B-045/B-048 |
| OCR 配图跨屏合并、候选确认与裁剪限制 | [配图设计 V3.1](截图OCR跨屏图片识别设计V3.1.md) | 本地实现并合成样本 Edge 回归；真实用户图像和识别率待验收 |
| HTML 导入 Markdown 草稿 | [HTML 导入 V2.4](HTML导入Markdown博客设计V2.4.md) | 本地预览/确认实现；公网来源、Bucket 和真实样本仍待验证 |
| ~~力扣链接建卡与本人解题内容导入~~ | [力扣导入 V2.5](力扣题目与题解导入设计V2.5.md) | **已取消（2026-10-07）**：用户主动删除该功能，代码已移除，B-041 在缺陷表中标记为已取消；本文仅作历史存档 |
| 领域目录与系列文章 | [目录功能 V2.6](领域知识目录与系列博客设计V2.6.md) | B-042A/B/C 本地实现；性能、移动设备和用户任务待验证 |
| 从已有网站迁移目录 | [网页迁移 V2.8](领域目录网页迁移设计V2.8.md) | B-044 设计/验收待办；当前没有自动抓取整站的通用能力 |
| 写作、阅读与私有笔记体验 | [体验计划 V2.1](写作阅读与笔记体验升级计划V2.1.md) | 部分实现；按缺陷表和对应测试核对 |
| 评论侧栏和评论治理 | [评论设计 V2.2](评论侧栏扩展设计V2.2.md) | 分页与审核已有本地实现；真实 PostgreSQL 性能/用户任务按缺陷表待验收 |
| 网页剪藏与私有图片修复证据 | [剪藏验收 V2.9.2](网页剪藏修复验收记录V2.9.2.md)、[图片清理说明](博客图片清理说明V2.0.md) | 验收记录不替代生产 Bucket 与真实侧载验收 |

## 架构/API/数据库参考

- [架构概览](architecture.md)、[I-021 架构与技术取舍](I-021-当前架构与技术取舍.md)和 [API 索引](api.md) 是当前入口；route/View 为准。[新功能设计模板](templates/新功能设计模板.md)及其 [I-017 填写样例](I-021-模板验证-I-017公开文章.md)用于新改进的场景、权限与验收记录。
- [当前数据库概览](database-current.md)；逐字段和关系的早期材料在下方“历史资料”。
- [Blog 产品/治理设计基线](Blog设计文档V2.0.md)仍包含计划、设计目标与缺陷关联；验收状态以缺陷表为准。

## 部署与验证

- [部署说明](deployment.md)：本地 8001、热更新 8001/5174、Compose 端口和安全边界。生产实站声明不得从本地测试推断。
- [发布阻断审查](发布阻断审查V2.0.md)：阶段性审查快照；更晚状态看缺陷表和提交 CI。
- [评测/测试升级方案](评测与测试升级方案V2.0.md)、[答案人工复核计划](智能体答案质量与人工复核计划V2.4.md)、[Agent 验证记录](Agent能力增强与验证记录V2.3.md)。规则测试不代表人工真值集或真实模型质量已达标。
- 所有当前缺陷、测试证据与未验收项：[缺陷跟踪表](缺陷跟踪表V2.0.md)。
- AI 全栈、Agent 架构、评测与交付的后续开发任务：[工程改进跟踪表 V1.0](AI全栈与Agent工程改进跟踪表V1.0.md)。包含优先级、当前证据、依赖、验收标准与实施记录；不代表功能已完成。

## 历史资料（不作为当前操作或系统状态来源）

下列文档保留决策、研究或早期实现记录；其中端口、API、认证、模型/字段和测试数量可能过时。当前操作请用上方链接，历史数据不要据此宣称功能或部署现状：

- [架构分析报告](architecture-analysis.md)、[早期数据库 ER 图](database-er-diagram.md)（不完整历史关系图）。
- [数据库逻辑设计 V2.0](数据库设计文档V2.0.md)、[数据库概念设计](database-design.md)、[字段参考手册](database-schema-reference.md)、[模型拆分设计](models-design.md)。这些旧数据库设计材料均已在文首标记限制，只有 `database-current.md` 是当前概览。
- [早期迭代蓝图](design-blueprint.md)、[早期系统知识摘要](SYSTEM_KNOWLEDGE_BASE.md)、[旧 API/异步/JWT 说明](restful-async-architecture.md)、[旧后端部署指南](backend-deployment-guide.md)。
- [早期力扣扩展设计](浏览器扩展连接博客设计V2.7.md)、[通用剪藏 V2.9 设计快照](网页剪藏到博客设计V2.9.md)、[修复报告](repair-report.md)、[旧评估报告](evaluation-report.md)。
- [最终博客文章](final-blog-post.md)是历史/演示材料，不是当前运行说明。

## 辅助与个人作品材料

以下材料用于演示/学习/求职，不是系统操作或质量验收证据：[演示脚本](demo-script.md)、[简历项目描述](resume.md)、[岗位准备指南](job-preparation-guide.md)、[全栈面试手册](python-fullstack-interview-guide.md)。其中个人履历与面试材料仅在作者需要时维护，不对外推断身份信息。

## 文档整理记录

- [逐文件文档盘点](document-inventory.md)：整理开始时 61 份仓库 Markdown 的用途、对应实现证据、当前/历史状态、处理动作与理由；根目录 Lark 导出与 `IPBS/欢迎.md` 仅按路径登记为外部资料，未读取或改写正文。
