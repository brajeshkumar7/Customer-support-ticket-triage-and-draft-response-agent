"""Minimal classify-then-respond LangGraph for support tickets."""

import asyncio
import json
import os
from typing import Any

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from src.agent.state import AgentState
from src.memory.short_term import ShortTermMemory
from src.openrouter_client import OpenRouterClient

CLASSIFICATIONS = {
    "order status",
    "return request",
    "damaged item",
    "billing dispute",
    "general question",
}
URGENCIES = {"low", "medium", "high"}
SAMPLE_TICKET = "My package has not arrived, and I need to know its status."


def _message_content(response: Any) -> str:
    """Extract the assistant text from an OpenAI-compatible completion."""
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as error:
        raise ValueError("OpenRouter returned an invalid chat completion.") from error
    if not isinstance(content, str) or not content.strip():
        raise ValueError("OpenRouter returned an empty assistant response.")
    return content.strip()


def _parse_classification(content: str) -> tuple[str, str]:
    try:
        result = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("Classifier response must be a JSON object.") from error
    if not isinstance(result, dict):
        raise ValueError("Classifier response must be a JSON object.")

    category = result.get("category")
    urgency = result.get("urgency")
    if not isinstance(category, str) or category.strip().lower() not in CLASSIFICATIONS:
        allowed = ", ".join(sorted(CLASSIFICATIONS))
        raise ValueError(f"Classifier returned an invalid category; expected one of: {allowed}.")
    if not isinstance(urgency, str) or urgency.strip().lower() not in URGENCIES:
        allowed = ", ".join(sorted(URGENCIES))
        raise ValueError(f"Classifier returned an invalid urgency; expected one of: {allowed}.")
    return category.strip().lower(), urgency.strip().lower()


def build_graph(
    *,
    short_term_memory: ShortTermMemory,
    client: Any | None = None,
    primary_model: str | None = None,
):
    """Compile a two-node graph for one ticket-scoped memory store."""
    load_dotenv()
    model = primary_model or os.getenv("OPENROUTER_PRIMARY_MODEL", "").strip()
    if not model:
        raise ValueError("OPENROUTER_PRIMARY_MODEL must name the primary OpenRouter model.")
    llm = client or OpenRouterClient()

    def validate_ticket_id(state: AgentState) -> None:
        if state["ticket_id"] != short_term_memory.ticket_id:
            raise ValueError(
                "AgentState ticket_id must match the injected ShortTermMemory ticket_id."
            )

    async def classify(state: AgentState) -> dict[str, str]:
        validate_ticket_id(state)
        response = await llm.create_chat_completion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify the support ticket. Return only a JSON object with "
                        'string fields "category" and "urgency". Category must be one '
                        'of: "order status", "return request", "damaged item", '
                        '"billing dispute", "general question". Urgency must be '
                        '"low", "medium", or "high".'
                    ),
                },
                {"role": "user", "content": state["ticket_text"]},
            ],
            temperature=0,
        )
        category, urgency = _parse_classification(_message_content(response))
        short_term_memory.set("ticket_text", state["ticket_text"])
        short_term_memory.set("category", category)
        short_term_memory.set("urgency", urgency)
        return {"category": category, "urgency": urgency}

    async def respond(state: AgentState) -> dict[str, str]:
        validate_ticket_id(state)
        response = await llm.create_chat_completion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Draft a concise, courteous customer support reply using only "
                        "the supplied ticket text, category, and urgency. No order, "
                        "policy, or account facts have been verified. Do not invent or "
                        "promise facts or actions; ask the customer for the information "
                        "needed to investigate when the ticket lacks enough detail."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "ticket_text": state["ticket_text"],
                            "category": state["category"],
                            "urgency": state["urgency"],
                        }
                    ),
                },
            ],
            temperature=0,
        )
        draft_response = _message_content(response)
        short_term_memory.set("draft_response", draft_response)
        return {"draft_response": draft_response}

    builder = StateGraph(AgentState)
    builder.add_node("classify", classify)
    builder.add_node("respond", respond)
    builder.add_edge(START, "classify")
    builder.add_edge("classify", "respond")
    builder.add_edge("respond", END)
    return builder.compile()


async def _run_sample() -> None:
    ticket_id = "sample-ticket"
    short_term_memory = ShortTermMemory(ticket_id)
    result = await build_graph(short_term_memory=short_term_memory).ainvoke(
        {"ticket_id": ticket_id, "ticket_text": SAMPLE_TICKET}
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(_run_sample())
