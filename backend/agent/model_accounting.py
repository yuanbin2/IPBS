"""Per-request LangChain model accounting. Never retains prompts or completions."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.context import register_configure_hook

from .telemetry import current_request_id

_handler: ContextVar[BaseCallbackHandler | None] = ContextVar("model_accounting_handler", default=None)
_purpose: ContextVar[str] = ContextVar("model_accounting_purpose", default="answer_generation")
_retry_group: ContextVar[str | None] = ContextVar("model_accounting_retry_group", default=None)
register_configure_hook(_handler, True)


def _usage(data):
    if not isinstance(data, dict):
        return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    aliases = {
        "prompt_tokens": ("prompt_tokens", "input_tokens"),
        "completion_tokens": ("completion_tokens", "output_tokens"),
        "total_tokens": ("total_tokens",),
    }
    result = {}
    for key, names in aliases.items():
        value = next((data[name] for name in names if isinstance(data.get(name), int)), None)
        result[key] = value if value is not None and value >= 0 else None
    return result


def _result_usage(result):
    for generation in result.generations or []:
        for item in generation:
            message = getattr(item, "message", None)
            if message is not None:
                metadata = getattr(message, "usage_metadata", None)
                if metadata:
                    return _usage(metadata)
                response = getattr(message, "response_metadata", None) or {}
                if response.get("token_usage"):
                    return _usage(response["token_usage"])
    return _usage((result.llm_output or {}).get("token_usage"))


def price_book_from_env():
    """Explicit JSON: version, currency, units_per_token_price, models.

    Empty pricing means unknown costs, never a guessed provider tariff.
    """
    raw = os.getenv("AGENT_MODEL_PRICES_JSON", "")
    if not raw:
        return {"version": "unconfigured", "currency": None, "units_per_token_price": None, "models": {}}
    try:
        data = json.loads(raw)
        if not isinstance(data.get("models"), dict) or not data.get("version"):
            raise ValueError("invalid price book")
        return data
    except (ValueError, TypeError):
        return {"version": "invalid", "currency": None, "units_per_token_price": None, "models": {}}


class ModelCallCollector(BaseCallbackHandler):
    def __init__(self, run_id: str, price_book: dict | None = None):
        self.run_id = str(run_id)
        self.price_book = price_book if price_book is not None else price_book_from_env()
        self.calls: list[dict] = []
        self._active: dict[str, tuple[float, dict]] = {}
        self._last_attempt: dict[str, int] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self._start(serialized, run_id, kwargs)

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self._start(serialized, run_id, kwargs)

    def _start(self, serialized, run_id, kwargs):
        params = kwargs.get("invocation_params") or {}
        model = (
            params.get("model_name") or params.get("model") or (serialized or {}).get("kwargs", {}).get("model_name")
        )
        model = str(model or "unknown")[:120]
        purpose = _purpose.get()
        group = _retry_group.get()
        attempt = self._last_attempt.get(group, 0) + 1 if group else 1
        if group:
            self._last_attempt[group] = attempt
        self._active[str(run_id)] = (
            time.perf_counter(),
            {
                "request_id": current_request_id(),
                "run_id": self.run_id,
                "call_id": str(run_id),
                "purpose": purpose,
                "model": model,
                "attempt": attempt,
            },
        )

    def _finish(self, run_id, *, result=None, error=None):
        active = self._active.pop(str(run_id), None)
        if active is None:
            return
        start, call = active
        call.update(
            latency_ms=round((time.perf_counter() - start) * 1000),
            status="failed" if error is not None else "succeeded",
            error_type=type(error).__name__ if error is not None else None,
            token_usage=_result_usage(result) if result is not None else _usage(None),
        )
        self.calls.append(call)

    def on_llm_end(self, response, *, run_id, **kwargs):
        self._finish(run_id, result=response)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._finish(run_id, error=error)

    def summary(self):
        book = self.price_book
        unit = book.get("units_per_token_price")
        prices = book.get("models") or {}
        known = Decimal("0")
        unknown_cost_calls = 0
        unknown_usage_calls = 0
        total = {key: 0 for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
        for call in self.calls:
            usage = call["token_usage"]
            for key in total:
                if usage[key] is None:
                    total[key] = None
                elif total[key] is not None:
                    total[key] += usage[key]
            if any(value is None for value in usage.values()):
                unknown_usage_calls += 1
            price = prices.get(call["model"])
            try:
                if not price or not unit or usage["prompt_tokens"] is None or usage["completion_tokens"] is None:
                    raise ValueError("unpriced")
                amount = (
                    Decimal(usage["prompt_tokens"]) * Decimal(str(price["input"]))
                    + Decimal(usage["completion_tokens"]) * Decimal(str(price["output"]))
                ) / Decimal(str(unit))
                if amount < 0:
                    raise ValueError("negative price")
                call["known_cost"] = str(amount)
                known += amount
            except (ValueError, InvalidOperation, KeyError, TypeError, ZeroDivisionError):
                call["known_cost"] = None
                unknown_cost_calls += 1
        return {
            "run_id": self.run_id,
            "call_count": len(self.calls),
            "failed_calls": sum(call["status"] == "failed" for call in self.calls),
            "token_usage": total,
            "unknown_usage_calls": unknown_usage_calls,
            "known_cost": str(known),
            "unknown_cost_calls": unknown_cost_calls,
            "currency": book.get("currency"),
            "price_version": book.get("version", "invalid"),
            "price_unit_tokens": unit,
            "complete_cost": unknown_cost_calls == 0,
        }


@contextmanager
def collect_model_calls(run_id, price_book=None):
    collector = ModelCallCollector(str(run_id), price_book)
    token = _handler.set(collector)
    try:
        yield collector
    finally:
        _handler.reset(token)


@contextmanager
def model_purpose(name: str):
    token = _purpose.set(name)
    try:
        yield
    finally:
        _purpose.reset(token)


@contextmanager
def model_retry_group(group: str):
    """Use the same group for explicit caller retries; independent calls start at 1."""
    token = _retry_group.set(group)
    try:
        yield
    finally:
        _retry_group.reset(token)
