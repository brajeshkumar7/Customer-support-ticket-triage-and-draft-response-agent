"""Evaluate the historical fixture-backed safety rules using offline cases.

Run with ``python -m src.eval.run_safety_regressions``. This does not call an
LLM, Zoho, or any external provider. The current graph uses the shared
informational-only policy in production_policy.py instead; this runner remains
for comparing the old fixture-backed rule with saved historical reports.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.agent.safety import decide_send_safety

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SAFETY_CASES_PATH = REPOSITORY_ROOT / "data" / "test_tickets" / "safety_regressions.jsonl"


def load_safety_cases(path: Path = SAFETY_CASES_PATH) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as case_file:
        for line_number, line in enumerate(case_file, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON on safety-case line {line_number}.") from error
            required = {
                "case_id", "category", "ticket_text", "order_id", "tool_results",
                "expected_safety_status", "expected_findings", "required_evidence",
                "acceptable_response", "acceptable_terminal_outcome",
            }
            if not isinstance(item, dict) or set(item) != required:
                raise ValueError(f"Safety-case line {line_number} has invalid fields.")
            case_id = item["case_id"]
            if not isinstance(case_id, str) or not case_id or case_id in seen:
                raise ValueError(f"Safety-case line {line_number} has an invalid/duplicate case_id.")
            if item["expected_safety_status"] not in {"blocked", "send_allowed"}:
                raise ValueError(f"Safety-case {case_id} has an unsupported expected status.")
            if not isinstance(item["expected_findings"], list):
                raise ValueError(f"Safety-case {case_id} expected_findings must be a list.")
            seen.add(case_id)
            cases.append(item)
    if not cases:
        raise ValueError("Safety regression set is empty.")
    return cases


def evaluate_safety_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    by_category: dict[str, dict[str, int]] = defaultdict(
        lambda: {"attempted": 0, "false_sends": 0, "false_escalations": 0, "matches": 0}
    )
    for case in cases:
        decision = decide_send_safety(
            ticket_text=case["ticket_text"],
            category=case["category"],
            order_id=case["order_id"],
            tool_results=case["tool_results"],
        )
        actual_status = decision["status"]
        expected_status = case["expected_safety_status"]
        actual_codes = {finding["code"] for finding in decision["findings"]}
        expected_codes = set(case["expected_findings"])
        status_match = actual_status == expected_status
        finding_match = actual_codes == expected_codes
        category = case["category"]
        category_result = by_category[category]
        category_result["attempted"] += 1
        category_result["matches"] += status_match and finding_match
        category_result["false_sends"] += expected_status == "blocked" and decision["send_allowed"]
        category_result["false_escalations"] += expected_status == "send_allowed" and not decision["send_allowed"]
        rows.append(
            {
                "case_id": case["case_id"],
                "category": category,
                "expected_safety_status": expected_status,
                "actual_safety_status": actual_status,
                "expected_findings": sorted(expected_codes),
                "actual_findings": sorted(actual_codes),
                "required_evidence": case["required_evidence"],
                "acceptable_response": case["acceptable_response"],
                "acceptable_terminal_outcome": case["acceptable_terminal_outcome"],
                "matches": status_match and finding_match,
            }
        )
    false_sends = sum(row["expected_safety_status"] == "blocked" and row["actual_safety_status"] == "send_allowed" for row in rows)
    false_escalations = sum(row["expected_safety_status"] == "send_allowed" and row["actual_safety_status"] == "blocked" for row in rows)
    missed_escalations = sum(row["expected_safety_status"] == "blocked" and row["actual_safety_status"] != "blocked" for row in rows)
    return {
        "attempted": len(rows),
        "matched": sum(row["matches"] for row in rows),
        "false_sends": false_sends,
        "missed_escalations": missed_escalations,
        "false_escalations": false_escalations,
        "by_category": dict(by_category),
        "results": rows,
    }


def main() -> int:
    report = evaluate_safety_cases(load_safety_cases())
    print("Historical fixture-backed safety gate regression (offline; not the current approval rule)")
    print("| Case | Category | Expected | Actual | Findings | Match |")
    print("|---|---|---|---|---|---:|")
    for row in report["results"]:
        print(
            f"| {row['case_id']} | {row['category']} | {row['expected_safety_status']} "
            f"| {row['actual_safety_status']} | {', '.join(row['actual_findings']) or '—'} "
            f"| {'yes' if row['matches'] else 'no'} |"
        )
    print(
        f"Summary: {report['matched']}/{report['attempted']} exact rule outcomes; "
        f"false sends={report['false_sends']}; missed escalations={report['missed_escalations']}; "
        f"false escalations={report['false_escalations']}."
    )
    print("By category:")
    print(json.dumps(report["by_category"], indent=2, sort_keys=True))
    return 0 if report["matched"] == report["attempted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
