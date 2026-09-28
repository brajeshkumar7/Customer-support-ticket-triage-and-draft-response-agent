"""Append-only, bounded JSONL events for agent runs."""

import json
import re
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_EVENT_FIELD_CHARS = 4_000
_write_lock = threading.Lock()
_LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "logs" / "events.jsonl"
_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"authorization|password|credential)",
    re.IGNORECASE,
)


def _redact(value: Any) -> Any:
    """Replace common credential values before an event is serialized."""
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _bounded(value: Any) -> Any:
    safe_value = _redact(value)
    encoded = json.dumps(safe_value, ensure_ascii=False, default=str)
    if len(encoded) <= MAX_EVENT_FIELD_CHARS:
        return safe_value
    return {
        "truncated": True,
        "preview": encoded[:MAX_EVENT_FIELD_CHARS],
    }


def log_event(
    *,
    event_type: str,
    run_id: str | None,
    name: str,
    inputs: Any,
    output: Any,
    latency_ms: float,
    error: dict[str, Any] | None = None,
    token_cost: float | None = None,
) -> None:
    """Append one JSON event, serializing it under a process-wide thread lock."""
    event: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id or "unscoped",
        "event_type": event_type,
        "name": name,
        "inputs": _bounded(inputs),
        "output": _bounded(output),
        "latency_ms": round(max(0.0, latency_ms), 3),
    }
    if event_type == "node_transition":
        event["node_name"] = name
    elif event_type == "tool_call":
        event["tool_name"] = name
    elif event_type in {"llm_call", "rate_limit"}:
        event["call_name"] = name
    if event_type == "llm_call":
        # None means the provider did not return a cost; it is not estimated.
        event["token_cost"] = token_cost
    if error is not None:
        event["error"] = _bounded(error)

    encoded = json.dumps(event, ensure_ascii=False, default=str)
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock, _LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(encoded + "\n")


def log_tool_event(
    *,
    tool_name: str,
    inputs: Any,
    output: Any,
    error: dict[str, Any] | None,
    latency_ms: float,
    token_cost: float | None = None,
    run_id: str | None = None,
) -> None:
    """Compatibility helper for logging one tool invocation."""
    log_event(
        event_type="tool_call",
        run_id=run_id,
        name=tool_name,
        inputs=inputs,
        output=output,
        error=error,
        latency_ms=latency_ms,
    )


def log_node_event(
    *,
    node_name: str,
    run_id: str | None,
    inputs: Any,
    output: Any,
    latency_ms: float,
    error: dict[str, Any] | None = None,
) -> None:
    """Append one graph-node execution with its state input and update."""
    log_event(
        event_type="node_transition",
        run_id=run_id,
        name=node_name,
        inputs=inputs,
        output=output,
        error=error,
        latency_ms=latency_ms,
    )


def log_llm_event(
    *,
    run_id: str | None,
    call_name: str,
    inputs: Any,
    output: Any,
    latency_ms: float,
    token_cost: float | None,
    error: dict[str, Any] | None = None,
) -> None:
    """Append one LLM API attempt and provider-reported cost when present."""
    log_event(
        event_type="llm_call",
        run_id=run_id,
        name=call_name,
        inputs=inputs,
        output=output,
        error=error,
        latency_ms=latency_ms,
        token_cost=token_cost,
    )


def log_rate_limit_event(
    *,
    run_id: str | None,
    call_name: str,
    inputs: Any,
    output: Any,
    latency_ms: float,
    error: dict[str, Any] | None = None,
) -> None:
    """Append a structured event for each account-level rate-limit response."""
    log_event(
        event_type="rate_limit",
        run_id=run_id,
        name=call_name,
        inputs=inputs,
        output=output,
        error=error,
        latency_ms=latency_ms,
    )
