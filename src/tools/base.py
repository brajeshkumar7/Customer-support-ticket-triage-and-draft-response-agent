"""Common async interface, result type, errors, and logging for mock tools."""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any

from src.observability.logger import log_tool_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolResult:
    """Serializable data returned by a successful tool invocation."""

    tool_name: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ToolError(RuntimeError):
    """Base exception for expected, catchable tool failures."""

    def __init__(self, tool_name: str, message: str) -> None:
        self.tool_name = tool_name
        super().__init__(message)


class ToolInputError(ToolError):
    """Raised when a tool receives missing or invalid input."""


class ToolNotFoundError(ToolError):
    """Raised when a requested fixture record does not exist."""


class ToolExecutionError(ToolError):
    """Raised when a tool cannot complete because its data source failed."""


class BaseTool(ABC):
    """Base class exposing one async run method for every tool."""

    tool_name = "base_tool"

    async def run(self, **kwargs: Any) -> ToolResult:
        started = time.perf_counter()
        try:
            data = await asyncio.to_thread(self._execute, **kwargs)
        except ToolError as error:
            self._log_event(
                kwargs,
                output=None,
                error={"type": type(error).__name__, "message": str(error)},
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            raise
        except Exception as error:
            wrapped = ToolExecutionError(
                self.tool_name, f"Unexpected tool failure: {error}"
            )
            self._log_event(
                kwargs,
                output=None,
                error={"type": type(wrapped).__name__, "message": str(wrapped)},
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            raise wrapped from error

        result = ToolResult(tool_name=self.tool_name, data=data)
        self._log_event(
            kwargs,
            output=result.to_dict(),
            error=None,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        return result

    def _log_event(
        self,
        inputs: dict[str, Any],
        *,
        output: dict[str, Any] | None,
        error: dict[str, str] | None,
        latency_ms: float,
    ) -> None:
        try:
            log_tool_event(
                tool_name=self.tool_name,
                inputs=inputs,
                output=output,
                error=error,
                latency_ms=latency_ms,
                token_cost=0.0,
            )
        except OSError:
            # Logging failures should be visible without hiding the tool result/error.
            logger.exception("Could not write JSONL event for tool %s", self.tool_name)

    @abstractmethod
    def _execute(self, **kwargs: Any) -> dict[str, Any]:
        """Perform local work in a worker thread and return JSON-safe data."""
