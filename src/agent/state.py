"""State shared by the minimal ticket classification graph."""

from typing import NotRequired, TypedDict


class AgentState(TypedDict):
    """Ticket identity, input, and values produced by the graph."""

    ticket_id: str
    ticket_text: str
    category: NotRequired[str]
    urgency: NotRequired[str]
    draft_response: NotRequired[str]
