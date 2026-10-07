import asyncio
import inspect
import json

import pytest

from src.agent.graph import build_graph, dispatch_fact_tools
from src.eval import compare_tool_dispatch as comparison


def test_default_and_invalid_mode():
    assert inspect.signature(build_graph).parameters["tool_dispatch_mode"].default == "concurrent"
    with pytest.raises(ValueError, match="tool_dispatch_mode"):
        build_graph(short_term_memory=None, long_term_memory=None, tool_dispatch_mode="invalid")


def test_concurrent_overlap():
    async def scenario():
        started = set()
        ready = asyncio.Event()

        async def call(index):
            started.add(index)
            if len(started) == 3:
                ready.set()
            await asyncio.wait_for(ready.wait(), timeout=1)
            return index

        assert await dispatch_fact_tools([call(i) for i in range(3)], mode="concurrent") == [0, 1, 2]
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["sequential", "concurrent"])
def test_failure_capture_and_order(mode):
    async def scenario():
        order = []

        async def call(index):
            order.append((index, "start"))
            await asyncio.sleep(0)
            order.append((index, "end"))
            if index == 1:
                raise ValueError("fixture unavailable")
            return index

        results = await dispatch_fact_tools([call(i) for i in range(3)], mode=mode)
        assert results[0] == 0 and isinstance(results[1], ValueError) and results[2] == 2
        if mode == "sequential":
            assert order == [(i, phase) for i in range(3) for phase in ("start", "end")]
    asyncio.run(scenario())


def row(index, latency):
    return {"ticket_id": str(index), "run_id": f"run-{index}", "expected_outcome": "escalate",
            "observed_outcome": "escalated", "matches_expected": True,
            "latency_ms": latency, "reported_cost": 0.01, "total_cost": 0.01,
            "llm_calls": 2, "retry_count": 0}


def test_summary_bypass_reduction_and_incomplete():
    report = {"batches": {"sequential": [row(i, i + 100) for i in range(50)],
                           "concurrent": [row(i, i + 50) for i in range(50)]}}
    for mode in report["batches"]:
        for item in report["batches"][mode]:
            item["gather_facts_ms"] = 20
        report["batches"][mode][0]["dispatch_ms"] = 2
    summary = comparison.summarize(report)
    assert summary["publishable"]
    assert summary["sequential"]["bypass_count"] == 49
    assert summary["sequential"]["dispatch_p95_ms"] == 2
    assert summary["full_run_reduction_percent"] == 100 * (147 - 97) / 147
    assert comparison.reduction(10, 20) == -100
    assert comparison.reduction(0, 20) is None
    assert comparison.reduction(None, 20) is None
    report["batches"]["concurrent"].pop()
    assert not comparison.summarize(report)["publishable"]
    assert comparison.summarize(report)["full_run_reduction_percent"] is None


def test_offline_recompute(tmp_path, monkeypatch, capsys):
    report = {"batches": {mode: [row(i, 100) for i in range(50)]
                           for mode in ("sequential", "concurrent")}}
    path = tmp_path / "report.json"
    comparison.save(report, path)
    monkeypatch.setattr(comparison, "run_comparison", lambda *args: pytest.fail("live call"))
    assert comparison.main(["--report", str(path)]) == 0
    assert json.loads(capsys.readouterr().out) == report["summary"]


def test_empty_and_first_checkpoint_are_persistable(tmp_path):
    report = {"batches": {"sequential": [], "concurrent": []}}
    path = tmp_path / "checkpoint.json"
    comparison.save(report, path)
    assert json.loads(path.read_text())["summary"]["concurrent"]["metrics"] is None
    report["batches"]["sequential"].append(row(0, 100))
    comparison.save(report, path)
    saved = json.loads(path.read_text())
    assert len(saved["batches"]["sequential"]) == 1
    assert not saved["summary"]["publishable"]
    assert saved["summary"]["full_run_reduction_percent"] is None


def test_timing_log_filter(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('\n'.join(["bad", json.dumps({"run_id": "a", "event_type": "tool_dispatch", "latency_ms": 1}),
                              json.dumps({"run_id": "b", "event_type": "tool_dispatch", "latency_ms": 9})]))
    assert comparison.timings({"a", "c"}, path) == {"a": {"dispatch_ms": 1}, "c": {}}


def test_progress_updates_only_comparison_rows(tmp_path):
    report = {"measured_at": "2026-10-07", "batches": {
        "sequential": [row(i, 100) for i in range(50)],
        "concurrent": [row(i, 90) for i in range(50)]}}
    progress = tmp_path / "PROGRESS.md"
    original = ("| Accuracy | historical | date |\n"
                "| p95 latency (sequential) | pending | unknown |\n"
                "| p95 latency (async) | old | old |\n\nHistorical:\n"
                "| p95 latency (async) | preserve | old |\n")
    progress.write_text(original)
    comparison.publish_progress(report, "report.json", progress)
    text = progress.read_text()
    assert "| Accuracy | historical | date |" in text
    assert "| p95 latency (async) | preserve | old |" in text
    assert "10.0%" in text
    report["batches"]["concurrent"] = []
    with pytest.raises(ValueError, match="complete"):
        comparison.publish_progress(report, "report.json", progress)
    assert progress.read_text() == text


def test_batches_use_fake_sender_separate_memory_and_one_client(tmp_path, monkeypatch):
    monkeypatch.setattr(comparison.evaluation, "load_cases", lambda: [row(i, 10) for i in range(50)])
    monkeypatch.setattr(comparison, "configuration", lambda: {"rag": {"enabled": False}})
    client = object()
    monkeypatch.setattr(comparison.evaluation, "OpenRouterClient", lambda: client)
    calls = []

    async def fake_run(cases, **kwargs):
        assert isinstance(kwargs["reply_sender"], comparison.evaluation.FakeReplySender)
        assert kwargs["shared_client"] is client
        assert "evaluation_memory" not in kwargs  # _run_graphs creates a fresh ephemeral store per call
        calls.append(kwargs)
        return []

    monkeypatch.setattr(comparison.evaluation, "_run_graphs", fake_run)
    report = {"comparison_id": "test", "batches": {"sequential": [], "concurrent": []}}
    asyncio.run(comparison.run_comparison(report, tmp_path / "report.json"))
    assert [c["tool_dispatch_mode"] for c in calls] == ["sequential", "concurrent"]
    assert calls[0]["reply_sender"] is not calls[1]["reply_sender"]
    assert calls[0]["evaluation_id"] != calls[1]["evaluation_id"]
