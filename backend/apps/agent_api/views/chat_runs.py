"""Chat run persistence shared by the ordinary and SSE endpoints."""

import hashlib
import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from agent.telemetry import correlate, current_request_id, emit, failure_alert

from ..models import AgentRun, Message
from .common import create_agent_observation, get_or_create_conversation


class RunConflict(Exception):
    """A run ID was reused with different request contents."""


def parse_run_id(raw):
    if raw in (None, ""):
        return uuid.uuid4()
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("run_id must be a UUID") from exc


def request_fingerprint(message, conversation_id, internet_enabled, project_id):
    payload = {
        "message": message,
        "conversation_id": str(conversation_id or ""),
        "internet_enabled": bool(internet_enabled),
        "project_id": str(project_id or ""),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _owned_run(run_id, workspace_key, owner_username):
    run = AgentRun.objects.select_related("conversation").filter(run_id=run_id).first()
    if run is None:
        return None
    if run.workspace_key != workspace_key or run.conversation.owner_username != owner_username:
        raise Http404
    return run


def get_owned_run(run_id, workspace_key, owner_username):
    run = _owned_run(run_id, workspace_key, owner_username)
    if run is None:
        raise Http404
    reconcile_stale_run(run)
    return run


def claim_run(request, message, workspace_key, owner_username):
    """Create the user message and run in one transaction, or reuse one exact request."""
    run_id = parse_run_id(request.data.get("run_id"))
    fingerprint = request_fingerprint(
        message,
        request.data.get("conversation_id"),
        request.data.get("internet_enabled", False),
        request.data.get("project_id"),
    )
    existing = _owned_run(run_id, workspace_key, owner_username)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise RunConflict
        reconcile_stale_run(existing)
        with correlate(request_id=current_request_id(request), run_id=existing.run_id):
            emit("run_reused", status=existing.status)
        return existing, [], False

    try:
        with transaction.atomic():
            conversation = get_or_create_conversation(
                request.data.get("conversation_id"),
                message,
                workspace_key,
                owner_username,
                project_id=request.data.get("project_id"),
            )
            history = [
                {"role": item.role, "content": item.content, "sources": item.sources}
                for item in conversation.messages.order_by("-id")[:10][::-1]
            ]
            run = AgentRun.objects.create(
                run_id=run_id,
                request_id=current_request_id(request),
                conversation=conversation,
                workspace_key=workspace_key,
                input_message=message,
                request_fingerprint=fingerprint,
                status=AgentRun.Status.PENDING,
            )
            Message.objects.create(conversation=conversation, agent_run=run, role=Message.Role.USER, content=message)
            return run, history, True
    except IntegrityError:
        # A concurrent request claimed the same UUID. The transaction above
        # rolled back its conversation and message before we inspect the winner.
        existing = _owned_run(run_id, workspace_key, owner_username)
        if existing is None:
            raise
        if existing.request_fingerprint != fingerprint:
            raise RunConflict from None
        reconcile_stale_run(existing)
        with correlate(request_id=current_request_id(request), run_id=existing.run_id):
            emit("run_reused", status=existing.status)
        return existing, [], False


def start_run(run):
    now = timezone.now()
    changed = AgentRun.objects.filter(pk=run.pk, status=AgentRun.Status.PENDING, cancel_requested=False).update(
        status=AgentRun.Status.RUNNING, started_at=now, updated_at=now
    )
    run.refresh_from_db()
    return bool(changed)


def finish_run(run, response_data, latency_ms):
    """Commit status, assistant message, and observation together before any response bytes."""
    now = timezone.now()
    with transaction.atomic():
        changed = AgentRun.objects.filter(pk=run.pk, status=AgentRun.Status.RUNNING, cancel_requested=False).update(
            status=AgentRun.Status.SUCCEEDED,
            result=response_data,
            route=response_data.get("route", ""),
            tool_calls=response_data.get("tool_calls", []),
            sources=response_data.get("sources", []),
            trace=response_data.get("trace", []),
            token_usage=response_data.get("token_usage", {}),
            model_calls=response_data.get("model_calls", []),
            model_accounting=response_data.get("model_accounting", {}),
            stage_timings=response_data.get("stage_timings", {}),
            finished_at=now,
            updated_at=now,
        )
        if not changed:
            run.refresh_from_db()
            if run.status == AgentRun.Status.RUNNING and run.cancel_requested:
                AgentRun.objects.filter(pk=run.pk, status=AgentRun.Status.RUNNING).update(
                    status=AgentRun.Status.CANCELLED,
                    model_calls=response_data.get("model_calls", []),
                    model_accounting=response_data.get("model_accounting", {}),
                    stage_timings=response_data.get("stage_timings", {}),
                    finished_at=now,
                    updated_at=now,
                )
                run.refresh_from_db()
            return False
        Message.objects.create(
            conversation=run.conversation,
            agent_run=run,
            role=Message.Role.AGENT,
            content=str(response_data.get("answer", "")),
            tool_calls=response_data.get("tool_calls", []),
            sources=response_data.get("sources", []),
            trace=response_data.get("trace", []),
            token_usage=response_data.get("token_usage", {}),
        )
        create_agent_observation(
            conversation=run.conversation,
            agent_run=run,
            input_message=run.input_message,
            workspace_key=run.workspace_key,
            response_data=response_data,
            latency_ms=latency_ms,
        )
        run.conversation.save(update_fields=["updated_at"])
    run.refresh_from_db()
    return True


def fail_run(
    run, error_code, latency_ms=0, *, stale_before=None, model_calls=None, model_accounting=None, stage_timings=None
):
    """Keep a queryable failure even when no assistant message was produced."""
    now = timezone.now()
    alert = False
    with transaction.atomic():
        for _ in range(2):
            current = AgentRun.objects.get(pk=run.pk)
            if current.status not in {AgentRun.Status.PENDING, AgentRun.Status.RUNNING}:
                break
            new_status = AgentRun.Status.CANCELLED if current.cancel_requested else AgentRun.Status.FAILED
            candidates = AgentRun.objects.filter(
                pk=run.pk, status=current.status, cancel_requested=current.cancel_requested
            )
            if stale_before is not None:
                candidates = candidates.filter(updated_at__lt=stale_before)
            changed = candidates.update(
                status=new_status,
                error_code="" if new_status == AgentRun.Status.CANCELLED else error_code[:80],
                finished_at=now,
                updated_at=now,
                model_calls=model_calls if model_calls is not None else current.model_calls,
                model_accounting=model_accounting if model_accounting is not None else current.model_accounting,
                stage_timings=stage_timings if stage_timings is not None else current.stage_timings,
            )
            if changed:
                if new_status == AgentRun.Status.FAILED:
                    alert = True
                    create_agent_observation(
                        conversation=run.conversation,
                        agent_run=run,
                        input_message=run.input_message,
                        workspace_key=run.workspace_key,
                        latency_ms=latency_ms,
                        failure_reason=error_code[:80],
                    )
                break
    if alert:
        transaction.on_commit(
            lambda: failure_alert("chat_run_failed", error_code, request_id=run.request_id, run_id=str(run.run_id))
        )
    run.refresh_from_db()


def request_cancellation(run):
    """Pending work is cancelled; running model calls stop only at the next boundary."""
    now = timezone.now()
    AgentRun.objects.filter(pk=run.pk, status=AgentRun.Status.PENDING).update(
        status=AgentRun.Status.CANCELLED, cancel_requested=True, finished_at=now, updated_at=now
    )
    AgentRun.objects.filter(pk=run.pk, status=AgentRun.Status.RUNNING).update(cancel_requested=True, updated_at=now)
    run.refresh_from_db()
    return run


def reconcile_stale_run(run):
    """A long-unupdated active run is terminalized on the next scoped lookup."""
    if run.status not in {AgentRun.Status.PENDING, AgentRun.Status.RUNNING}:
        return
    cutoff = timezone.now() - timedelta(seconds=getattr(settings, "AGENT_CHAT_RUN_STALE_SECONDS", 900))
    if run.updated_at >= cutoff:
        return
    fail_run(run, "interrupted", stale_before=cutoff)


def serialize_run(run):
    input_message = run.messages.filter(role=Message.Role.USER).values_list("id", flat=True).first()
    output_message = run.messages.filter(role=Message.Role.AGENT).values_list("id", flat=True).first()
    result = run.result
    if run.status == AgentRun.Status.SUCCEEDED and not result:
        # Pre-I-006 rows have no result JSON; their observation still carries
        # the answer and evidence, when one was recorded.
        observation = run.observations.order_by("-id").first()
        if observation:
            result = {
                "answer": observation.answer,
                "route": observation.route,
                "trace": observation.trace,
                "tool_calls": observation.tool_calls,
                "sources": observation.sources,
                "token_usage": observation.token_usage,
            }
    return {
        "run_id": str(run.run_id),
        "request_id": run.request_id,
        "status": run.status,
        "cancel_requested": run.cancel_requested,
        "cancellation_mode": "cooperative_after_current_step",
        "conversation_id": run.conversation_id,
        "input_message_id": input_message,
        "output_message_id": output_message,
        "result": result if run.status == AgentRun.Status.SUCCEEDED else None,
        "error_code": run.error_code,
        "model_calls": run.model_calls,
        "model_accounting": run.model_accounting,
        "stage_timings": run.stage_timings,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
