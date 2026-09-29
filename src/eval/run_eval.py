"""Run the TASK-18 ticket set through the graph with simulated delivery.

The benchmark injects a fake sender and never posts to Zoho. Use
``python -m src.eval.zoho_smoke`` for a separate, explicitly confirmed
single-ticket live delivery check. Use ``--report PATH`` to recompute metrics
offline without calling models or external services.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gc
import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv

from src.agent.graph import SUPERVISOR_RETRY_CAP, build_graph
from src.agent.reply_sender import ReplySender
from src.memory.long_term import LongTermMemory
from src.memory.short_term import ShortTermMemory
from src.openrouter_client import OpenRouterClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TICKETS_PATH = REPOSITORY_ROOT / "data" / "test_tickets" / "tickets.jsonl"
MANIFEST_PATH = REPOSITORY_ROOT / "data" / "test_tickets" / "manifest.csv"
LOG_PATH = REPOSITORY_ROOT / "data" / "logs" / "events.jsonl"
REPORTS_DIR = REPOSITORY_ROOT / "data" / "eval_reports"
PROGRESS_PATH = REPOSITORY_ROOT / "PROGRESS.md"
EXPECTED_CATEGORIES = {
    "order_status",
    "returns",
    "damaged_item",
    "billing_dispute",
    "general_question",
}
EXPECTED_OUTCOMES = {"auto_resolve", "escalate"}
LLM_EVENT_TYPE = "llm_call"


class EvaluationDataError(ValueError):
    """Raised when evaluation inputs are missing, malformed, or inconsistent."""


def load_cases(
    tickets_path: Path = TICKETS_PATH,
    manifest_path: Path = MANIFEST_PATH,
) -> list[dict[str, str]]:
    """Load and validate the ticket text and manifest as one ordered dataset."""
    manifest: dict[str, dict[str, str]] = {}
    with manifest_path.open(newline="", encoding="utf-8-sig") as manifest_file:
        reader = csv.DictReader(manifest_file)
        expected_columns = ["ticket_id", "category", "expected_outcome", "notes"]
        if reader.fieldnames != expected_columns:
            raise EvaluationDataError(
                f"Manifest columns must be exactly {expected_columns!r}."
            )
        for row in reader:
            ticket_id = (row.get("ticket_id") or "").strip()
            category = (row.get("category") or "").strip()
            outcome = (row.get("expected_outcome") or "").strip()
            if not ticket_id or ticket_id in manifest:
                raise EvaluationDataError("Manifest ticket IDs must be non-empty and unique.")
            if category not in EXPECTED_CATEGORIES:
                raise EvaluationDataError(f"Unknown category for {ticket_id}: {category!r}.")
            if outcome not in EXPECTED_OUTCOMES:
                raise EvaluationDataError(f"Unknown expected outcome for {ticket_id}: {outcome!r}.")
            manifest[ticket_id] = {
                "category": category,
                "expected_outcome": outcome,
                "notes": (row.get("notes") or "").strip(),
            }

    tickets: dict[str, str] = {}
    with tickets_path.open(encoding="utf-8") as tickets_file:
        for line_number, line in enumerate(tickets_file, start=1):
            if not line.strip():
                continue
            try:
                ticket = json.loads(line)
            except json.JSONDecodeError as error:
                raise EvaluationDataError(
                    f"Invalid ticket JSON on line {line_number}: {error}."
                ) from error
            if not isinstance(ticket, dict) or set(ticket) != {"ticket_id", "ticket_text"}:
                raise EvaluationDataError(
                    f"Ticket line {line_number} must contain only ticket_id and ticket_text."
                )
            ticket_id = ticket.get("ticket_id")
            ticket_text = ticket.get("ticket_text")
            if (
                not isinstance(ticket_id, str)
                or not ticket_id
                or ticket_id in tickets
                or not isinstance(ticket_text, str)
                or not ticket_text.strip()
            ):
                raise EvaluationDataError(
                    f"Ticket line {line_number} has a missing, duplicate, or invalid field."
                )
            tickets[ticket_id] = ticket_text

    if tickets.keys() != manifest.keys():
        missing_text = sorted(manifest.keys() - tickets.keys())
        missing_manifest = sorted(tickets.keys() - manifest.keys())
        raise EvaluationDataError(
            "Ticket and manifest IDs do not match; "
            f"missing ticket text={missing_text}, missing manifest rows={missing_manifest}."
        )

    return [
        {"ticket_id": ticket_id, "ticket_text": tickets[ticket_id], **manifest[ticket_id]}
        for ticket_id in manifest
    ]


class FakeReplySender:
    """Record simulated replies for evaluation without making network calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def send_public_reply(self, ticket_id: str, body: str) -> dict[str, Any]:
        self.calls.append({"ticket_id": ticket_id, "body": body})
        return {"simulated": True, "ticket_id": ticket_id, "http_status": None}


def _safe_cost(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else None


def costs_by_run_id(
    run_ids: set[str], log_path: Path = LOG_PATH
) -> dict[str, dict[str, Any]]:
    """Sum provider-reported LLM costs for selected run IDs, preserving gaps."""
    aggregate = {
        run_id: {"reported_cost": 0.0, "llm_calls": 0, "calls_missing_cost": 0}
        for run_id in run_ids
    }
    if not log_path.is_file():
        return aggregate
    with log_path.open(encoding="utf-8") as log_file:
        for line in log_file:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            run_id = event.get("run_id")
            if event.get("event_type") != LLM_EVENT_TYPE or run_id not in aggregate:
                continue
            entry = aggregate[run_id]
            entry["llm_calls"] += 1
            cost = _safe_cost(event.get("token_cost"))
            if cost is None:
                entry["calls_missing_cost"] += 1
            else:
                entry["reported_cost"] += cost
    for entry in aggregate.values():
        entry["total_cost"] = (
            entry["reported_cost"] if entry["calls_missing_cost"] == 0 else None
        )
        if entry["llm_calls"] == 0:
            entry["total_cost"] = None
    return aggregate


def workflow_errors_by_run_id(
    run_ids: set[str], log_path: Path = LOG_PATH
) -> dict[str, dict[str, str]]:
    """Find graph-level operational failures recorded in node events."""
    failures: dict[str, dict[str, str]] = {}
    if not log_path.is_file():
        return failures
    with log_path.open(encoding="utf-8") as log_file:
        for line in log_file:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            run_id = event.get("run_id")
            error = event.get("error")
            if (
                run_id in run_ids
                and event.get("event_type") == "node_transition"
                and isinstance(error, dict)
                and error.get("error_type")
            ):
                failures[run_id] = {
                    "node": str(error.get("node", event.get("name", "unknown"))),
                    "error_type": str(error["error_type"]),
                }
    return failures


def reconcile_workflow_errors(
    report: dict[str, Any], log_path: Path = LOG_PATH
) -> dict[str, Any]:
    """Mark older saved-report rows failed when JSONL shows workflow errors."""
    run_ids = {
        str(row["run_id"])
        for row in report.get("results", [])
        if isinstance(row, dict) and row.get("run_id")
    }
    failures = workflow_errors_by_run_id(run_ids, log_path)
    for row in report.get("results", []):
        failure = failures.get(str(row.get("run_id", "")))
        if not failure:
            continue
        row["workflow_error"] = failure
        row["run_error"] = failure["error_type"]
        row["observed_outcome"] = "failed"
        row["matches_expected"] = False
    return report


def _nearest_rank_p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def calculate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate dispositions and costs without rounding the source values."""
    total = len(results)
    if total == 0:
        raise ValueError("Cannot calculate evaluation metrics for an empty result set.")

    unscored = [row for row in results if row.get("run_error")]
    scored = [row for row in results if not row.get("run_error")]
    auto_cases = [row for row in scored if row["expected_outcome"] == "auto_resolve"]
    escalation_cases = [row for row in scored if row["expected_outcome"] == "escalate"]
    matched = [row for row in scored if row.get("matches_expected") is True]
    auto_escalated = [row for row in auto_cases if row.get("observed_outcome") == "escalated"]
    expected_escalated_sent = [
        row
        for row in escalation_cases
        if row.get("observed_outcome") in {"sent", "simulated_sent"}
    ]
    expected_escalated_escalated = [
        row for row in escalation_cases if row.get("observed_outcome") == "escalated"
    ]
    cap_failures = [
        row
        for row in scored
        if row.get("retry_count", 0) >= SUPERVISOR_RETRY_CAP
        and row.get("supervisor_status") == "FAIL"
    ]
    successful_costs = [row["total_cost"] for row in matched if row.get("total_cost") is not None]
    all_reported_costs = [row["reported_cost"] for row in results]
    missing_cost_tickets = sum(
        row.get("calls_missing_cost", 0) > 0 or row.get("llm_calls", 0) == 0
        for row in results
    )
    successful_costs_complete = all(
        row.get("total_cost") is not None for row in matched
    )

    return {
        "ticket_count": total,
        "scored_ticket_count": len(scored),
        "unscored_count": len(unscored),
        "matched_count": len(matched),
        "task_completion_rate": len(matched) / len(scored) if scored else None,
        "expected_auto_resolve_count": len(auto_cases),
        "auto_resolve_incorrect_escalation_count": len(auto_escalated),
        "auto_resolve_incorrect_escalation_rate": (
            len(auto_escalated) / len(auto_cases) if auto_cases else None
        ),
        "expected_escalate_count": len(escalation_cases),
        "expected_escalate_correct_count": len(expected_escalated_escalated),
        "escalation_recall": (
            len(expected_escalated_escalated) / len(escalation_cases)
            if escalation_cases
            else None
        ),
        "expected_escalate_incorrect_send_count": len(expected_escalated_sent),
        "expected_escalate_incorrect_send_rate": (
            len(expected_escalated_sent) / len(escalation_cases)
            if escalation_cases
            else None
        ),
        "mean_retries_to_success": (
            sum(row.get("retry_count", 0) for row in matched) / len(matched)
            if matched
            else None
        ),
        "failure_after_cap_count": len(cap_failures),
        "failure_after_cap_rate": len(cap_failures) / len(scored) if scored else None,
        "p95_latency_ms": _nearest_rank_p95(
            [float(row["latency_ms"]) for row in scored if row.get("latency_ms") is not None]
        ),
        "total_reported_token_cost": sum(all_reported_costs),
        "tickets_with_missing_token_cost": missing_cost_tickets,
        "cost_per_successful_run": (
            sum(successful_costs) / len(matched)
            if matched and successful_costs_complete
            else None
        ),
    }


def _report_result_path(report_id: str, reports_dir: Path = REPORTS_DIR) -> Path:
    return reports_dir / f"task19_{report_id}.json"


def _write_report(report: dict[str, Any], reports_dir: Path = REPORTS_DIR) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = _report_result_path(report["evaluation_id"], reports_dir)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report_path


def load_report(report_path: Path) -> dict[str, Any]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluationDataError(f"Could not read evaluation report {report_path}: {error}.") from error
    if not isinstance(report, dict) or not isinstance(report.get("results"), list):
        raise EvaluationDataError("Evaluation report must contain a results array.")
    reconcile_workflow_errors(report)
    report["metrics"] = calculate_metrics(report["results"])
    return report


def _format_fraction(numerator: int, denominator: int) -> str:
    return "not measurable (no scored tickets)" if denominator == 0 else f"{numerator}/{denominator} = {numerator / denominator!r}"


def print_report(report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    print(f"Evaluation ID: {report['evaluation_id']}")
    print(f"Mode: {report['mode']}; tickets: {metrics['ticket_count']}")
    print(f"Unscored workflow failures: {metrics['unscored_count']}")
    if report.get("delivery_adapter") == "fake":
        print("Delivery: simulated only; no public reply was sent.")
    print("\n| Ticket | Expected | Observed | Match | Retries | Latency ms | Reported cost | Missing-cost calls |")
    print("|---|---|---|---:|---:|---:|---:|---:|")
    for row in report["results"]:
        match = "yes" if row.get("matches_expected") else "no"
        cost = "unknown" if row.get("total_cost") is None else repr(row["total_cost"])
        print(
            f"| {row['ticket_id']} | {row['expected_outcome']} | {row['observed_outcome']} "
            f"| {match} | {row.get('retry_count', 0)} | {row.get('latency_ms')} "
            f"| {cost} | {row.get('calls_missing_cost', 0)} |"
        )
    print("\nMetrics (fraction values are computed by the harness):")
    print(
        "Overall completion rate among scored tickets: "
        + _format_fraction(metrics["matched_count"], metrics["scored_ticket_count"])
    )
    print(
        "Escalation recall: "
        + _format_fraction(metrics["expected_escalate_correct_count"], metrics["expected_escalate_count"])
    )
    print(
        "Incorrect escalation rate for auto-resolve tickets: "
        + _format_fraction(
            metrics["auto_resolve_incorrect_escalation_count"],
            metrics["expected_auto_resolve_count"],
        )
    )
    print(
        "Incorrect send rate for expected escalations: "
        + _format_fraction(
            metrics["expected_escalate_incorrect_send_count"], metrics["expected_escalate_count"]
        )
    )
    print(f"Mean retries-to-success: {metrics['mean_retries_to_success']!r}")
    if metrics["failure_after_cap_rate"] is None:
        print("Failure-after-cap rate: not measurable (no scored workflow runs)")
    else:
        print(
            f"Failure-after-cap rate: {metrics['failure_after_cap_count']}/"
            f"{metrics['scored_ticket_count']} = {metrics['failure_after_cap_rate']!r}"
        )
    if metrics["p95_latency_ms"] is None:
        print("p95 full-run latency (async graph): not measurable (no scored workflow runs)")
    else:
        print(f"p95 full-run latency (async graph): {metrics['p95_latency_ms']!r} ms")
    print(
        "Reported token-cost subtotal (incomplete when calls are missing): "
        f"{metrics['total_reported_token_cost']!r}"
    )
    print(f"Tickets with missing token cost: {metrics['tickets_with_missing_token_cost']}")
    print(f"Cost per successful run: {metrics['cost_per_successful_run']!r}")


async def _run_graphs(
    cases: list[dict[str, str]],
    *,
    evaluation_id: str,
    reply_sender: ReplySender,
) -> list[dict[str, Any]]:
    from src.observability.logger import _LOG_PATH

    run_ids = {
        case["ticket_id"]: f"task19-{evaluation_id}-{case['ticket_id']}"
        for case in cases
    }
    results: list[dict[str, Any]] = []
    llm_client = OpenRouterClient()

    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] Running {case['ticket_id']}...", flush=True)
        run_id = run_ids[case["ticket_id"]]
        simulated_ticket_id = f"SIMULATED-{case['ticket_id']}"
        started = time.perf_counter()
        graph_result: dict[str, Any] = {}
        run_error: str | None = None
        try:
            memory = LongTermMemory(ephemeral=True)
            graph = None
            try:
                graph = build_graph(
                    short_term_memory=ShortTermMemory(run_id),
                    long_term_memory=memory,
                    client=llm_client,
                    reply_sender=reply_sender,
                )
                graph_result = await graph.ainvoke(
                    {
                        "ticket_id": run_id,
                        "ticket_text": case["ticket_text"],
                        "zoho_ticket_id": simulated_ticket_id,
                    }
                )
            finally:
                del graph
                del memory
                gc.collect()
        except Exception as error:
            run_error = type(error).__name__
            print(f"  Graph run failed: {run_error}: {error}", flush=True)
        workflow_error = graph_result.get("workflow_error")
        if workflow_error:
            run_error = str(workflow_error.get("error_type", "workflow_error"))
            print(
                f"  Workflow failed at {workflow_error.get('node', 'unknown')}: {run_error}",
                flush=True,
            )
        latency_ms = (time.perf_counter() - started) * 1000
        observed_outcome = (
            "failed"
            if run_error
            else "simulated_sent"
            if graph_result.get("terminal_status") == "sent" and graph_result.get("response_sent")
            else "escalated"
            if graph_result.get("terminal_status") == "escalated"
            else "failed"
        )
        results.append(
            {
                "ticket_id": case["ticket_id"],
                "run_id": run_id,
                "category": case["category"],
                "expected_outcome": case["expected_outcome"],
                "observed_outcome": observed_outcome,
                "matches_expected": (
                    observed_outcome == "simulated_sent"
                    if case["expected_outcome"] == "auto_resolve"
                    else observed_outcome == "escalated"
                ),
                "retry_count": graph_result.get("retry_count", 0),
                "supervisor_status": graph_result.get("supervisor_status"),
                "zoho_delivery_status": graph_result.get("zoho_delivery_status"),
                "latency_ms": latency_ms,
                "run_error": run_error,
                "workflow_error": workflow_error,
                "reported_cost": 0.0,
                "total_cost": None,
                "llm_calls": 0,
                "calls_missing_cost": 0,
            }
        )

    costs = costs_by_run_id(set(run_ids.values()), Path(_LOG_PATH))
    for row in results:
        row.update(costs[row["run_id"]])
    return results


def update_progress(report: dict[str, Any], progress_path: Path = PROGRESS_PATH) -> None:
    """Write metric values from a complete simulated-delivery report."""
    if report.get("mode") != "simulated_delivery" or len(report.get("results", [])) != 25:
        raise EvaluationDataError(
            "Only a complete 25-ticket simulated-delivery report can update PROGRESS.md."
        )
    if any(row.get("run_error") for row in report["results"]):
        raise EvaluationDataError(
            "Cannot publish metrics from an evaluation with graph setup/run errors."
        )
    metrics = report.get("metrics") or calculate_metrics(report["results"])
    measured_date = report.get("measured_at", "")[:10]

    values = {
        "Unscored workflow failures": str(metrics["unscored_count"]),
        "Task completion rate (simulated delivery)": (
            f"{metrics['matched_count']}/{metrics['ticket_count']} = "
            f"{metrics['task_completion_rate']!r}"
        ),
        "Mean retries-to-success": repr(metrics["mean_retries_to_success"]),
        "Failure rate after cap": (
            f"{metrics['failure_after_cap_count']}/{metrics['ticket_count']} = "
            f"{metrics['failure_after_cap_rate']!r}"
        ),
        "p95 latency (sequential)": "Not measured: pending TASK-20",
        "p95 latency (async)": f"{metrics['p95_latency_ms']!r} ms",
        "Cost per successful run": repr(metrics["cost_per_successful_run"]),
        "Total reported token cost": repr(metrics["total_reported_token_cost"]),
        "Tickets with missing token cost": str(metrics["tickets_with_missing_token_cost"]),
        "Escalation recall": _format_fraction(
            metrics["expected_escalate_correct_count"], metrics["expected_escalate_count"]
        ),
        "Incorrect escalation rate (auto-resolve)": _format_fraction(
            metrics["auto_resolve_incorrect_escalation_count"],
            metrics["expected_auto_resolve_count"],
        ),
        "Incorrect send rate (expected escalation)": _format_fraction(
            metrics["expected_escalate_incorrect_send_count"], metrics["expected_escalate_count"]
        ),
        "Per-ticket reported token cost": "; ".join(
            f"{row['ticket_id']}="
            + (
                repr(row["total_cost"])
                if row.get("total_cost") is not None
                else f"unknown (reported subtotal={row.get('reported_cost')!r})"
            )
            for row in report["results"]
        ),
    }

    if metrics["mean_retries_to_success"] is None:
        values["Mean retries-to-success"] = "Not measurable: no tickets matched expected outcome"
    if metrics["cost_per_successful_run"] is None:
        reason = (
            "no tickets matched expected outcome"
            if metrics["matched_count"] == 0
            else "provider cost missing for at least one matching ticket"
        )
        values["Cost per successful run"] = f"Not measurable: {reason}"
    if metrics["tickets_with_missing_token_cost"]:
        values["Total reported token cost"] += (
            " (known subtotal; provider cost missing on "
            f"{metrics['tickets_with_missing_token_cost']} ticket(s))"
        )

    original_text = progress_path.read_text(encoding="utf-8")
    lines = original_text.splitlines()
    replaced: set[str] = set()
    for index, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] not in values:
            continue
        metric_name = cells[0]
        cells[1] = values[metric_name]
        cells[2] = measured_date if metric_name != "p95 latency (sequential)" else "Not measured"
        lines[index] = "| " + " | ".join(cells) + " |"
        replaced.add(metric_name)

    missing_rows = [
        f"| {metric_name} | {metric_value} | "
        f"{'Not measured' if metric_name == 'p95 latency (sequential)' else measured_date} |"
        for metric_name, metric_value in values.items()
        if metric_name not in replaced
    ]
    if missing_rows:
        table_end = next(
            (
                index
                for index, line in enumerate(lines)
                if index > 0 and line.strip() == "---"
            ),
            len(lines),
        )
        lines[table_end:table_end] = missing_rows

    lines.extend(
        [
            "",
            f"## [{measured_date}] TASK-19 full evaluation",
            "**Worked on:** TASK-19",
            f"**Completed:** Ran {len(report['results'])} tickets with simulated delivery; "
            f"{metrics['matched_count']} matched their expected disposition.",
            "**Blocked/open questions:** Sequential latency remains unmeasured until TASK-20. "
            f"{metrics['tickets_with_missing_token_cost']} tickets had at least one missing "
            "provider-reported token cost; those costs are not estimated.",
            "**Metrics measured this session:** See the tracker above and the saved report "
            f"`{report.get('report_path', '')}`.",
            "**Next session should start with:** TASK-20 sequential versus async latency comparison.",
        ]
    )
    progress_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        help="Recompute and display metrics from a saved report without external calls.",
    )
    args = parser.parse_args(argv)

    if args.report:
        report = load_report(args.report)
        print_report(report)
        return 0

    load_dotenv(REPOSITORY_ROOT / ".env")
    try:
        cases = load_cases()
        if len(cases) != 25:
            raise EvaluationDataError(f"Expected exactly 25 tickets; found {len(cases)}.")
    except EvaluationDataError as error:
        parser.error(str(error))

    evaluation_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    original_send_value = os.environ.get("ZOHO_DESK_SEND_ENABLED")
    os.environ["ZOHO_DESK_SEND_ENABLED"] = "true"
    fake_sender = FakeReplySender()
    try:
        print(
            "Evaluation uses a fake sender; it will not make Zoho requests or post public replies.",
            flush=True,
        )
        results = asyncio.run(
            _run_graphs(
                cases,
                evaluation_id=evaluation_id,
                reply_sender=fake_sender,
            )
        )
    finally:
        if original_send_value is None:
            os.environ.pop("ZOHO_DESK_SEND_ENABLED", None)
        else:
            os.environ["ZOHO_DESK_SEND_ENABLED"] = original_send_value

    report: dict[str, Any] = {
        "task": "TASK-19",
        "evaluation_id": evaluation_id,
        "mode": "simulated_delivery",
        "delivery_adapter": "fake",
        "simulated_reply_count": len(fake_sender.calls),
        "measured_at": datetime.now().astimezone().isoformat(),
        "ticket_count": len(cases),
        "results": results,
    }
    report["metrics"] = calculate_metrics(results)
    report["report_path"] = str(_report_result_path(evaluation_id).relative_to(REPOSITORY_ROOT))
    report_path = _write_report(report)
    print_report(report)
    print(f"Saved report: {report_path.relative_to(REPOSITORY_ROOT)}")

    if any(row.get("run_error") for row in results):
        print(
            "Metrics were not written: one or more graph runs failed before producing a disposition.",
            flush=True,
        )
        return 2
    update_progress(report)
    print(f"Updated metrics in {PROGRESS_PATH.relative_to(REPOSITORY_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
