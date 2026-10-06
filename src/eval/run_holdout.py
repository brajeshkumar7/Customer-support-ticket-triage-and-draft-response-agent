"""Run the frozen author-labeled holdout with real models and a fake sender only."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from src.agent.production_policy import APPROVAL_POLICY_VERSION, KNOWLEDGE_PATH, simulation_knowledge
from src.openrouter_client import OpenRouterClient
from src.memory.long_term import LongTermMemory
from src.tools.base import BaseTool, ToolUnavailableError
from src.eval.run_eval import (
    EXPECTED_CATEGORIES, FakeReplySender, REPOSITORY_ROOT, REPORTS_DIR,
    _run_graphs, calculate_metrics, costs_by_run_id,
    model_usage_by_run_id,
)

HOLDOUT_PATH = REPOSITORY_ROOT / "data" / "test_tickets" / "holdout_v1.jsonl"
FROZEN_SHA256 = "9db380b94121900e3aad49c60ee378dfe4dd25ac8ce8083844f4d81cdbeb096e"


class UnavailableOrderTool(BaseTool):
    tool_name = "order_lookup"

    def _execute(self, **_kwargs):
        raise ToolUnavailableError(self.tool_name, "Simulated order source timeout.")


def holdout_tools(case: dict[str, str]) -> dict:
    if case.get("scenario") == "provider_failure" and case.get("category") in {
        "order_status", "damaged_item",
    }:
        return {"order_lookup_tool": UnavailableOrderTool()}
    return {}


def load_holdout() -> list[dict]:
    payload = HOLDOUT_PATH.read_bytes()
    if hashlib.sha256(payload).hexdigest() != FROZEN_SHA256:
        raise ValueError("Frozen holdout hash changed; this version cannot be scored.")
    rows = [json.loads(line) for line in payload.decode("utf-8").splitlines() if line]
    if len(rows) != 200 or len({row["id"] for row in rows}) != 200:
        raise ValueError("Holdout must have 200 unique cases.")
    counts = Counter(row["category"] for row in rows)
    if counts != Counter({category: 40 for category in EXPECTED_CATEGORIES}):
        raise ValueError("Holdout must have 40 cases per category.")
    if any(row["expected_disposition"] not in {"informational", "human"}
           or row.get("label_provenance") != "author_drafted_templated_synthetic"
           or not isinstance(row.get("required_evidence"), list)
           or not isinstance(row.get("critical_failure_tags"), list)
           for row in rows):
        raise ValueError("Holdout labels or metadata are invalid.")
    return rows


def summarize(rows: list[dict]) -> dict:
    scored = []
    for row in rows:
        actual = row["observed_outcome"]
        expected = row["expected_disposition"]
        sent = actual == "simulated_sent"
        review = row.get("safety_review") or {}
        evidence = set(review.get("evidence_ids") or [])
        required = set(row.get("required_evidence") or [])
        evidence_ok = sent and bool(evidence) and required.issubset(evidence)
        unsupported_send = sent and (
            not evidence_ok or row.get("draft_response") != row.get("expected_template")
        )
        scored.append({**row,
                       "false_send": sent and expected == "human",
                       "false_escalation": actual == "escalated" and expected == "informational",
                       "evidence_covered": evidence_ok if sent else None,
                       "unsupported_public_claim": unsupported_send})
    metrics = calculate_metrics(scored)
    metrics["unsupported_public_claim_count"] = sum(r["unsupported_public_claim"] for r in scored)
    metrics["evidence_coverage"] = {
        "covered": sum(r["evidence_covered"] is True for r in scored),
        "simulated_sends": sum(r["observed_outcome"] == "simulated_sent" for r in scored),
    }
    metrics["by_category"] = {
        category: {**metrics["by_category"].get(category, {"ticket_count": 0}),
                   "unsupported_public_claims": sum(r["unsupported_public_claim"] for r in scored if r["category"] == category),
                   "p95_latency_ms": percentile95([r["latency_ms"] for r in scored if r["category"] == category])}
        for category in EXPECTED_CATEGORIES
    }
    metrics["p95_approved_faq_ms"] = percentile95([
        r["latency_ms"] for r in scored if r["observed_outcome"] == "simulated_sent"
    ])
    return metrics


def percentile95(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[(95 * len(values) + 99) // 100 - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Recompute a saved report without model calls.")
    parser.add_argument("--resume", type=Path, help="Resume an interrupted fake-sender checkpoint.")
    args = parser.parse_args()
    if args.report and args.resume:
        parser.error("Choose either --report or --resume.")
    if args.report:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        metrics = summarize(report["results"])
        model_usage = report.get("model_usage") or model_usage_by_run_id(
            {str(row["run_id"]) for row in report["results"] if row.get("run_id")}
        )
        metrics["by_model"] = model_usage
        print(json.dumps(metrics, indent=2))
        return 0
    source = load_holdout()
    knowledge = simulation_knowledge()
    cases = [{"ticket_id": row["id"], "ticket_text": row["ticket_text"],
              "category": row["category"],
              "expected_outcome": "auto_resolve" if row["expected_disposition"] == "informational" else "escalate",
              "notes": row["scenario"], "scenario": row["scenario"]} for row in source]
    load_dotenv(REPOSITORY_ROOT / ".env")
    if args.resume:
        checkpoint_path = args.resume.resolve()
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (checkpoint.get("holdout_sha256") != FROZEN_SHA256
                or checkpoint.get("delivery_adapter") != "fake"
                or checkpoint.get("memory_mode") != "shared_ephemeral_chroma_sequential"):
            parser.error("Checkpoint does not match the frozen fake-sender, shared-Chroma holdout mode.")
        if checkpoint.get("primary_model") != os.getenv("OPENROUTER_PRIMARY_MODEL", ""):
            parser.error("Configured primary model differs from the checkpoint.")
        if (checkpoint.get("approval_policy") != APPROVAL_POLICY_VERSION
                or checkpoint.get("knowledge_sha256") != hashlib.sha256(KNOWLEDGE_PATH.read_bytes()).hexdigest()
                or checkpoint.get("fallback_models") != [item.strip() for item in os.getenv("OPENROUTER_MODELS", "").split(",") if item.strip()]):
            parser.error("Policy, knowledge, or fallback models changed; start a new holdout run.")
        evaluation_id = checkpoint["evaluation_id"]
        completed = checkpoint["results"]
        valid_ids = {row["ticket_id"] for row in cases}
        done_ids = [row.get("ticket_id") for row in completed]
        if len(done_ids) != len(set(done_ids)) or not set(done_ids).issubset(valid_ids):
            parser.error("Checkpoint contains duplicate or unknown ticket IDs.")
    else:
        evaluation_id = "holdout_v1_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        checkpoint_path = REPORTS_DIR / f"{evaluation_id}.checkpoint.json"
        completed = []
    checkpoint = {"evaluation_id": evaluation_id, "holdout_sha256": FROZEN_SHA256,
                  "delivery_adapter": "fake", "primary_model": os.getenv("OPENROUTER_PRIMARY_MODEL", ""),
                  "memory_mode": "shared_ephemeral_chroma_sequential",
                  "fallback_models": [item.strip() for item in os.getenv("OPENROUTER_MODELS", "").split(",") if item.strip()],
                  "approval_policy": APPROVAL_POLICY_VERSION,
                  "knowledge_sha256": hashlib.sha256(KNOWLEDGE_PATH.read_bytes()).hexdigest(),
                  "results": completed}

    def save_checkpoint() -> None:
        pending_path = checkpoint_path.with_suffix(".pending")
        pending_path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
        pending_path.replace(checkpoint_path)

    def save_result(row: dict) -> None:
        completed.append(row)
        save_checkpoint()

    # A fresh Chroma collection is shared by this sequential run. It never
    # opens or modifies the developer's configured persistent memory store.
    evaluation_memory = LongTermMemory(
        ephemeral=True,
        collection_name=f"holdout_{uuid4().hex}",
    )
    if args.resume:
        for row in completed:
            summary = row.get("remembered_summary")
            if row.get("observed_outcome") == "simulated_sent" and isinstance(summary, str) and summary:
                evaluation_memory.add(
                    summary,
                    {"ticket_id": row["ticket_id"], "category": row.get("category", "unknown")},
                )
    save_checkpoint()
    remaining = [case for case in cases if case["ticket_id"] not in set(done_ids if args.resume else [])]
    print(
        f"Frozen holdout: {len(completed)} completed; {len(remaining)} remaining. "
        f"Shared ephemeral Chroma is enabled. Checkpoint: {checkpoint_path}",
        flush=True,
    )
    previous = os.environ.get("ZOHO_DESK_SEND_ENABLED")
    os.environ["ZOHO_DESK_SEND_ENABLED"] = "true"
    sender = FakeReplySender()
    try:
        if remaining:
            shared_client = OpenRouterClient()

            async def run_evaluation() -> None:
                await _run_graphs(
                    remaining,
                    evaluation_id=evaluation_id,
                    reply_sender=sender,
                    tool_overrides=holdout_tools,
                    on_result=save_result,
                    shared_client=shared_client,
                    evaluation_memory=evaluation_memory,
                )

            asyncio.run(run_evaluation())
    finally:
        if previous is None:
            os.environ.pop("ZOHO_DESK_SEND_ENABLED", None)
        else:
            os.environ["ZOHO_DESK_SEND_ENABLED"] = previous
    results = [next(row for row in completed if row["ticket_id"] == case["ticket_id"])
               for case in cases]
    from src.observability.logger import _LOG_PATH
    costs = costs_by_run_id({row["run_id"] for row in results}, Path(_LOG_PATH))
    model_usage = model_usage_by_run_id(
        {row["run_id"] for row in results}, Path(_LOG_PATH)
    )
    for row in results:
        row.update(costs[row["run_id"]])
    by_id = {row["id"]: row for row in source}
    for row in results:
        source_row = by_id[row["ticket_id"]]
        row.update({key: source_row[key] for key in (
            "expected_disposition", "required_evidence", "acceptable_answer",
            "critical_failure_tags", "scenario", "label_provenance",
        )})
        review = row.get("safety_review") or {}
        evidence_ids = review.get("evidence_ids") or []
        reply_type = evidence_ids[0] if len(evidence_ids) == 1 else None
        row["expected_template"] = knowledge["replies"].get(reply_type)
        row["injected_failure_source"] = (
            "order_lookup" if source_row["scenario"] == "provider_failure"
            and source_row["category"] in {"order_status", "damaged_item"} else None
        )
    report = {"evaluation_id": evaluation_id, "scope": "author_labeled_synthetic_holdout",
              "holdout_sha256": FROZEN_SHA256, "delivery_adapter": "fake",
              "memory_mode": "shared_ephemeral_chroma_sequential",
              "primary_model": os.getenv("OPENROUTER_PRIMARY_MODEL", ""),
              "fallback_models": [item.strip() for item in os.getenv("OPENROUTER_MODELS", "").split(",") if item.strip()],
              "knowledge_version": knowledge["version"],
              "knowledge_sha256": hashlib.sha256(KNOWLEDGE_PATH.read_bytes()).hexdigest(),
              "knowledge_review_status": knowledge["status"],
              "approval_policy": APPROVAL_POLICY_VERSION,
              "simulated_reply_count": sum(row["observed_outcome"] == "simulated_sent" for row in results),
              "measured_at": datetime.now(UTC).isoformat(),
              "results": results, "model_usage": model_usage,
              "metrics": summarize(results)}
    report["metrics"]["by_model"] = model_usage
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    destination = REPORTS_DIR / f"{evaluation_id}.json"
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps(report["metrics"], indent=2))
    print(f"Saved report: {destination}")
    return 2 if any(row.get("run_error") for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
