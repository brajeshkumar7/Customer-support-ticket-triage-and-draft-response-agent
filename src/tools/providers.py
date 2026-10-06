"""Provider-neutral interfaces for support facts and reference data.

The current implementations are fixture-backed. A future commerce connector
can implement these contracts without changing the graph or its safety rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from src.tools.base import ToolResult, ToolUnavailableError
from src.observability.logger import log_tool_event


class OrderFactsProvider(Protocol):
    async def run(self, *, run_id: str | None = None, order_id: str | None) -> ToolResult:
        """Return verified order and shipment facts or raise a typed ToolError."""


class PolicySource(Protocol):
    async def run(
        self, *, run_id: str | None = None, order_id: str | None, reason: str
    ) -> ToolResult:
        """Return an eligibility result or raise a typed ToolError."""


class FAQSource(Protocol):
    async def run(self, *, run_id: str | None = None, query: str) -> ToolResult:
        """Return matching reference material or raise a typed ToolError."""


class ShipmentFactsProvider(Protocol):
    async def run(self, *, run_id: str | None = None, order_id: str | None) -> ToolResult:
        """Return a fresh shipment record or raise a typed ToolError."""


class BillingFactsProvider(Protocol):
    async def run(self, *, run_id: str | None = None, account_id: str | None) -> ToolResult:
        """Return an authorized billing record or raise a typed ToolError."""


@dataclass(frozen=True)
class CustomerOrderEvidence:
    """Contract for a future authoritative order/shipment adapter.

    Fixture tool results do not satisfy this contract and cannot authorize
    customer-specific replies.
    """

    order_id: str
    requester_email: str
    order_status: str
    shipment_status: str
    observed_at: datetime
    source: str


def verify_customer_order_evidence(
    evidence: CustomerOrderEvidence,
    *,
    ticket_requester_email: str,
    now: datetime,
    max_age: timedelta = timedelta(minutes=15),
) -> tuple[bool, str]:
    """Fail closed on mismatch, stale/invalid timestamps, and contradictions."""
    if not evidence.source or not evidence.order_id:
        return False, "source_unavailable"
    if (not ticket_requester_email or evidence.requester_email.casefold()
            != ticket_requester_email.casefold()):
        return False, "requester_mismatch"
    if (evidence.observed_at.tzinfo is None or now.tzinfo is None
            or evidence.observed_at > now
            or now - evidence.observed_at > max_age):
        return False, "stale_or_invalid_timestamp"
    order = evidence.order_status.casefold()
    shipment = evidence.shipment_status.casefold()
    if order not in {"processing", "shipped", "delivered"} or shipment not in {
        "not_shipped", "in_transit", "delivered",
    }:
        return False, "unknown_status"
    if (order == "delivered" and shipment != "delivered") or (
        order == "processing" and shipment != "not_shipped"
    ):
        return False, "conflicting_facts"
    return True, "verified"


class UnavailableBusinessSource:
    """Explicit placeholder: no real commerce, shipment, billing or policy API exists."""

    def __init__(self, source: str) -> None:
        if source not in {"order", "shipment", "billing", "policy"}:
            raise ValueError("Unknown business source.")
        self.source = source

    async def run(self, **kwargs: Any) -> ToolResult:
        error = ToolUnavailableError(self.source, f"Authoritative {self.source} source is not configured.")
        log_tool_event(tool_name=self.source, inputs={"configured": False}, output=None,
                       error={"type": type(error).__name__}, latency_ms=0,
                       run_id=kwargs.get("run_id"))
        raise error


def unavailable_result(error: BaseException) -> dict[str, Any]:
    """Normalize a provider failure without converting it into evidence."""
    source = getattr(error, "source", getattr(error, "tool_name", "unknown"))
    return {
        "ok": False,
        "availability": "unavailable",
        "error": {"type": type(error).__name__, "source": str(source)},
    }
