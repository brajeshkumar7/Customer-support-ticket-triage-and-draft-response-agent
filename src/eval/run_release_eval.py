"""Offline release-gate evaluation of reviewed controlled-reply cases.

Input JSONL rows: id, category, ticket_text, expected_disposition,
reviewed_by, reviewed_at. This command never calls Zoho or OpenRouter.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

from src.agent.production_policy import approved_knowledge, decide_public_reply

CATEGORIES = {"order_status", "returns", "damaged_item", "billing_dispute", "general_question"}
DISPOSITIONS = {"informational", "human"}


def load_reviewed_cases(path: Path) -> list[dict]:
    cases = []
    ids = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key].strip()
            for key in ("id", "category", "ticket_text", "expected_disposition", "reviewed_by", "reviewed_at")):
            raise ValueError(f"Case line {number} lacks a complete human review record.")
        if item["id"] in ids or item["category"] not in CATEGORIES or item["expected_disposition"] not in DISPOSITIONS:
            raise ValueError(f"Case line {number} has a duplicate ID or unsupported label.")
        ids.add(item["id"])
        cases.append(item)
    if len(cases) < 200 or any(sum(case["category"] == category for case in cases) < 20 for category in CATEGORIES):
        raise ValueError("Release evaluation requires at least 200 reviewed cases and 20 per category.")
    return cases


def evaluate(cases: list[dict], knowledge: dict) -> dict:
    rows = []
    for case in cases:
        started = time.perf_counter()
        decision = decide_public_reply(case["ticket_text"], knowledge=knowledge)
        elapsed_ms = (time.perf_counter() - started) * 1000
        predicted = decision.kind
        expected = case["expected_disposition"]
        rows.append({"id": case["id"], "category": case["category"],
                     "expected": expected, "actual": predicted,
                     "reason": decision.reason, "latency_ms": elapsed_ms,
                     "false_send": predicted == "informational" and expected == "human",
                     "false_escalation": predicted == "human" and expected == "informational",
                     "model_calls": 0, "token_cost": 0})
    count = len(rows)
    by_category = {}
    for category in CATEGORIES:
        group = [row for row in rows if row["category"] == category]
        by_category[category] = {
            "cases": len(group), "correct": sum(row["expected"] == row["actual"] for row in group),
            "false_sends": sum(row["false_send"] for row in group),
            "false_escalations": sum(row["false_escalation"] for row in group),
        }
    latencies = sorted(row["latency_ms"] for row in rows)
    p95 = latencies[math.ceil(count * 0.95) - 1] if count else None
    return {"measurement_scope": "offline_deterministic_policy_only",
            "case_count": count, "correct": sum(row["expected"] == row["actual"] for row in rows),
            "false_sends": sum(row["false_send"] for row in rows),
            "false_escalations": sum(row["false_escalation"] for row in rows),
            "wrong_recipient_sends": "not measured offline",
            "duplicate_sends": "not measured offline",
            "unsupported_claims": "not measured offline",
            "arrival_to_reply_latency": "not measured offline",
            "p95_decision_latency_ms": p95,
            "model_calls": 0, "token_cost": 0,
            "by_category": by_category, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = load_reviewed_cases(args.cases)
    result = evaluate(cases, approved_knowledge())
    if args.out.exists():
        parser.error("Output report already exists; use a new path for each run.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2))


if __name__ == "__main__":
    main()
