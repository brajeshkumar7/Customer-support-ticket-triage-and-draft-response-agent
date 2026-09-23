"""
Shared state schema passed between LangGraph nodes.
Implements PRD.md Section 4: Memory (short-term working state).

Define the TypedDict/Pydantic model for: ticket, classification, tool results,
draft response, confidence score, retry count, escalation flag.
"""
