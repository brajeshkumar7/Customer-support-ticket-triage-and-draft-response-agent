"""Measure Jev checklist decisions on author-labeled development drafts.

This small visible set is not an independent holdout or a release gate.
No graph delivery adapter or Zoho client is instantiated.
"""

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from src.agent.supervisor import (
    parse_supervisor_decision, supervisor_configuration, supervisor_questions,
)
from src.openrouter_client import OpenRouterClient


def review_cases():
    cases = []
    for name, status in (("shipped", "In transit"), ("processing", "Preparing shipment"),
                         ("delivered", "Delivered")):
        evidence = {"order_lookup": {"ok": True, "data": {
            "order_id": "ORD-1001", "status": name, "tracking_status": status}}}
        for variant, draft, expected in (
            ("supported", f"According to the local mock lookup, ORD-1001 is {name}.", "PASS"),
            ("unsupported", "Your refund has been issued and will arrive tomorrow.", "FAIL"),
            ("insufficient", "Your parcel will arrive tomorrow.", "FAIL"),
        ):
            cases.append({"case_id": f"{name}-{variant}", "label": variant,
                          "expected_status": expected,
                          "state": {"ticket_text": "Please check my order ORD-1001.",
                                    "urgency": "low", "draft_response": draft,
                                    "tool_results": evidence, "cited_reference_guidance": [],
                                    "evidence_boundaries": "Order lookup is fictional local simulation, not real business authority."}})
    return cases


async def evaluate():
    load_dotenv(".env")
    config = supervisor_configuration()
    client = OpenRouterClient()
    evaluation_id = "task38_reviews_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    rows = []
    for case in review_cases():
        started = time.perf_counter()
        run_id = evaluation_id + "-" + case["case_id"]
        print("Reviewing " + case["case_id"], flush=True)
        try:
            response = await client.create_decision(model=config["model"], state=case["state"],
                questions=supervisor_questions(), run_id=run_id, call_name="supervisor_review")
            status, reason = parse_supervisor_decision(response)
            row = {**case, "run_id": run_id, "status": status, "reason": reason, "response": response}
        except Exception as error:
            row = {**case, "run_id": run_id, "status": "UNSCORED", "error": type(error).__name__}
        row["latency_ms"] = (time.perf_counter() - started) * 1000
        rows.append(row)
        print(case["case_id"] + ": " + row["status"], flush=True)
    # Cost comes exclusively from logged provider-reported usage, never estimates.
    from src.eval.run_eval import costs_by_run_id, _nearest_rank_p95
    costs = costs_by_run_id({row["run_id"] for row in rows})
    for row in rows:
        row["logged_cost"] = costs[row["run_id"]]
    scored = [row for row in rows if row["status"] != "UNSCORED"]
    report = {"evaluation_id": evaluation_id, "label_status": "author_labeled_visible_development_set",
              "supervisor_configuration": config, "results": rows,
              "summary": {"scored": len(scored), "total": len(rows),
                          "accuracy": sum(r["status"] == r["expected_status"] for r in scored) / len(scored) if scored else None,
                          "false_acceptances": sum(r["status"] == "PASS" and r["expected_status"] == "FAIL" for r in scored),
                          "false_rejections": sum(r["status"] == "FAIL" and r["expected_status"] == "PASS" for r in scored),
                          "p95_latency_ms": _nearest_rank_p95([row["latency_ms"] for row in rows]),
                          "provider_reported_cost": sum(row["logged_cost"]["reported_cost"] for row in rows),
                          "total_cost": (sum(row["logged_cost"]["total_cost"] for row in rows)
                                         if all(row["logged_cost"].get("total_cost") is not None for row in rows) else None)}}
    path = Path("data/eval_reports") / (evaluation_id + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print("Report: " + str(path))
    return 0 if len(scored) == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(evaluate()))
