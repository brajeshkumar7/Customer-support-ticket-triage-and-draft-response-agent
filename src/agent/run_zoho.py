"""Fetch one controlled Zoho email ticket and run the agent in draft-only mode."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from collections.abc import Callable, Sequence
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

from src.agent.graph import build_graph
from src.memory.long_term import LongTermMemory
from src.memory.short_term import ShortTermMemory
from zoho_desk_client import ZohoDeskClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return " ".join(" ".join(parser.parts).split())


async def _await_if_needed(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


async def process_ticket(
    ticket_id: str,
    *,
    client: Any,
    graph_builder: Callable[..., Any] = build_graph,
    memory_factory: Callable[..., Any] = LongTermMemory,
) -> dict[str, Any]:
    ticket = await _await_if_needed(client.fetch_ticket(ticket_id))
    if not isinstance(ticket, dict):
        raise ValueError("Zoho returned an invalid ticket record.")
    channel = ticket.get("channel")
    if not isinstance(channel, str) or channel.strip().casefold() != "email":
        raise ValueError("This command only processes Zoho Email tickets; no agent run or reply was made.")
    description = ticket.get("description")
    subject = ticket.get("subject")
    body_text = _plain_text(description) if isinstance(description, str) else ""
    subject_text = _plain_text(subject) if isinstance(subject, str) else ""
    if not body_text:
        raise ValueError("The Zoho ticket has no usable description; no agent run or reply was made.")
    ticket_text = f"Subject: {subject_text}\n\n{body_text}" if subject_text else body_text

    run_id = f"zoho-{ticket_id}-{uuid4().hex[:10]}"
    graph = graph_builder(
        short_term_memory=ShortTermMemory(run_id),
        long_term_memory=memory_factory(),
        allow_delivery=False,
    )
    try:
        run_timeout = float(os.getenv("AGENT_RUN_TIMEOUT_SECONDS", "60"))
    except ValueError as error:
        raise ValueError("AGENT_RUN_TIMEOUT_SECONDS must be a positive number.") from error
    if not 0 < run_timeout <= 600:
        raise ValueError("AGENT_RUN_TIMEOUT_SECONDS must be between 0 and 600.")
    return await asyncio.wait_for(graph.ainvoke(
        {
            "ticket_id": run_id,
            "zoho_ticket_id": ticket_id,
            "ticket_text": ticket_text,
        }
    ), timeout=run_timeout)


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[[], Any] = ZohoDeskClient.from_env,
    graph_builder: Callable[..., Any] = build_graph,
    memory_factory: Callable[..., Any] = LongTermMemory,
    confirm_input: Callable[[str], str] = input,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket-id", required=True, help="Existing numeric Zoho ticket API ID")
    parser.add_argument(
        "--draft-only",
        action="store_true",
        help="Required acknowledgement: this phase never sends a public reply.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    ticket_id = args.ticket_id.strip()
    if not re.fullmatch(r"[0-9]+", ticket_id):
        parser.error("--ticket-id must contain digits only.")
    if args.send:
        parser.error("Live sending is blocked during the safety-improvement phase; use --draft-only.")
    if not args.draft_only:
        print("No ticket fetched. Run with --draft-only to process a controlled ticket without sending.")
        return 0

    load_dotenv(REPOSITORY_ROOT / ".env")
    print(
        f"This will fetch Zoho ticket {ticket_id} and create a draft-only agent result. "
        "It cannot post a public reply, even when ZOHO_DESK_SEND_ENABLED=true. "
        "Use only a ticket and contact you control."
    )
    if confirm_input("Type CONTROLLED to confirm this ticket/contact are yours: ").strip() != "CONTROLLED":
        print("Ownership confirmation did not match; no ticket was fetched or reply sent.")
        return 2
    if confirm_input(f"Retype ticket ID {ticket_id} to confirm: ").strip() != ticket_id:
        print("Ticket confirmation did not match; no ticket was fetched or reply sent.")
        return 2

    try:
        client = client_factory()
        result = asyncio.run(
            process_ticket(
                ticket_id,
                client=client,
                graph_builder=graph_builder,
                memory_factory=memory_factory,
            )
        )
    except Exception as error:
        print(f"Zoho agent run stopped: {error}")
        return 1

    print(
        json.dumps(
            {
                "category": result.get("category"),
                "urgency": result.get("urgency"),
                "priority": result.get("priority"),
                "priority_rank": result.get("priority_rank"),
                "classification_basis": result.get("classification_basis"),
                "category_basis": result.get("category_basis"),
                "urgency_basis": result.get("urgency_basis"),
                "supervisor_status": result.get("supervisor_status"),
                "terminal_status": result.get("terminal_status"),
                "zoho_delivery_status": result.get("zoho_delivery_status"),
                "response_sent": result.get("response_sent"),
                "retry_count": result.get("retry_count"),
                "safety_review": result.get("safety_review"),
                "draft_response": result.get("draft_response"),
                "escalation_reason": result.get("escalation_reason"),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
