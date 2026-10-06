"""Run one controlled Zoho ticket through the agent; optionally send a reviewed email."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from collections.abc import Callable, Sequence
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

from src.agent.graph import build_graph
from src.memory.long_term import LongTermMemory
from src.memory.short_term import ShortTermMemory
from src.observability.logger import log_tool_event
from zoho_desk_client import ZohoDeskClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HUMAN_REVIEW_ACKNOWLEDGEMENT = (
    "Thank you for contacting support. We received your message and cannot "
    "verify the details needed for a specific answer yet. Please allow a "
    "support representative to review your ticket."
)


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


def _ticket_text(ticket: dict[str, Any]) -> str:
    description = ticket.get("description")
    subject = ticket.get("subject")
    body_text = _plain_text(description) if isinstance(description, str) else ""
    subject_text = _plain_text(subject) if isinstance(subject, str) else ""
    if not body_text:
        raise ValueError("The Zoho ticket has no usable description; no agent run or reply was made.")
    return f"Subject: {subject_text}\n\n{body_text}" if subject_text else body_text


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
    ticket_text = _ticket_text(ticket)

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


def _send_reviewed_draft(
    ticket_id: str,
    result: dict[str, Any],
    *,
    client: Any,
    confirm_input: Callable[[str], str],
) -> int:
    draft = result.get("draft_response")
    approved_draft = (result.get("supervisor_status") == "PASS"
                      and not result.get("workflow_error")
                      and isinstance(draft, str) and bool(draft.strip()))
    message = draft if approved_draft else HUMAN_REVIEW_ACKNOWLEDGEMENT
    content_source = "approved_agent_draft" if approved_draft else "human_review_acknowledgement"

    try:
        ticket = asyncio.run(_await_if_needed(client.fetch_ticket(ticket_id)))
        if not isinstance(ticket, dict) or str(ticket.get("id", ticket_id)) != ticket_id:
            raise ValueError("Zoho returned a different ticket; no email was sent.")
        if _ticket_text(ticket) != result.get("ticket_text"):
            raise ValueError("The ticket text changed during the agent run; no email was sent.")
        if str(ticket.get("status", "")).casefold() in {"closed", "spam", "deleted"}:
            raise ValueError("The ticket is closed or unavailable; no email was sent.")
        recipient = ticket.get("email")
        if not isinstance(recipient, str) or not re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient.strip()
        ):
            raise ValueError("The ticket has no valid requester email; no email was sent.")
        recipient = recipient.strip()
    except Exception as error:
        print(f"Reviewed send stopped: {error}")
        return 1

    print("The agent run has finished. Review the safety findings above.")
    print(f"Zoho ticket: {ticket_id}; recipient: {recipient}")
    safety_review = result.get("safety_review")
    if not approved_draft:
        print("The agent draft failed review. The email below is a fixed acknowledgement, not the agent draft.")
    elif not isinstance(safety_review, dict) or safety_review.get("send_allowed") is not True:
        print("Automatic delivery was blocked. Sending this controlled test draft requires your human review.")
    print(f"Exact outgoing email ({content_source}):\n\n{message}\n")
    if confirm_input("Type the requester email exactly to confirm the recipient: ").strip().casefold() != recipient.casefold():
        print("Recipient confirmation did not match; no email was sent.")
        return 2
    if confirm_input(f"Type SEND {ticket_id} to send the exact email above: ").strip() != f"SEND {ticket_id}":
        print("Email confirmation did not match; no email was sent.")
        return 2

    started = time.perf_counter()
    try:
        delivery = asyncio.run(_await_if_needed(client.send_reviewed_reply(
            ticket_id, message, expected_email=recipient,
        )))
        if not isinstance(delivery, dict) or not delivery.get("thread_id"):
            raise ValueError("Zoho did not confirm a reply thread ID")
    except Exception as error:
        try:
            log_tool_event(
                tool_name="zoho_desk_reviewed_reply",
                inputs={"zoho_ticket_id": ticket_id, "content_source": content_source}, output=None,
                error={"code": type(error).__name__, "delivery_status": getattr(error, "delivery_status", "unknown")},
                latency_ms=(time.perf_counter() - started) * 1000,
                run_id=result.get("ticket_id"),
            )
        except OSError:
            pass
        print(f"Zoho did not confirm the reviewed reply ({type(error).__name__}). Check the ticket before any retry.")
        return 1
    try:
        log_tool_event(
            tool_name="zoho_desk_reviewed_reply",
            inputs={"zoho_ticket_id": ticket_id, "content_source": content_source},
            output={"delivery_status": "sent", "http_status": delivery.get("http_status")},
            error=None, latency_ms=(time.perf_counter() - started) * 1000,
            run_id=result.get("ticket_id"),
        )
    except OSError:
        print("The email was sent, but its local JSONL delivery event could not be written.")
    print(json.dumps({
        "reviewed_email_status": "sent",
        "email_content_source": content_source,
        "zoho_ticket_id": ticket_id,
        "thread_id": delivery.get("thread_id"),
        "agent_run_id": result.get("ticket_id"),
    }, indent=2))
    return 0


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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--draft-only",
        action="store_true",
        help="Run the agent and print its draft without a public reply.",
    )
    mode.add_argument(
        "--send-reviewed",
        action="store_true",
        help="After the agent run, confirm the exact draft and recipient before one controlled email.",
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
        parser.error("Use --draft-only or --send-reviewed; the old --send mode is disabled.")
    if not args.draft_only and not args.send_reviewed:
        print("No ticket fetched. Choose --draft-only or --send-reviewed for a controlled test.")
        return 0

    load_dotenv(REPOSITORY_ROOT / ".env")
    if args.send_reviewed and os.getenv("ZOHO_DESK_SEND_ENABLED", "").strip().lower() not in {"true", "1", "yes", "on"}:
        parser.error("Set ZOHO_DESK_SEND_ENABLED=true before a reviewed test send.")
    print(
        f"This will fetch Zoho ticket {ticket_id} and run the local agent. "
        + ("You will review the draft before any public email is attempted. " if args.send_reviewed
           else "No public email will be attempted. ")
        + "Use only a ticket and contact you control."
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
                "agent_run_id": result.get("ticket_id"),
                "category": result.get("category"),
                "urgency": result.get("urgency"),
                "priority": result.get("priority"),
                "priority_rank": result.get("priority_rank"),
                "classification_basis": result.get("classification_basis"),
                "category_basis": result.get("category_basis"),
                "urgency_basis": result.get("urgency_basis"),
                "triage_decision": result.get("triage_decision"),
                "supervisor_status": result.get("supervisor_status"),
                "supervisor_reason": result.get("supervisor_reason"),
                "supervisor_decision": result.get("supervisor_decision"),
                "confidence_score": result.get("confidence_score"),
                "workflow_error": result.get("workflow_error"),
                "terminal_status": result.get("terminal_status"),
                "zoho_delivery_status": result.get("zoho_delivery_status"),
                "response_sent": result.get("response_sent"),
                "retry_count": result.get("retry_count"),
                "safety_review": result.get("safety_review"),
                "draft_response": result.get("draft_response"),
                "rag_review": result.get("rag_review"),
                "draft_evidence_ids": result.get("draft_evidence_ids", []),
                "retrieved_evidence": result.get("retrieved_evidence", []),
                "escalation_reason": result.get("escalation_reason"),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if args.send_reviewed:
        return _send_reviewed_draft(
            ticket_id, result, client=client, confirm_input=confirm_input,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
