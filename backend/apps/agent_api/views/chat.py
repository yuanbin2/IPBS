"""Chat execution, live SSE body chunks, and durable run results."""

import json
import logging
import time
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.model_accounting import collect_model_calls
from agent.multi_agent import MultiAgentSupervisor
from agent.security import detect_sensitive_input
from agent.telemetry import collect_stages, correlate, emit, stage_summary

from ..exceptions import ErrorCode
from ..models import AgentRun, ApprovalRequest, SecurityAuditEvent, UserProfile
from ..serializers import serialize_agent_observation, serialize_approval_request, serialize_conversation
from .chat_runs import (
    RunConflict,
    claim_run,
    fail_run,
    finish_run,
    get_owned_run,
    request_cancellation,
    serialize_run,
    start_run,
)
from .common import (
    audit_security_event,
    error_response,
    get_conversation_owner,
    get_workspace_key,
    maybe_create_blog_delete_approval,
    maybe_create_mcp_approval,
    require_roles,
)


class _ApprovalCancelled(Exception):
    pass


_logger = logging.getLogger(__name__)


def _timings(run, stages, calls, total_ms):
    queue_wait = round(((run.started_at or run.created_at) - run.created_at).total_seconds() * 1000)
    return stage_summary(stages, calls, queue_wait_ms=queue_wait, total_ms=total_ms)


def _attach_accounting(response_data, collector, *, stages, run, total_ms):
    summary = collector.summary()
    legacy_usage = response_data.get("token_usage") or {}
    if not collector.calls and any(isinstance(value, int) and value > 0 for value in legacy_usage.values()):
        # A non-LangChain or external model supplied usage without a callback.
        # Keep its tokens, but do not claim that this request has a complete price.
        summary["unobserved_model_calls"] = True
        summary["unknown_cost_calls"] = 1
        summary["complete_cost"] = False
    response_data["model_calls"] = collector.calls
    response_data["model_accounting"] = summary
    response_data["stage_timings"] = _timings(run, stages, collector.calls, total_ms)
    with correlate(request_id=run.request_id, run_id=run.run_id):
        emit(
            "chat_stages",
            status="succeeded",
            duration_ms=total_ms,
            queue_wait_ms=response_data["stage_timings"]["queue_wait_ms"],
            retrieval_ms=response_data["stage_timings"]["retrieval_ms"],
            model_ms=response_data["stage_timings"]["model_ms"],
            count=len(collector.calls),
        )
    if collector.calls:
        response_data["token_usage"] = summary["token_usage"]
    _logger.info(
        "model_accounting run_id=%s calls=%s failed=%s unknown_usage=%s unknown_cost=%s price_version=%s",
        summary["run_id"],
        summary["call_count"],
        summary["failed_calls"],
        summary["unknown_usage_calls"],
        summary["unknown_cost_calls"],
        summary["price_version"],
    )


def _prepare(request):
    denied = require_roles(request, [UserProfile.Role.OPERATOR])
    if denied:
        return None, denied
    message = str(request.data.get("message", "")).strip()
    if not message:
        return None, error_response("message is required", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)
    workspace_key = get_workspace_key(request)
    try:
        run, history, created = claim_run(request, message, workspace_key, get_conversation_owner(request))
    except ValueError as exc:
        return None, error_response(str(exc), ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST)
    except RunConflict:
        return None, error_response("run_id 已用于其他请求", ErrorCode.CONFLICT, status.HTTP_409_CONFLICT)

    if created:
        sensitive_marker = detect_sensitive_input(message)
        if sensitive_marker:
            audit_security_event(
                request,
                SecurityAuditEvent.EventType.SENSITIVE_INPUT,
                "chat input matched security filter",
                {"pattern": sensitive_marker},
            )
    return (run, history, created, message, workspace_key), None


def _approval_response_data(message, approval):
    is_mcp_approval = approval.action == ApprovalRequest.Action.EXECUTE_MCP_TOOL
    return {
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
        "approval_required": True,
        "approval": serialize_approval_request(approval),
    }


def _execute(request, run, history, message, workspace_key):
    """Commit the synchronous answer before returning to the client."""
    if not start_run(run):
        return None
    started_at = time.perf_counter()
    collector = None
    stages = []
    try:
        with transaction.atomic():
            approval = maybe_create_blog_delete_approval(message, request) or maybe_create_mcp_approval(
                message, request
            )
            if approval:
                response_data = _approval_response_data(message, approval)
                response_data.update(run_id=str(run.run_id), status=AgentRun.Status.SUCCEEDED)
                response_data["request_id"] = run.request_id
                response_data["latency_ms"] = round((time.perf_counter() - started_at) * 1000)
                if finish_run(run, response_data, response_data["latency_ms"]):
                    return None
                raise _ApprovalCancelled

        with (
            correlate(request_id=run.request_id, run_id=run.run_id),
            collect_stages() as stages,
            collect_model_calls(run.run_id) as collector,
        ):
            agent = MultiAgentSupervisor(Path(settings.BASE_DIR).parent, workspace_key=workspace_key)
            response = agent.chat(
                message,
                internet_enabled=bool(request.data.get("internet_enabled", False)),
                history=history,
            )
        response_data = response.to_dict()
        _attach_accounting(
            response_data,
            collector,
            stages=stages,
            run=run,
            total_ms=round((time.perf_counter() - started_at) * 1000),
        )

        response_data.update(
            run_id=str(run.run_id),
            request_id=run.request_id,
            status=AgentRun.Status.SUCCEEDED,
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )
        finish_run(run, response_data, response_data["latency_ms"])
        return None
    except _ApprovalCancelled:
        fail_run(
            run,
            "cancelled",
            model_calls=collector.calls if collector else [],
            model_accounting=collector.summary() if collector else {},
            stage_timings=_timings(
                run, stages, collector.calls if collector else [], round((time.perf_counter() - started_at) * 1000)
            ),
        )
        return None
    except Exception as exc:
        fail_run(
            run,
            type(exc).__name__,
            round((time.perf_counter() - started_at) * 1000),
            model_calls=collector.calls if collector else [],
            model_accounting=collector.summary() if collector else {},
            stage_timings=_timings(
                run, stages, collector.calls if collector else [], round((time.perf_counter() - started_at) * 1000)
            ),
        )
        return type(exc).__name__


def _response_payload(run):
    observation = run.observations.order_by("-id").first()
    return {
        **(serialize_run(run)["result"] or {}),
        "run_id": str(run.run_id),
        "request_id": run.request_id,
        "status": run.status,
        "conversation": serialize_conversation(run.conversation),
        "observation": serialize_agent_observation(observation) if observation else None,
    }


def _stream_run(request, run, history, message, workspace_key):
    with (
        correlate(request_id=run.request_id, run_id=run.run_id),
        collect_stages() as stages,
        collect_model_calls(run.run_id) as collector,
    ):
        yield from _stream_run_accounted(request, run, history, message, workspace_key, collector, stages)


def _stream_run_accounted(request, run, history, message, workspace_key, collector, stages):
    """Execute while yielding progress; closing the HTTP iterator drains this run."""
    if not start_run(run):
        yield {"type": "run", "run_id": str(run.run_id), "status": run.status}
        yield {"type": "done", "run_id": str(run.run_id), "status": run.status, "conversation_id": run.conversation_id}
        return

    started_at = time.perf_counter()
    first_body_ms = None
    assembled_body = ""
    yield {"type": "run", "run_id": str(run.run_id), "request_id": run.request_id, "status": run.status}
    try:
        approval_data = None
        with transaction.atomic():
            approval = maybe_create_blog_delete_approval(message, request) or maybe_create_mcp_approval(
                message, request
            )
            if approval:
                approval_data = _approval_response_data(message, approval)
                approval_data.update(
                    run_id=str(run.run_id),
                    request_id=run.request_id,
                    status=AgentRun.Status.SUCCEEDED,
                    latency_ms=round((time.perf_counter() - started_at) * 1000),
                    first_body_ms=None,
                )
                if not finish_run(run, approval_data, approval_data["latency_ms"]):
                    raise _ApprovalCancelled

        if approval_data is not None:
            yield {"type": "progress", "detail": "审批请求已保存"}
            yield {"type": "response", **approval_data}
        else:
            agent = MultiAgentSupervisor(Path(settings.BASE_DIR).parent, workspace_key=workspace_key)
            response_data = None
            agent_events = agent.chat_stream(
                message,
                internet_enabled=bool(request.data.get("internet_enabled", False)),
                history=history,
            )
            last_cancel_check = last_heartbeat = time.monotonic()
            try:
                for event in agent_events:
                    event_type = event.get("type")
                    if event_type == "response":
                        response_data = {key: value for key, value in event.items() if key != "type"}
                    elif event_type == "error":
                        raise RuntimeError("agent_stream_error")
                    elif event_type == "trace":
                        yield {"type": "progress", "detail": event.get("data", "")}
                    elif event_type == "answer_delta":
                        text = event.get("text", "")
                        if text:
                            assembled_body += text
                            if first_body_ms is None:
                                first_body_ms = round((time.perf_counter() - started_at) * 1000)
                            yield {"type": "answer_delta", "text": text}
                    elif event_type == "answer_snapshot":
                        assembled_body = event.get("text", "")
                        if first_body_ms is None:
                            first_body_ms = round((time.perf_counter() - started_at) * 1000)
                        yield {"type": "answer_snapshot", "text": assembled_body}

                    now = time.monotonic()
                    if now - last_heartbeat >= 30:
                        AgentRun.objects.filter(pk=run.pk, status=AgentRun.Status.RUNNING).update(
                            updated_at=timezone.now()
                        )
                        last_heartbeat = now
                    if now - last_cancel_check >= 0.25:
                        run.refresh_from_db(fields=["cancel_requested", "status"])
                        if run.cancel_requested or run.status != AgentRun.Status.RUNNING:
                            break
                        last_cancel_check = now
            except Exception:
                if response_data is None:
                    raise
            finally:
                close_events = getattr(agent_events, "close", None)
                if close_events:
                    try:
                        close_events()
                    except Exception:
                        if response_data is None:
                            raise

            if response_data is None:
                run.refresh_from_db(fields=["cancel_requested", "status"])
                if run.cancel_requested:
                    raise _ApprovalCancelled
                raise RuntimeError("agent_stream_without_response")

            final_answer = str(response_data.get("answer", ""))
            if first_body_ms is not None and assembled_body != final_answer:
                if final_answer.startswith(assembled_body):
                    tail = final_answer[len(assembled_body) :]
                    if tail:
                        yield {"type": "answer_delta", "text": tail}
                else:
                    yield {"type": "answer_snapshot", "text": final_answer}
            elif first_body_ms is None:
                yield {"type": "progress", "detail": "此路径不提供生成期正文增量，显示最终回答"}

            response_data.update(
                run_id=str(run.run_id),
                request_id=run.request_id,
                status=AgentRun.Status.SUCCEEDED,
                first_body_ms=first_body_ms,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
            )
            _attach_accounting(response_data, collector, stages=stages, run=run, total_ms=response_data["latency_ms"])
            if finish_run(run, response_data, response_data["latency_ms"]):
                yield {"type": "response", **response_data}
    except _ApprovalCancelled:
        fail_run(
            run,
            "cancelled",
            model_calls=collector.calls,
            model_accounting=collector.summary(),
            stage_timings=_timings(run, stages, collector.calls, round((time.perf_counter() - started_at) * 1000)),
        )
    except Exception as exc:
        fail_run(
            run,
            type(exc).__name__,
            round((time.perf_counter() - started_at) * 1000),
            model_calls=collector.calls,
            model_accounting=collector.summary(),
            stage_timings=_timings(run, stages, collector.calls, round((time.perf_counter() - started_at) * 1000)),
        )
        yield {"type": "error", "run_id": str(run.run_id), "detail": "问答执行失败", "code": type(exc).__name__}
    yield {"type": "done", "run_id": str(run.run_id), "status": run.status, "conversation_id": run.conversation_id}


class _SSEEvents:
    """Drain the model and persist its result when a client stops receiving."""

    def __init__(self, frames):
        self.frames = iter(frames)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        try:
            frame = next(self.frames)
        except StopIteration:
            self.closed = True
            raise
        return f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"

    def close(self):
        if self.closed:
            return
        try:
            for _ in self:
                pass
        finally:
            self.closed = True
            close_frames = getattr(self.frames, "close", None)
            if close_frames:
                close_frames()


def _sse_response(run, events):
    response = StreamingHttpResponse(
        _SSEEvents(events),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    response["X-Agent-Run-ID"] = str(run.run_id)
    return response


class AgentChatView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        prepared, error = _prepare(request)
        if error:
            return error
        run, history, created, message, workspace_key = prepared
        if created:
            execution_error = _execute(request, run, history, message, workspace_key)
            if execution_error:
                result = error_response(
                    "问答执行失败，请按 run_id 查询状态",
                    ErrorCode.UPSTREAM_UNAVAILABLE if execution_error == "TimeoutError" else ErrorCode.INTERNAL_ERROR,
                    (
                        status.HTTP_503_SERVICE_UNAVAILABLE
                        if execution_error == "TimeoutError"
                        else status.HTTP_500_INTERNAL_SERVER_ERROR
                    ),
                    run_id=str(run.run_id),
                    run_status=run.status,
                    error_code=execution_error,
                )
                result["X-Agent-Run-ID"] = str(run.run_id)
                return result
        if run.status == AgentRun.Status.SUCCEEDED:
            result = Response(
                _response_payload(run),
                status=status.HTTP_202_ACCEPTED if (run.result or {}).get("approval_required") else status.HTTP_200_OK,
            )
        else:
            result = Response(
                serialize_run(run),
                status=(
                    status.HTTP_202_ACCEPTED
                    if run.status in {AgentRun.Status.PENDING, AgentRun.Status.RUNNING}
                    else status.HTTP_200_OK
                ),
            )
        result["X-Agent-Run-ID"] = str(run.run_id)
        return result


class AgentChatStreamView(APIView):
    """SSE response streams model text and finalizes even when delivery stops."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        prepared, error = _prepare(request)
        if error:
            return error
        run, history, created, message, workspace_key = prepared
        if created:
            events = _stream_run(request, run, history, message, workspace_key)
        elif run.status == AgentRun.Status.SUCCEEDED:
            stored_result = serialize_run(run)["result"] or {}
            events = [
                {"type": "run", "run_id": str(run.run_id), "status": run.status},
                *({"type": "progress", "detail": item} for item in stored_result.get("trace", [])),
                {"type": "response", **stored_result},
                {
                    "type": "done",
                    "run_id": str(run.run_id),
                    "status": run.status,
                    "conversation_id": run.conversation_id,
                },
            ]
        else:
            return error_response(
                "该 run_id 已存在；请查询运行状态，不会重复执行",
                ErrorCode.CONFLICT,
                status.HTTP_409_CONFLICT,
                **serialize_run(run),
            )
        return _sse_response(run, events)


class AgentChatRunView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, run_id):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        run = get_owned_run(run_id, get_workspace_key(request), get_conversation_owner(request))
        return Response(serialize_run(run))


class AgentChatRunCancelView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, run_id):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        run = get_owned_run(run_id, get_workspace_key(request), get_conversation_owner(request))
        request_cancellation(run)
        return Response(serialize_run(run))
