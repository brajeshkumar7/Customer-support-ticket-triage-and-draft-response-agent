"""State shared by the support-ticket triage graph."""

from typing import Any, NotRequired, TypedDict


class AgentState(TypedDict):
    """Ticket identity, input, and values produced by the graph."""

    ticket_id: str
    ticket_text: str
    zoho_ticket_id: NotRequired[str]
    category: NotRequired[str]
    urgency: NotRequired[str]
    order_id: NotRequired[str | None]
    stated_reason: NotRequired[str]
    tool_results: NotRequired[dict[str, Any]]
    recalled_facts: NotRequired[list[dict[str, Any]]]
    memory_errors: NotRequired[list[dict[str, str]]]
    remembered_fact_id: NotRequired[str]
    draft_response: NotRequired[str]
    supervisor_status: NotRequired[str]
    supervisor_reason: NotRequired[dict[str, Any]]
    retry_count: NotRequired[int]
    supervisor_feedback: NotRequired[dict[str, Any]]
    escalated: NotRequired[bool]
    escalation_reason: NotRequired[str]
    escalation_payload: NotRequired[dict[str, Any]]
    failed_attempts: NotRequired[list[dict[str, Any]]]
    confidence_score: NotRequired[float]
    response_sent: NotRequired[bool]
    zoho_delivery_status: NotRequired[str]
    zoho_send_result: NotRequired[dict[str, Any]]
    zoho_http_status: NotRequired[int | None]
    send_failure_reason: NotRequired[str | None]
    terminal_status: NotRequired[str]
    workflow_error: NotRequired[dict[str, str]]
