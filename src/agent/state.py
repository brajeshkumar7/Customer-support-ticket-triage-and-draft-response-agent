"""State shared by the support-ticket triage graph."""

from typing import Any, NotRequired, TypedDict


class AgentState(TypedDict):
    """Ticket identity, input, and values produced by the graph."""

    ticket_id: str
    ticket_text: str
    category: NotRequired[str]
    urgency: NotRequired[str]
    order_id: NotRequired[str | None]
    stated_reason: NotRequired[str]
    tool_results: NotRequired[dict[str, Any]]
    recalled_facts: NotRequired[list[dict[str, Any]]]
    memory_errors: NotRequired[list[dict[str, str]]]
    remembered_fact_id: NotRequired[str]
    draft_response: NotRequired[str]
