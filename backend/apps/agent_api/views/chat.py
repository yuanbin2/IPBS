"""聊天执行：非流式与 SSE 流式对话（路由/工具/RAG 由 MultiAgentSupervisor 编排）。"""

import json
import time
from pathlib import Path

from django.conf import settings
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.multi_agent import MultiAgentSupervisor
from agent.security import detect_sensitive_input

from ..exceptions import ErrorCode
from ..models import AgentRun, ApprovalRequest, Message, SecurityAuditEvent
from ..serializers import serialize_agent_observation, serialize_approval_request, serialize_conversation
from .common import (
    audit_security_event,
    create_agent_observation,
    error_response,
    get_conversation_owner,
    get_or_create_conversation,
    get_workspace_key,
    maybe_create_blog_delete_approval,
    maybe_create_mcp_approval,
)


class AgentChatView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        message = str(request.data.get("message", "")).strip()
        if not message:
            return error_response("message is required", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)
        workspace_key = get_workspace_key(request)
        sensitive_marker = detect_sensitive_input(message)
        if sensitive_marker:
            audit_security_event(
                request,
                SecurityAuditEvent.EventType.SENSITIVE_INPUT,
                "chat input matched security filter",
                {"pattern": sensitive_marker},
            )

        # 会话同时按 workspace 和 owner 隔离，conversation_id 不能跨用户复用。
        conversation = get_or_create_conversation(
            request.data.get("conversation_id"),
            message,
            workspace_key,
            get_conversation_owner(request),
        )
        # 只把最近十条消息送入 Agent，既保留追问上下文，也控制 prompt 长度。
        history = [
            {"role": item.role, "content": item.content} for item in conversation.messages.order_by("-id")[:10][::-1]
        ]
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.USER,
            content=message,
        )

        # 高风险动作在调用 Supervisor 前转成审批单；当前 HTTP 请求只返回
        # 202，不直接执行删除或受控 MCP 工具。
        approval = maybe_create_blog_delete_approval(message, request) or maybe_create_mcp_approval(message, request)
        if approval:
            is_mcp_approval = approval.action == ApprovalRequest.Action.EXECUTE_MCP_TOOL
            response_data = {
                "answer": (
                    f"工具调用已进入人工审批 #{approval.id}：{approval.payload.get('tool_name')}"
                    if is_mcp_approval
                    else f"已为文章删除创建审批单 #{approval.id}。管理员批准后才会删除：{approval.payload.get('title')}"
                ),
                "tool_calls": [
                    {
                        "name": "mcp_approval" if is_mcp_approval else "admin_approval",
                        "input": message,
                        "output": f"approval_id={approval.id}; action={approval.action}",
                    }
                ],
                "sources": [],
                "trace": [
                    "supervisor -> received request",
                    "supervisor -> admin_approval_agent (blog deletion requires approval)",
                    "admin_approval_agent -> approval request created",
                ],
                "route": "admin_approval_agent",
                "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "supervisor": {
                    "selected_agent": "admin_approval_agent",
                    "display_name": "Admin Approval Agent",
                    "reason": "blog deletion requires human approval",
                    "confidence": 0.98,
                    "handoff": "handoff -> Admin Approval Agent",
                },
            }
            Message.objects.create(
                conversation=conversation,
                role=Message.Role.AGENT,
                content=response_data["answer"],
                tool_calls=response_data["tool_calls"],
                sources=response_data["sources"],
                trace=response_data["trace"],
                token_usage=response_data["token_usage"],
            )
            agent_run = AgentRun.objects.create(
                conversation=conversation,
                workspace_key=workspace_key,
                input_message=message,
                route=response_data["route"],
                tool_calls=response_data["tool_calls"],
                sources=response_data["sources"],
                trace=response_data["trace"],
                token_usage=response_data["token_usage"],
            )
            observation = create_agent_observation(
                conversation=conversation,
                agent_run=agent_run,
                input_message=message,
                workspace_key=workspace_key,
                response_data=response_data,
            )
            conversation.save(update_fields=["updated_at"])
            return Response(
                {
                    **response_data,
                    "approval_required": True,
                    "approval": serialize_approval_request(approval),
                    "conversation": serialize_conversation(conversation),
                    "observation": serialize_agent_observation(observation),
                },
                status=status.HTTP_202_ACCEPTED,
            )

        # REST 层只负责生命周期和持久化，真正的路由/工具/RAG 逻辑由
        # MultiAgentSupervisor 统一编排。
        project_root = Path(settings.BASE_DIR).parent
        started_at = time.perf_counter()
        try:
            agent = MultiAgentSupervisor(project_root, workspace_key=workspace_key)
            response = agent.chat(
                message,
                internet_enabled=bool(request.data.get("internet_enabled", False)),
                history=history,
            )
            response_data = response.to_dict()
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started_at) * 1000)
            create_agent_observation(
                conversation=conversation,
                agent_run=None,
                input_message=message,
                workspace_key=workspace_key,
                latency_ms=latency_ms,
                failure_reason=str(exc),
            )
            raise

        # 将最终回答、工具轨迹、来源和 token 使用量一起保存，前端历史回放
        # 与可观测性页面因此不需要再次运行 Agent。
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.AGENT,
            content=response.answer,
            tool_calls=response_data["tool_calls"],
            sources=response_data["sources"],
            trace=response.trace,
            token_usage=response.token_usage,
        )
        agent_run = AgentRun.objects.create(
            conversation=conversation,
            workspace_key=workspace_key,
            input_message=message,
            route=response.route,
            tool_calls=response_data["tool_calls"],
            sources=response_data["sources"],
            trace=response.trace,
            token_usage=response.token_usage,
        )
        observation = create_agent_observation(
            conversation=conversation,
            agent_run=agent_run,
            input_message=message,
            workspace_key=workspace_key,
            response_data=response_data,
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )
        if any(item == "security_filter -> output redacted" for item in response.trace):
            audit_security_event(request, SecurityAuditEvent.EventType.OUTPUT_REDACTED, "agent output redacted")

        conversation.save(update_fields=["updated_at"])
        return Response(
            {
                **response_data,
                "conversation": serialize_conversation(conversation),
                "observation": serialize_agent_observation(observation),
            }
        )


class AgentChatStreamView(APIView):
    """SSE streaming endpoint that yields thinking steps and the final answer."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        message = str(request.data.get("message", "")).strip()
        if not message:
            return error_response("message is required", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)

        workspace_key = get_workspace_key(request)
        sensitive_marker = detect_sensitive_input(message)
        if sensitive_marker:
            audit_security_event(
                request,
                SecurityAuditEvent.EventType.SENSITIVE_INPUT,
                "chat input matched security filter",
                {"pattern": sensitive_marker},
            )

        conversation = get_or_create_conversation(
            request.data.get("conversation_id"),
            message,
            workspace_key,
            get_conversation_owner(request),
        )
        history = [
            {"role": item.role, "content": item.content} for item in conversation.messages.order_by("-id")[:10][::-1]
        ]
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.USER,
            content=message,
        )

        # Check for approval
        approval = maybe_create_blog_delete_approval(message, request) or maybe_create_mcp_approval(message, request)
        if approval:
            is_mcp_approval = approval.action == ApprovalRequest.Action.EXECUTE_MCP_TOOL
            response_data = {
                "answer": (
                    f"工具调用已进入人工审批 #{approval.id}：{approval.payload.get('tool_name')}"
                    if is_mcp_approval
                    else f"已为文章删除创建审批单 #{approval.id}。管理员批准后才会删除：{approval.payload.get('title')}"
                ),
                "tool_calls": [
                    {
                        "name": "mcp_approval" if is_mcp_approval else "admin_approval",
                        "input": message,
                        "output": f"approval_id={approval.id}; action={approval.action}",
                    }
                ],
                "sources": [],
                "trace": [
                    "supervisor -> received request",
                    "supervisor -> admin_approval_agent (blog deletion requires approval)",
                    "admin_approval_agent -> approval request created",
                ],
                "route": "admin_approval_agent",
                "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "supervisor": {
                    "selected_agent": "admin_approval_agent",
                    "display_name": "Admin Approval Agent",
                    "reason": "blog deletion requires human approval",
                    "confidence": 0.98,
                    "handoff": "handoff -> Admin Approval Agent",
                },
            }

            def approval_stream():
                yield f"data: {json.dumps({'type': 'response', **response_data}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'conversation_id': conversation.id}, ensure_ascii=False)}\n\n"

            Message.objects.create(
                conversation=conversation,
                role=Message.Role.AGENT,
                content=response_data["answer"],
                tool_calls=response_data["tool_calls"],
                sources=response_data["sources"],
                trace=response_data["trace"],
                token_usage=response_data["token_usage"],
            )
            conversation.save(update_fields=["updated_at"])

            response = StreamingHttpResponse(approval_stream(), content_type="text/event-stream")
            response["Cache-Control"] = "no-cache"
            response["X-Accel-Buffering"] = "no"
            return response

        # SSE generator for normal chat
        def event_stream():
            project_root = Path(settings.BASE_DIR).parent
            started_at = time.perf_counter()
            agent = MultiAgentSupervisor(project_root, workspace_key=workspace_key)
            collected_response = {}

            try:
                for event in agent.chat_stream(
                    message,
                    internet_enabled=bool(request.data.get("internet_enabled", False)),
                    history=history,
                ):
                    if event["type"] == "response":
                        collected_response = event
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)}, ensure_ascii=False)}\n\n"

            # Persist after streaming completes
            if collected_response:
                Message.objects.create(
                    conversation=conversation,
                    role=Message.Role.AGENT,
                    content=collected_response.get("answer", ""),
                    tool_calls=collected_response.get("tool_calls", []),
                    sources=collected_response.get("sources", []),
                    trace=collected_response.get("trace", []),
                    token_usage=collected_response.get("token_usage", {}),
                )
                agent_run = AgentRun.objects.create(
                    conversation=conversation,
                    workspace_key=workspace_key,
                    input_message=message,
                    route=collected_response.get("route", ""),
                    tool_calls=collected_response.get("tool_calls", []),
                    sources=collected_response.get("sources", []),
                    trace=collected_response.get("trace", []),
                    token_usage=collected_response.get("token_usage", {}),
                )
                create_agent_observation(
                    conversation=conversation,
                    agent_run=agent_run,
                    input_message=message,
                    workspace_key=workspace_key,
                    response_data=collected_response,
                    latency_ms=round((time.perf_counter() - started_at) * 1000),
                )
                conversation.save(update_fields=["updated_at"])

                # Send done event with conversation_id
                yield f"data: {json.dumps({'type': 'done', 'conversation_id': conversation.id}, ensure_ascii=False)}\n\n"

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
