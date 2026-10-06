import json
from io import StringIO
from pathlib import Path

import pytest

from src.eval.run_eval import (
    EvaluationDataError,
    FakeReplySender,
    calculate_metrics,
    costs_by_run_id,
    load_cases,
    load_report,
    model_usage_by_run_id,
    reconcile_workflow_errors,
    update_progress,
    workflow_errors_by_run_id,
)
from src.eval.zoho_smoke import SMOKE_REPLY, main as zoho_smoke_main


class MemoryPath:
    """Small in-memory path double for tests in restricted temp environments."""

    def __init__(self, text: str, *, exists: bool = True) -> None:
        self.text = text
        self.exists = exists

    def is_file(self) -> bool:
        return self.exists

    def open(self, *_args, **_kwargs):
        return StringIO(self.text)

    def read_text(self, **_kwargs) -> str:
        return self.text

    def write_text(self, text: str, **_kwargs) -> int:
        self.text = text
        return len(text)


def _make_cases(count: int = 2) -> list[dict[str, str]]:
    return [
        {
            "ticket_id": f"ticket_{index}",
            "ticket_text": f"Synthetic ticket {index}",
            "category": "order_status",
            "expected_outcome": "auto_resolve" if index == 0 else "escalate",
            "notes": "synthetic",
        }
        for index in range(count)
    ]


def test_load_real_ticket_set_has_50_matching_cases():
    cases = load_cases()

    assert len(cases) == 50
    assert len({case["ticket_id"] for case in cases}) == 50
    assert sum(case["expected_outcome"] == "auto_resolve" for case in cases) == 7
    assert sum(case["expected_outcome"] == "escalate" for case in cases) == 43
    assert {case["category"] for case in cases} == {
        "order_status", "returns", "damaged_item", "billing_dispute", "general_question"
    }
    assert all(sum(case["category"] == category for case in cases) == 10 for category in {
        "order_status", "returns", "damaged_item", "billing_dispute", "general_question"
    })
    assert [case["ticket_id"] for case in cases[:25]] == [
        f"{prefix}_{index:02d}"
        for prefix in ("order", "return", "damage", "billing", "general")
        for index in range(1, 6)
    ]
    assert [case["ticket_id"] for case in cases[25:]] == [
        f"{prefix}_{index:02d}"
        for prefix in ("order", "return", "damage", "billing", "general")
        for index in range(6, 11)
    ]


def test_live_evaluator_rejects_incomplete_dataset_before_model_calls(monkeypatch):
    from src.eval import run_eval

    monkeypatch.setattr(run_eval, "load_dotenv", lambda *_args: None)
    monkeypatch.setattr(run_eval, "load_cases", lambda: _make_cases(49))
    with pytest.raises(SystemExit) as error:
        run_eval.main([])
    assert error.value.code == 2


def test_new_ticket_labels_match_current_fixture_capabilities():
    from src.tools.order_data import load_orders
    from src.tools.faq_search import FAQ_ENTRIES

    historical_manifest = Path(__file__).resolve().parents[1] / "data" / "test_tickets" / "manifest.csv"
    cases = {case["ticket_id"]: case for case in load_cases(manifest_path=historical_manifest)}
    orders = load_orders()
    assert set(orders) == {f"ORD-{index}" for index in range(1001, 1007)}
    assert orders["ORD-1001"]["status"] == "shipped"
    assert orders["ORD-1005"]["status"] == "processing"
    assert orders["ORD-1002"]["delivered_days_ago"] == 12
    assert orders["ORD-1003"]["delivered_days_ago"] == 3
    assert orders["ORD-1004"]["delivered_days_ago"] == 45
    assert orders["ORD-1006"]["delivered_days_ago"] == 5
    assert {"shipping-delay", "payment-methods", "refund-timing"} <= {
        entry["id"] for entry in FAQ_ENTRIES
    }
    expected_new = {
        "order": ["auto_resolve", "auto_resolve", "escalate", "escalate", "escalate"],
        "return": ["auto_resolve", "auto_resolve", "auto_resolve", "escalate", "escalate"],
        "damage": ["auto_resolve", "auto_resolve", "auto_resolve", "escalate", "escalate"],
        "billing": ["escalate"] * 5,
        "general": ["auto_resolve", "auto_resolve", "auto_resolve", "escalate", "escalate"],
    }
    for prefix, outcomes in expected_new.items():
        for index, outcome in enumerate(outcomes, start=6):
            case = cases[f"{prefix}_{index:02d}"]
            assert case["expected_outcome"] == outcome
            assert case["notes"]
    for case in list(cases.values())[25:]:
        for token in case["ticket_text"].split():
            if token.startswith("ORD-"):
                assert token.rstrip("?.,") in orders or token.rstrip("?.,") == "ORD-9999"


@pytest.mark.asyncio
async def test_fake_reply_sender_records_simulated_delivery_without_network():
    sender = FakeReplySender()

    result = await sender.send_public_reply("SIMULATED-order_01", "Approved draft")

    assert result["simulated"] is True
    assert sender.calls == [
        {"ticket_id": "SIMULATED-order_01", "body": "Approved draft"}
    ]


def test_cost_aggregation_preserves_missing_provider_costs():
    events = [
        {"run_id": "run-a", "event_type": "llm_call", "token_cost": 0.125},
        {"run_id": "run-a", "event_type": "llm_call", "token_cost": None},
        {"run_id": "run-b", "event_type": "llm_call", "token_cost": 50.0},
        {"run_id": "run-a", "event_type": "tool_call", "token_cost": 100.0},
    ]
    log_path = MemoryPath("".join(json.dumps(event) + "\n" for event in events))

    result = costs_by_run_id({"run-a"}, log_path)["run-a"]
    assert result == {
        "reported_cost": 0.125,
        "llm_calls": 2,
        "calls_missing_cost": 1,
        "total_cost": None,
    }


def test_zero_model_calls_have_known_zero_provider_cost():
    result = costs_by_run_id({"faq-run"}, MemoryPath(""))["faq-run"]
    assert result == {
        "reported_cost": 0.0,
        "llm_calls": 0,
        "calls_missing_cost": 0,
        "total_cost": 0.0,
    }


def test_model_usage_is_grouped_by_actual_response_model_and_cost():
    events = [
        {"event_type": "llm_call", "run_id": "run-a", "inputs": {"model": "primary"},
         "output": {"model": "fallback-a"}, "token_cost": 0.25},
        {"event_type": "llm_call", "run_id": "run-a", "inputs": {"model": "primary"},
         "output": {"model": "fallback-a"}, "token_cost": None},
        {"event_type": "llm_call", "run_id": "run-b", "inputs": {"model": "primary"},
         "output": {"model": "primary"}, "token_cost": 0.5},
    ]
    log_path = MemoryPath("".join(json.dumps(event) + "\n" for event in events))

    assert model_usage_by_run_id({"run-a"}, log_path) == {
        "fallback-a": {"llm_calls": 2, "reported_cost": 0.25, "calls_missing_cost": 1}
    }


def test_logged_workflow_errors_are_not_scored_as_successful_escalations():
    log_path = MemoryPath(
        json.dumps(
            {
                "event_type": "node_transition",
                "run_id": "run-a",
                "name": "classify",
                "error": {"node": "classify", "error_type": "APIConnectionError"},
            }
        )
        + "\n"
    )
    report = {
        "results": [
            {
                "run_id": "run-a",
                "expected_outcome": "escalate",
                "observed_outcome": "escalated",
                "matches_expected": True,
                "retry_count": 0,
                "supervisor_status": None,
                "latency_ms": 10.0,
                "reported_cost": 0.0,
                "total_cost": None,
                "llm_calls": 1,
                "calls_missing_cost": 1,
            }
        ]
    }

    assert workflow_errors_by_run_id({"run-a"}, log_path) == {
        "run-a": {"node": "classify", "error_type": "APIConnectionError"}
    }
    reconciled = reconcile_workflow_errors(report, log_path)

    assert reconciled["results"][0]["observed_outcome"] == "failed"
    assert reconciled["results"][0]["matches_expected"] is False
    metrics = calculate_metrics(reconciled["results"])
    assert metrics["unscored_count"] == 1
    assert metrics["scored_ticket_count"] == 0
    assert metrics["task_completion_rate"] is None
    assert metrics["failure_after_cap_rate"] is None
    assert metrics["p95_latency_ms"] is None


def test_calculate_metrics_uses_expected_dispositions_and_nearest_rank_p95():
    results = [
        {
            "expected_outcome": "auto_resolve",
            "observed_outcome": "simulated_sent",
            "matches_expected": True,
            "retry_count": 1,
            "supervisor_status": "PASS",
            "latency_ms": 10.0,
            "reported_cost": 0.1,
            "total_cost": 0.1,
            "llm_calls": 1,
            "calls_missing_cost": 0,
        },
        {
            "expected_outcome": "auto_resolve",
            "observed_outcome": "escalated",
            "matches_expected": False,
            "retry_count": 3,
            "supervisor_status": "FAIL",
            "latency_ms": 20.0,
            "reported_cost": 0.2,
            "total_cost": 0.2,
            "llm_calls": 1,
            "calls_missing_cost": 0,
        },
        {
            "expected_outcome": "escalate",
            "observed_outcome": "escalated",
            "matches_expected": True,
            "retry_count": 0,
            "supervisor_status": "PASS",
            "latency_ms": 30.0,
            "reported_cost": 0.3,
            "total_cost": 0.3,
            "llm_calls": 1,
            "calls_missing_cost": 0,
        },
        {
            "expected_outcome": "escalate",
            "observed_outcome": "simulated_sent",
            "matches_expected": False,
            "retry_count": 0,
            "supervisor_status": "PASS",
            "latency_ms": 40.0,
            "reported_cost": 0.4,
            "total_cost": 0.4,
            "llm_calls": 1,
            "calls_missing_cost": 0,
        },
    ]

    metrics = calculate_metrics(results)
    assert metrics["task_completion_rate"] == 0.5
    assert metrics["escalation_recall"] == 0.5
    assert metrics["auto_resolve_incorrect_escalation_rate"] == 0.5
    assert metrics["expected_escalate_incorrect_send_rate"] == 0.5
    assert metrics["mean_retries_to_success"] == 0.5
    assert metrics["failure_after_cap_rate"] == 0.25
    assert metrics["p95_latency_ms"] == 40.0
    assert metrics["total_reported_token_cost"] == 1.0
    assert metrics["cost_per_successful_run"] == 0.2


def test_calculate_metrics_reports_cost_unavailable_if_no_matched_runs():
    metrics = calculate_metrics(
        [
            {
                "expected_outcome": "auto_resolve",
                "observed_outcome": "escalated",
                "matches_expected": False,
                "retry_count": 0,
                "supervisor_status": "PASS",
                "latency_ms": 12.0,
                "reported_cost": 0.2,
                "total_cost": 0.2,
                "llm_calls": 1,
                "calls_missing_cost": 0,
            }
        ]
    )
    assert metrics["cost_per_successful_run"] is None


def test_metrics_report_decision_errors_and_unsupported_reviews_by_category():
    results = [
        {
            "ticket_id": "order-risk",
            "category": "order_status",
            "expected_outcome": "escalate",
            "observed_outcome": "simulated_sent",
            "matches_expected": False,
            "retry_count": 0,
            "supervisor_status": "PASS",
            "supervisor_reason": {
                "checks": [
                    {"id": "no_unsupported_claims", "passed": False, "reason": "unsupported"}
                ]
            },
            "failed_attempts": [],
            "safety_review": {"send_allowed": False},
            "latency_ms": 1.0,
            "reported_cost": 0.0,
            "total_cost": 0.0,
            "llm_calls": 1,
            "calls_missing_cost": 0,
        },
        {
            "ticket_id": "faq-safe",
            "category": "general_question",
            "expected_outcome": "auto_resolve",
            "observed_outcome": "escalated",
            "matches_expected": False,
            "retry_count": 3,
            "supervisor_status": "FAIL",
            "supervisor_reason": {"checks": []},
            "failed_attempts": [],
            "safety_review": {"send_allowed": True},
            "latency_ms": 2.0,
            "reported_cost": 0.0,
            "total_cost": 0.0,
            "llm_calls": 1,
            "calls_missing_cost": 0,
        },
    ]

    metrics = calculate_metrics(results)

    assert metrics["false_send_count"] == 1
    assert metrics["missed_escalation_count"] == 1
    assert metrics["false_escalation_count"] == 1
    assert metrics["unsupported_claim_review_count"] == 1
    assert metrics["safety_gate_violation_count"] == 1
    assert metrics["by_category"]["order_status"]["false_sends"] == 1
    assert metrics["by_category"]["order_status"]["unsupported_claim_reviews"] == 1
    assert metrics["by_category"]["general_question"]["false_escalations"] == 1


def test_metrics_report_category_accuracy_and_priority_distribution():
    metrics = calculate_metrics([
        {
            "ticket_id": "case-1",
            "category": "order_status",
            "predicted_category": "order status",
            "urgency": "high",
            "priority": "P1",
            "expected_outcome": "escalate",
            "observed_outcome": "escalated",
            "matches_expected": True,
            "latency_ms": 1.0,
            "reported_cost": 0.0,
            "total_cost": 0.0,
        },
        {
            "ticket_id": "case-2",
            "category": "general_question",
            "predicted_category": "order status",
            "urgency": "low",
            "priority": "P3",
            "expected_outcome": "auto_resolve",
            "observed_outcome": "simulated_sent",
            "matches_expected": True,
            "latency_ms": 1.0,
            "reported_cost": 0.0,
            "total_cost": 0.0,
        },
    ])

    assert metrics["category_classification"] == {
        "measured_count": 2,
        "correct_count": 1,
        "accuracy": 0.5,
        "urgency_distribution": {"high": 1, "medium": 0, "low": 1},
        "priority_distribution": {"P1": 1, "P2": 0, "P3": 1},
    }


def test_report_recomputes_metrics_offline():
    report_path = MemoryPath(
        json.dumps(
            {
                "evaluation_id": "saved",
                "mode": "simulated_delivery",
                "results": [
                    {
                        "expected_outcome": "escalate",
                        "observed_outcome": "escalated",
                        "matches_expected": True,
                        "retry_count": 0,
                        "supervisor_status": "PASS",
                        "latency_ms": 15.0,
                        "reported_cost": 0.12,
                        "total_cost": 0.12,
                        "llm_calls": 2,
                        "calls_missing_cost": 0,
                    }
                ],
            }
        )
    )

    loaded = load_report(report_path)
    assert loaded["metrics"]["task_completion_rate"] == 1.0
    assert loaded["metrics"]["p95_latency_ms"] == 15.0


def test_historical_25_ticket_report_remains_readable_offline():
    report = {
        "evaluation_id": "historical-25",
        "mode": "simulated_delivery",
        "results": [
            {
                "ticket_id": f"historical_{index}",
                "expected_outcome": "escalate",
                "observed_outcome": "escalated",
                "matches_expected": True,
                "retry_count": 0,
                "supervisor_status": "PASS",
                "latency_ms": float(index + 1),
                "reported_cost": 0.01,
                "total_cost": 0.01,
                "llm_calls": 1,
                "calls_missing_cost": 0,
            }
            for index in range(25)
        ],
    }
    loaded = load_report(MemoryPath(json.dumps(report)))
    assert loaded["metrics"]["ticket_count"] == 25
    assert loaded["metrics"]["matched_count"] == 25


def test_progress_update_requires_full_simulated_delivery_report():
    progress_path = MemoryPath(
        "| Metric | Value | Date measured |\n"
        "|---|---|---|\n"
        "| Task completion rate (simulated delivery) | — | — |\n",
    )
    report = {"mode": "dry_run", "results": []}

    with pytest.raises(EvaluationDataError, match="complete 50-ticket simulated-delivery"):
        update_progress(report, progress_path)


def test_progress_update_rejects_graph_setup_failures():
    report = {
        "mode": "simulated_delivery",
        "results": [{"run_error": "PermissionError"} for _ in range(50)],
    }
    with pytest.raises(EvaluationDataError, match="graph setup/run errors"):
        update_progress(report, MemoryPath("original progress"))


@pytest.mark.parametrize("invalid_row", [{"ticket_id": "ticket_0", "observed_outcome": "failed"},
                                        {"ticket_id": "ticket_1", "observed_outcome": "simulated_sent"}])
def test_progress_update_rejects_incomplete_or_duplicate_results(invalid_row):
    rows = [
        {"ticket_id": f"ticket_{index}", "observed_outcome": "escalated"}
        for index in range(50)
    ]
    rows[0] = invalid_row
    report = {"mode": "simulated_delivery", "results": rows}
    with pytest.raises(EvaluationDataError, match="incomplete or duplicate"):
        update_progress(report, MemoryPath("original progress"))


def test_progress_update_copies_computed_live_metrics():
    progress_path = MemoryPath(
        "# Progress\n\n## Metrics tracker\n"
        "**Current metrics provenance:** Latest completed 25-ticket simulated run; expanded 50-ticket metrics are unmeasured.\n"
        "| Metric | Value | Date measured |\n"
        "|---|---|---|\n"
        "| Task completion rate (simulated delivery) | — | — |\n"
        "| Mean retries-to-success | — | — |\n"
        "| Failure rate after cap | — | — |\n"
        "| p95 latency (sequential) | — | — |\n"
        "| p95 latency (async) | — | — |\n"
        "| Cost per successful run | — | — |\n"
    )
    results = [
        {
            "ticket_id": f"ticket_{index}",
            "expected_outcome": "escalate",
            "observed_outcome": "escalated",
            "matches_expected": True,
            "retry_count": 0,
            "supervisor_status": "PASS",
            "latency_ms": float(index + 1),
            "reported_cost": 0.01,
            "total_cost": 0.01,
            "llm_calls": 1,
            "calls_missing_cost": 0,
        }
        for index in range(50)
    ]
    report = {
        "mode": "simulated_delivery",
        "measured_at": "2026-09-30T00:00:00+00:00",
        "results": results,
    }

    update_progress(report, progress_path)

    assert "| Task completion rate (simulated delivery) | 50/50 = 1.0 | 2026-09-30 |" in progress_path.text
    assert "| p95 latency (sequential) | Not measured: pending TASK-20 | Not measured |" in progress_path.text
    assert "| p95 latency (async) | 48.0 ms | 2026-09-30 |" in progress_path.text
    assert "## [2026-09-30] TASK-29 informational-only full evaluation" in progress_path.text
    assert "**Current metrics provenance:** Complete 50-ticket simulated graph run under informational-only labels, measured on 2026-09-30." in progress_path.text
    assert progress_path.text.index("| False sends |") > progress_path.text.index("| Metric | Value | Date measured |")


def test_manifest_and_ticket_ids_must_match():
    manifest_path = MemoryPath(
        "ticket_id,category,expected_outcome,notes\n"
        "ticket_0,order_status,auto_resolve,ok\n",
    )
    tickets_path = MemoryPath(
        json.dumps({"ticket_id": "different", "ticket_text": "Text"}) + "\n"
    )

    with pytest.raises(EvaluationDataError, match="IDs do not match"):
        load_cases(tickets_path, manifest_path)


def test_zoho_smoke_does_not_send_without_explicit_send(monkeypatch):
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "true")
    factory_calls = []

    assert (
        zoho_smoke_main(
            ["--ticket-id", "12345"],
            client_factory=lambda: factory_calls.append("created"),
            confirm_input=lambda _prompt: "12345",
        )
        == 0
    )
    assert factory_calls == []


def test_zoho_smoke_requires_exact_ticket_confirmation(monkeypatch):
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "true")
    factory_calls = []

    assert (
        zoho_smoke_main(
            ["--ticket-id", "12345", "--send"],
            client_factory=lambda: factory_calls.append("created"),
            confirm_input=lambda prompt: (
                "CONTROLLED" if prompt.startswith("Type CONTROLLED") else "12346"
            ),
        )
        == 2
    )
    assert factory_calls == []


def test_zoho_smoke_posts_at_most_one_fixed_reply_after_confirmation(
    monkeypatch,
):
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "true")
    events = []

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def send_public_reply(self, ticket_id: str, body: str):
            self.calls.append((ticket_id, body))
            return {"http_status": 200}

    client = FakeClient()
    monkeypatch.setattr("src.eval.zoho_smoke.log_tool_event", lambda **event: events.append(event))

    result = zoho_smoke_main(
        ["--ticket-id", "12345", "--send"],
        client_factory=lambda: client,
        confirm_input=lambda prompt: (
            "CONTROLLED" if prompt.startswith("Type CONTROLLED") else "12345"
        ),
    )

    assert result == 0
    assert client.calls == [("12345", SMOKE_REPLY)]
    assert len(events) == 1
    assert "body" not in events[0]["inputs"]
    assert events[0]["error"] is None
