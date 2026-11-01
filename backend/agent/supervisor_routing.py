"""Supervisor 路由判定：安全优先级 + 业务关键词 → 专用 Agent。

纯函数、无 IO，可独立单测（见 tests/test_agent.py 的 SupervisorRoutingTests）；
判定顺序即优先级：治理/审批 > MCP 能力 > 系统事实 > 私有文档 > 话题匹配 >
检索关键词 > 工具 > 审查 > 统计 > 博客 > 写作 > 兜底知识能力入口。
Supervisor 选专用 Agent；兜底入口的内部查询分析器再决定直接回答或检索。
"""

from __future__ import annotations

import re

from .agent_types import SpecializedAgentName, SupervisorDecision  # noqa: F401 — 类型再导出

MCP_CAPABILITY_KEYWORDS = [
    "网页搜索",
    "网络搜索",
    "网上搜索",
    "联网搜索",
    "web search",
    "在网络中查找",
    "在网络中搜索",
    "在网上查找",
    "在网上搜索",
    "用网络查找",
    "用网络搜索",
    "本地文件",
    "项目文件",
    "文件搜索",
    "代码搜索",
    "git 仓库",
    "git状态",
    "git 状态",
    "数据库统计",
    "系统统计",
    "现在几点",
    "几点了",
    "当前时间",
    "现在时间",
    "今天日期",
    "今天几号",
    "current time",
]

WEB_SEARCH_TOOL_KEYWORDS = [
    "网页",
    "联网",
    "网络搜索",
    "网上搜索",
    "互联网",
    "web",
    "在网络中查找",
    "在网络中搜索",
    "在网上查找",
    "在网上搜索",
    "用网络查找",
    "用网络搜索",
    "网页搜索",
]

TECHNICAL_TOPIC_SUFFIXES = (
    "成像",
    "算法",
    "模型",
    "技术",
    "方法",
    "网络",
    "学习",
    "重建",
    "检测",
    "识别",
    "计算",
)

RETRIEVAL_KEYWORDS = [
    "数据库",
    "自己的数据库",
    "知识库",
    "资料库",
    "查找",
    "检索",
    "搜索",
    "网络",
    "网上",
    "相关的东西",
    "相关资料",
    "项目相关",
    "成功的",
    "成功案例",
    "依据",
]

FOLLOW_UP_MARKERS = ["那", "他", "她", "它", "其", "这个", "这份", "继续", "详细", "呢", "上述", "上面", "刚才", "然后"]


def contains_any(lowered: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in lowered for keyword in keywords)


def decision(
    selected_agent: SpecializedAgentName,
    display_name: str,
    reason: str,
    confidence: float,
) -> SupervisorDecision:
    return SupervisorDecision(
        selected_agent=selected_agent,
        display_name=display_name,
        reason=reason,
        confidence=confidence,
        handoff=f"handoff -> {display_name}",
    )


def is_mcp_request(message: str) -> bool:
    lowered = message.lower()
    explicit_mcp = contains_any(lowered, ["mcp", "调用工具", "使用工具", "用工具"])
    explicit_capability = contains_any(lowered, MCP_CAPABILITY_KEYWORDS)
    return explicit_mcp or explicit_capability


def is_system_stack_question(message: str) -> bool:
    lowered = message.lower()
    subject = contains_any(lowered, ["本系统", "本项目", "本博客", "博客系统", "这个项目", "技术栈"])
    stack = contains_any(lowered, ["技术栈", "使用了什么技术", "用了哪些技术", "系统架构"])
    return subject and stack


def select_mcp_tool_name(message: str) -> str:
    lowered = message.lower()
    if contains_any(
        lowered,
        ["现在几点", "几点了", "当前时间", "现在时间", "今天日期", "今天几号", "current time", "what time"],
    ):
        return "current_time"
    if contains_any(lowered, ["git", "仓库", "提交", "分支"]):
        return "git_repo_info"
    if contains_any(lowered, WEB_SEARCH_TOOL_KEYWORDS):
        return "web_search"
    if contains_any(lowered, ["数据库统计", "数据统计", "系统统计", "业务统计", "统计", "数量"]):
        return "safe_database_stats"
    return "local_file_search"


def routing_message(message: str, history: list[dict[str, str]]) -> str:
    """把上一轮用户问题拼进路由输入，使追问仍能继承实体。"""
    # Explicit review requests inspect the previous answer via structured
    # history; including the old question here can incorrectly route them to RAG.
    if contains_any(message.lower(), ["审查", "检查回答", "检查刚才", "核对回答", "核对引用", "review"]):
        return message
    is_follow_up = contains_any(message.lower(), FOLLOW_UP_MARKERS)
    if not is_follow_up or not history:
        return message
    previous_user_messages = [item.get("content", "") for item in history if item.get("role") == "user"]
    if not previous_user_messages:
        return message
    # A past tool request is not authorization to invoke a tool in this turn.
    if is_mcp_request(previous_user_messages[-1]):
        return message
    return f"上一问题：{previous_user_messages[-1]}\n当前追问：{message}"


def web_search_output_unusable(output: str) -> bool:
    return output.startswith("网页搜索失败：") or output.startswith("网页搜索没有返回可用结果。")


def decide(message: str) -> SupervisorDecision:
    """按安全优先级和业务关键词选择专用 Agent。"""
    lowered = message.lower()

    # Governance has priority over business routing. A request such as
    # "删除知识库" must never be consumed by the retrieval keyword below.
    if contains_any(lowered, ["审批", "发布审核", "删除", "敏感", "权限", "管理员", "admin"]):
        return decision(
            "admin_approval_agent",
            "Admin Approval Agent",
            "request needs governance or destructive-action review",
            0.88,
        )

    if is_mcp_request(message):
        return decision(
            "mcp_tool_agent",
            "MCP Tool Agent",
            "request maps to a registered MCP capability",
            0.94,
        )

    if is_system_stack_question(message):
        return decision(
            "blog_agent",
            "System Facts Agent",
            "system technology-stack facts require grounded blog retrieval",
            0.99,
        )

    # The authenticated chat can search private documents uploaded to the
    # current workspace. Resume requests must not be sent to the public-only
    # Blog Agent, otherwise an uploaded CV can never be retrieved.
    if contains_any(
        lowered,
        ["简历", "我的文档", "上传的文档", "上传的资料", "知识库文档", "附件"],
    ):
        return decision(
            "rag_agent",
            "Private Knowledge RAG Agent",
            "request targets an uploaded private workspace document",
            0.98,
        )

    if contains_any(
        lowered,
        ["哪个学校", "哪所学校", "什么学校", "毕业院校", "就读学校", "作者单位", "任职单位", "来自哪里"],
    ):
        return decision(
            "rag_agent",
            "Private Knowledge RAG Agent",
            "person affiliation question requires uploaded-document retrieval",
            0.96,
        )

    if contains_any(
        lowered,
        ["散射成像", "散射介质", "散斑相关", "散斑", "scattering imaging", "speckle correlation"],
    ):
        return decision(
            "rag_agent",
            "Private Knowledge RAG Agent",
            "technical topic matches bilingual uploaded-document retrieval",
            0.95,
        )

    compact_topic = re.sub(r"[\s，。？！,.!?]", "", lowered)
    if 2 <= len(compact_topic) <= 24 and any(term in compact_topic for term in TECHNICAL_TOPIC_SUFFIXES):
        return decision(
            "rag_agent",
            "Private Knowledge RAG Agent",
            "short technical topic handed to knowledge-capable agent",
            0.9,
        )

    if contains_any(lowered, RETRIEVAL_KEYWORDS):
        return decision(
            "rag_agent",
            "Private Knowledge RAG Agent",
            "request may need current workspace knowledge",
            0.91,
        )

    if contains_any(lowered, ["mcp", "tool", "工具", "git", "仓库", "本地文件", "文件搜索", "网页搜索"]):
        return decision(
            "mcp_tool_agent",
            "MCP Tool Agent",
            "request asks to use or inspect external tools",
            0.86,
        )

    if contains_any(lowered, ["检查", "审查", "review", "是否可靠", "有没有问题", "幻觉", "引用"]):
        return decision(
            "review_agent",
            "Review Agent",
            "request asks for answer quality, citation, or risk review",
            0.82,
        )

    if contains_any(lowered, ["统计", "多少", "数量", "访问量", "文章数", "文档数", "sql", "数据分析"]):
        return decision(
            "sql_analysis_agent",
            "SQL Analysis Agent",
            "request asks for safe platform statistics",
            0.86,
        )

    if contains_any(lowered, ["博客", "个人", "项目经历", "langgraph 项目", "关于我"]):
        return decision(
            "blog_agent",
            "Blog Agent",
            "request is about public blog, resume, or project experience",
            0.84,
        )

    if contains_any(lowered, ["写", "润色", "总结", "提纲", "标题", "摘要", "改写", "文案"]):
        return decision(
            "rag_agent",
            "Writing or Knowledge Agent",
            "writing request handed to inner direct-or-retrieve decision",
            0.78,
        )

    if re.search(r"\d+\s*[\+\-\*/%]\s*\d+", message) or contains_any(
        lowered,
        ["知识库", "rag", "检索", "搜索", "文档", "readme", "mcp", "当前用户", "profile"],
    ):
        return decision(
            "rag_agent",
            "RAG Agent",
            "request needs tools, retrieval, or project knowledge",
            0.9,
        )

    return decision(
        "rag_agent",
        "General or Knowledge Agent",
        "inner query analyzer chooses direct answer or workspace retrieval",
        0.62,
    )
