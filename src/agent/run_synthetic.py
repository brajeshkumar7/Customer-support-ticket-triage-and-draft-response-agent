"""Run one synthetic ticket through the graph with simulated delivery only."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

from src.agent.graph import build_graph
from src.agent.reply_sender import SimulationOnlyReplySender
from src.memory.long_term import LongTermMemory
from src.memory.short_term import ShortTermMemory
from src.eval.run_eval import load_cases

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class SimulatedReplySender(SimulationOnlyReplySender):
    """Record an approved reply as simulated; never contact Zoho or another API."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def send_public_reply(self, ticket_id: str, body: str) -> dict[str, Any]:
        self.calls.append({"ticket_id": ticket_id, "body": body})
        return {"simulated": True, "ticket_id": ticket_id, "http_status": None}


async def run_case(
    case_id: str,
    *,
    cases_loader: Callable[[], list[dict[str, str]]] = load_cases,
    graph_builder: Callable[..., Any] = build_graph,
    memory_factory: Callable[..., Any] = LongTermMemory,
) -> tuple[dict[str, Any], SimulatedReplySender]:
    cases = cases_loader()
    case = next((candidate for candidate in cases if candidate["ticket_id"] == case_id), None)
    if case is None:
        raise ValueError(f"Unknown synthetic case ID: {case_id}")

    run_id = f"synthetic-{case_id}-{uuid4().hex[:10]}"
    sender = SimulatedReplySender()
    graph = graph_builder(
        short_term_memory=ShortTermMemory(run_id),
        long_term_memory=memory_factory(ephemeral=True),
        reply_sender=sender,
    )
    result = await graph.ainvoke(
        {
            "ticket_id": run_id,
            "zoho_ticket_id": f"SIMULATED-{case_id}",
            "ticket_text": case["ticket_text"],
        }
    )
    return result, sender


def main(
    argv: Sequence[str] | None = None,
    *,
    cases_loader: Callable[[], list[dict[str, str]]] = load_cases,
    graph_builder: Callable[..., Any] = build_graph,
    memory_factory: Callable[..., Any] = LongTermMemory,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True, help="Synthetic ticket ID, e.g. order_01")
    args = parser.parse_args(argv)
    previous_flag = os.environ.get("ZOHO_DESK_SEND_ENABLED")
    load_dotenv(REPOSITORY_ROOT / ".env")
    os.environ["ZOHO_DESK_SEND_ENABLED"] = "true"
    try:
        result, sender = asyncio.run(
            run_case(
                args.case_id,
                cases_loader=cases_loader,
                graph_builder=graph_builder,
                memory_factory=memory_factory,
            )
        )
    except Exception as error:
        print(f"Synthetic run failed: {error}")
        return 1
    finally:
        if previous_flag is None:
            os.environ.pop("ZOHO_DESK_SEND_ENABLED", None)
        else:
            os.environ["ZOHO_DESK_SEND_ENABLED"] = previous_flag

    summary = {
        "category": result.get("category"),
        "urgency": result.get("urgency"),
        "priority": result.get("priority"),
        "priority_rank": result.get("priority_rank"),
        "classification_basis": result.get("classification_basis"),
        "category_basis": result.get("category_basis"),
        "urgency_basis": result.get("urgency_basis"),
        "triage_decision": result.get("triage_decision"),
        "terminal_status": result.get("terminal_status"),
        "delivery": "simulated" if result.get("zoho_send_result", {}).get("simulated") else None,
        "supervisor_status": result.get("supervisor_status"),
        "supervisor_reason": result.get("supervisor_reason"),
        "supervisor_decision": result.get("supervisor_decision"),
        "confidence_score": result.get("confidence_score"),
        "safety_review": result.get("safety_review"),
        "workflow_error": result.get("workflow_error"),
        "retry_count": result.get("retry_count"),
        "draft_response": result.get("draft_response"),
        "rag_review": result.get("rag_review"),
        "rag_search_count": result.get("rag_search_count"),
        "draft_evidence_ids": result.get("draft_evidence_ids"),
        "retrieved_evidence": result.get("retrieved_evidence", []),
        "escalation_reason": result.get("escalation_reason"),
        "simulated_sender_calls": len(sender.calls),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
