from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from .tools import SafeCalculator, ToolResult, build_langchain_tools, search_local_blog


@dataclass(frozen=True)
class AgentResponse:
    answer: str
    tool_calls: list[ToolResult]
    trace: list[str]

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "tool_calls": [asdict(call) for call in self.tool_calls],
            "trace": self.trace,
        }


class SimpleToolCallingAgent:
    """LangChain LCEL chain based day-2 agent loop.

    Flow:
    user input -> prompt | GPT-4o mini with tools -> execute tool calls
    -> messages | GPT-4o mini -> final answer.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.tools = build_langchain_tools(project_root)
        self.tools_by_name: dict[str, BaseTool] = {item.name: item for item in self.tools}
        self.llm = self._build_llm()

    def chat(self, message: str) -> AgentResponse:
        message = message.strip()
        trace = ["收到用户输入", "构建 LangChain LCEL chain"]

        try:
            return self._chat_with_langchain(message, trace)
        except Exception as exc:
            fallback = self._fallback_chat(message)
            return AgentResponse(
                answer=f"LangChain 模型调用失败，已使用本地兜底工具回答：\n{fallback.answer}",
                tool_calls=fallback.tool_calls,
                trace=[*trace, f"模型调用异常：{exc}", "使用本地兜底工具"],
            )

    def _build_llm(self) -> ChatOpenAI | None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None

        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=api_key,
            base_url=os.getenv("OPENAI_BASE_URL", "https://poloai.top/v1/"),
            temperature=0,
        )

    def _chat_with_langchain(self, message: str, trace: list[str]) -> AgentResponse:
        if self.llm is None:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        tool_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "你是企业知识智能体平台的助手。"
                        "如果问题可以直接回答，就直接回答；"
                        "只有当需要项目资料、用户资料或计算时才调用工具。"
                        "可用工具：blog_search 用于搜索博客和项目文档；"
                        "current_user_profile 用于获取当前用户资料；"
                        "calculator 用于数学计算。"
                        "最终回答使用中文，并简洁说明是否调用了工具。"
                    ),
                ),
                ("human", "{message}"),
            ]
        )
        tool_chain = tool_prompt | self.llm.bind_tools(self.tools)

        prompt_value = tool_prompt.invoke({"message": message})
        messages = prompt_value.to_messages()
        ai_message = tool_chain.invoke({"message": message})
        tool_calls: list[ToolResult] = []

        if not ai_message.tool_calls:
            trace.append("chain 未请求工具，直接返回模型回答")
            return AgentResponse(
                answer=str(ai_message.content),
                tool_calls=tool_calls,
                trace=trace,
            )

        messages.append(ai_message)
        for call in ai_message.tool_calls:
            tool_name = call["name"]
            args = call.get("args", {})
            tool_input = self._stringify_tool_args(args)
            selected_tool = self.tools_by_name[tool_name]
            output = selected_tool.invoke(args)
            tool_calls.append(ToolResult(tool_name, tool_input, str(output)))
            messages.append(ToolMessage(content=str(output), tool_call_id=call["id"]))
            trace.append(f"chain 调用工具：{tool_name}")

        final_prompt = ChatPromptTemplate.from_messages([MessagesPlaceholder("messages")])
        final_chain = final_prompt | self.llm
        final_message = final_chain.invoke({"messages": messages})
        trace.append("chain 基于工具结果生成最终回答")

        return AgentResponse(
            answer=str(final_message.content),
            tool_calls=tool_calls,
            trace=trace,
        )

    def _stringify_tool_args(self, args: dict) -> str:
        if not args:
            return ""
        if len(args) == 1:
            return str(next(iter(args.values())))
        return str(args)

    def _fallback_chat(self, message: str) -> AgentResponse:
        if re.search(r"\d+\s*[\+\-\*/%]\s*\d+", message):
            expression = re.search(r"[\d\s\+\-\*/%\.\(\)]+", message)
            value = expression.group(0).strip() if expression else message
            output = SafeCalculator().run(value)
            return AgentResponse(
                answer=f"我调用了计算器工具，结果是：{output}",
                tool_calls=[ToolResult("calculator", value, output)],
                trace=["本地兜底：calculator"],
            )

        if any(keyword in message.lower() for keyword in ["我是谁", "当前用户", "用户资料", "我的项目", "profile"]):
            output = (
                "当前用户正在构建企业知识智能体平台 + 个人博客智能体系统；"
                "技术路线是 Vue 3 + Django + LangChain/LangGraph + RAG + MCP。"
            )
            return AgentResponse(
                answer=f"我读取了当前用户资料：{output}",
                tool_calls=[ToolResult("current_user_profile", message, output)],
                trace=["本地兜底：current_user_profile"],
            )

        output = search_local_blog(self.project_root, message)
        return AgentResponse(
            answer=f"我检索了本地项目文档，找到这些线索：\n{output}",
            tool_calls=[ToolResult("blog_search", message, output)],
            trace=["本地兜底：blog_search"],
        )

