"""Export a synthetic evaluation report without ticket bodies or draft text."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def public_measurement(report: dict, *, report_sha256: str) -> dict:
    rows = report.get("results")
    if not isinstance(rows, list) or not rows:
        raise ValueError("A complete saved report with case results is required.")
    if any(row.get("run_error") for row in rows):
        raise ValueError("Unscored graph failures prevent a complete public measurement.")
    expected_count = 200 if report.get("scope") == "author_labeled_synthetic_holdout" else 50
    if len(rows) != expected_count:
        raise ValueError(f"Expected {expected_count} case results, found {len(rows)}.")
    safe_keys = (
        "ticket_id", "run_id", "category", "expected_outcome", "expected_disposition",
        "observed_outcome", "matches_expected", "retry_count", "supervisor_status",
        "latency_ms", "reported_cost", "total_cost", "llm_calls", "calls_missing_cost",
        "scenario", "false_send", "false_escalation", "evidence_covered",
        "unsupported_public_claim", "critical_failure_tags",
    )
    cases = []
    for row in rows:
        case = {key: row[key] for key in safe_keys if key in row}
        review = row.get("safety_review") or {}
        case["reason_code"] = review.get("reason_code")
        case["evidence_ids"] = review.get("evidence_ids") or []
        cases.append(case)
    return {
        "evaluation_id": report.get("evaluation_id"),
        "scope": report.get("scope", report.get("task")),
        "approval_policy": report.get("approval_policy"),
        "label_file": report.get("label_file"),
        "holdout_sha256": report.get("holdout_sha256"),
        "knowledge_sha256": report.get("knowledge_sha256"),
        "model": report.get("primary_model"),
        "delivery_adapter": report.get("delivery_adapter"),
        "measured_at": report.get("measured_at"),
        "source_report_sha256": report_sha256,
        "metrics": report.get("metrics"),
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Replace an existing derived public measurement file.",
    )
    args = parser.parse_args()
    payload = args.report.read_bytes()
    measurement = public_measurement(
        json.loads(payload.decode("utf-8")),
        report_sha256=hashlib.sha256(payload).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w" if args.overwrite else "x", encoding="utf-8") as target:
        json.dump(measurement, target, indent=2)
    print(args.output)


if __name__ == "__main__":
    main()
