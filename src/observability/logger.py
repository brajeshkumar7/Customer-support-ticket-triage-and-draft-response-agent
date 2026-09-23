"""Small JSONL event writer used by the mock tools."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_write_lock = threading.Lock()
_LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "logs" / "tool_calls.jsonl"


def log_tool_event(
    *,
    tool_name: str,
    inputs: dict[str, Any],
    output: dict[str, Any] | None,
    error: dict[str, str] | None,
    latency_ms: float,
    token_cost: float,
) -> None:
    """Append one concurrent-safe tool event to the project's JSONL log."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "tool_call",
        "tool_name": tool_name,
        "inputs": inputs,
        "output": output,
        "error": error,
        "latency_ms": round(latency_ms, 3),
        "token_cost": token_cost,
    }
    encoded = json.dumps(event, ensure_ascii=False, default=str)
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock, _LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(encoded + "\n")
