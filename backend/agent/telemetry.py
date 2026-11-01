"""Small, content-free correlation and stage timing layer for chat and ingestion."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

_request_id = ContextVar("agent_request_id", default="")
_run_id = ContextVar("agent_run_id", default="")
_task_id = ContextVar("agent_task_id", default="")
_stages = ContextVar("agent_stage_timings", default=None)
logger = logging.getLogger("agent.telemetry")
_SAFE_VALUE = re.compile(r"^[a-zA-Z0-9_.:-]{1,100}$")
_ERROR_CLASSES = {
    "APIError",
    "AuthenticationError",
    "BadRequestError",
    "ConnectionError",
    "Exception",
    "NotFoundError",
    "PermissionError",
    "RateLimitError",
    "RuntimeError",
    "TimeoutError",
    "ValueError",
}
_KNOWN_ERROR_CODES = {
    "broker_unavailable",
    "document_ingestion_failed",
    "email_delivery_failed",
    "embedding_space_invalid",
    "ingestion_timeout",
    "retry_limit_exceeded",
}


def _safe(value):
    value = str(value or "")
    if not value:
        return ""
    return value if _SAFE_VALUE.fullmatch(value) else "invalid"


def safe_error_code(value):
    """Keep only application codes or exception class names, never provider text."""
    value = str(value or "")
    if value in _KNOWN_ERROR_CODES or value in _ERROR_CLASSES:
        return value
    prefix, separator, suffix = value.partition(":")
    if separator and prefix == "embedding_request_failed" and suffix in _ERROR_CLASSES:
        return value
    return "other_failure"


def current_request_id(request=None):
    raw = getattr(request, "request_id", None) or getattr(getattr(request, "_request", None), "request_id", None)
    return str(raw or _request_id.get())


@contextmanager
def correlate(*, request_id=None, run_id=None, task_id=None):
    tokens = []
    for var, value in ((_request_id, request_id), (_run_id, run_id), (_task_id, task_id)):
        if value is not None:
            tokens.append((var, var.set(str(value))))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


@contextmanager
def collect_stages():
    stages = []
    token = _stages.set(stages)
    try:
        yield stages
    finally:
        _stages.reset(token)


def emit(event, *, level="info", **fields):
    """Only identifiers, fixed codes, counts and timings may enter operational logs."""
    permitted = {
        "status",
        "error_code",
        "stage",
        "attempt",
        "duration_ms",
        "queue_wait_ms",
        "retrieval_ms",
        "model_ms",
        "count",
        "document_id",
    }
    data = {
        "event": _safe(event),
        "request_id": _safe(_request_id.get()),
        "run_id": _safe(_run_id.get()),
        "task_id": _safe(_task_id.get()),
    }
    for key, value in fields.items():
        if key not in permitted:
            continue
        if key in {"attempt", "duration_ms", "queue_wait_ms", "retrieval_ms", "model_ms", "count", "document_id"}:
            data[key] = max(0, int(value))
        elif key == "error_code":
            data[key] = safe_error_code(value)
        else:
            data[key] = _safe(value)
    getattr(logger, level)("telemetry %s", json.dumps(data, sort_keys=True))
    return data


@contextmanager
def timed_stage(name):
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:
        duration = round((time.perf_counter() - started) * 1000)
        stages = _stages.get()
        if stages is not None:
            stages.append({"stage": name, "duration_ms": duration, "status": "failed"})
        emit("stage_completed", stage=name, duration_ms=duration, status="failed", error_code=type(exc).__name__)
        raise
    else:
        duration = round((time.perf_counter() - started) * 1000)
        stages = _stages.get()
        if stages is not None:
            stages.append({"stage": name, "duration_ms": duration, "status": "succeeded"})
        emit("stage_completed", stage=name, duration_ms=duration, status="succeeded")


def observe_stage(name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with timed_stage(name):
                return function(*args, **kwargs)

        return wrapped

    return decorate


def stage_summary(stages, model_calls, *, queue_wait_ms=0, total_ms=None):
    timings = {
        "queue_wait_ms": max(0, queue_wait_ms),
        "retrieval_ms": sum(item["duration_ms"] for item in stages if item["stage"] == "retrieval"),
        "retrieval_calls": sum(item["stage"] == "retrieval" for item in stages),
        "model_ms": sum(call["latency_ms"] for call in model_calls),
        "model_calls": len(model_calls),
        "total_ms": total_ms,
    }
    candidates = {"queue": timings["queue_wait_ms"], "retrieval": timings["retrieval_ms"], "model": timings["model_ms"]}
    largest = max(candidates, key=candidates.get)
    timings["largest_measured_stage"] = largest if candidates[largest] > 0 else None
    return timings


def failure_alert(kind, error_code, *, request_id="", run_id="", task_id=""):
    """Console alert plus optional configured admin email; no request or exception body."""
    with correlate(request_id=request_id, run_id=run_id, task_id=task_id):
        data = emit("failure_alert", level="error", status=kind, error_code=error_code)
        from django.conf import settings

        recipients = getattr(settings, "AGENT_ALERT_EMAILS", [])
        if recipients:
            from django.core.mail import send_mail

            try:
                send_mail(
                    subject=f"Agent failure: {_safe(kind)}",
                    message=json.dumps(data, sort_keys=True),
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "agent-alert@localhost"),
                    recipient_list=recipients,
                    fail_silently=False,
                )
            except Exception:
                emit("alert_delivery_failed", level="error", error_code="email_delivery_failed")


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Generate locally; never trust a client-supplied correlation header.
        request.request_id = str(uuid.uuid4())
        started = time.perf_counter()
        with correlate(request_id=request.request_id):
            response = self.get_response(request)
            if request.path.startswith(("/api/agent/chat/", "/api/agent/documents/", "/api/agent/tasks/")):
                emit(
                    "response_started" if getattr(response, "streaming", False) else "request_completed",
                    status=response.status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                )
        response["X-Request-ID"] = request.request_id
        return response
