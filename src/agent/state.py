"""State shared by the minimal ticket classification graph."""

from typing import NotRequired, TypedDict


class AgentState(TypedDict):
    """The input ticket and the three values produced by the graph."""

    ticket_text: str
    category: NotRequired[str]
    urgency: NotRequired[str]
    draft_response: NotRequired[str]
