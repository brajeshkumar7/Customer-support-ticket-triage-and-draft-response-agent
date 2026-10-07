"""Compare two live 50-case batches with fake delivery; --report recomputes offline."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, UTC
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from src.eval import run_eval as evaluation
from src.knowledge.store import rag_configuration
from src.knowledge.policy import policy_configuration
from src.tools.knowledge_search import KnowledgeSearchTool
from src.agent.supervisor import supervisor_configuration


def configuration():
    root = evaluation.REPOSITORY_ROOT
    paths = [evaluation.TICKETS_PATH, evaluation.MANIFEST_PATH,
             evaluation.KNOWLEDGE_PATH, root / "data/mock_orders.json", root / ".env"]
    return {
        "file_hashes": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in paths if p.exists()},
        "models": {key: os.getenv(key, "") for key in
                   ("OPENROUTER_PRIMARY_MODEL", "OPENROUTER_MODELS", "OPENROUTER_TRIAGE_MODEL",
                    "OPENROUTER_SUPERVISOR_MODEL", "OPENROUTER_REQUESTS_PER_MINUTE")},
        "rag": rag_configuration(), "business_policy": policy_configuration(),
        "supervisor": supervisor_configuration(),
        "approval_policy": evaluation.APPROVAL_POLICY_VERSION,
        "memory_mode": "separate_batches_shared_ephemeral_chroma",
    }


def reduction(sequential, concurrent):
    if sequential is None or concurrent is None or sequential <= 0:
        return None
    return 100 * (sequential - concurrent) / sequential


def timings(run_ids, log_path):
    result = {run_id: {} for run_id in run_ids}
    if not log_path.exists():
        return result
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("run_id") not in result:
            continue
        if event.get("event_type") == "tool_dispatch":
            result[event["run_id"]]["dispatch_ms"] = event["latency_ms"]
        if event.get("event_type") == "node_transition" and event.get("name") == "gather_facts":
            result[event["run_id"]]["gather_facts_ms"] = event["latency_ms"]
    return result


def summarize(report):
    summaries = {}
    for mode in ("sequential", "concurrent"):
        rows = report["batches"][mode]
        complete = (len(rows) == evaluation.EXPECTED_TICKET_COUNT and
                    len({r["ticket_id"] for r in rows}) == evaluation.EXPECTED_TICKET_COUNT and
                    all(not r.get("run_error") and r.get("observed_outcome") in
                        {"simulated_sent", "escalated"} for r in rows))
        dispatch = [r["dispatch_ms"] for r in rows if "dispatch_ms" in r]
        gathered = [r["gather_facts_ms"] for r in rows if "gather_facts_ms" in r]
        summaries[mode] = {
            "complete": complete, "metrics": evaluation.calculate_metrics(rows) if rows else None,
            "dispatch_p95_ms": evaluation._nearest_rank_p95(dispatch),
            "gather_facts_p95_ms": evaluation._nearest_rank_p95(gathered),
            "dispatch_count": len(dispatch),
            "bypass_count": sum("gather_facts_ms" in r and "dispatch_ms" not in r
                                and not r.get("run_error") for r in rows),
            "model_calls": sum(r.get("llm_calls", 0) for r in rows),
        }
    seq, concurrent = summaries["sequential"], summaries["concurrent"]
    complete = (seq["complete"] and concurrent["complete"] and not report.get("error")
                and {r["ticket_id"] for r in report["batches"]["sequential"]}
                == {r["ticket_id"] for r in report["batches"]["concurrent"]})
    summaries["publishable"] = complete
    summaries["full_run_reduction_percent"] = reduction(
        seq["metrics"]["p95_latency_ms"], concurrent["metrics"]["p95_latency_ms"]
    ) if complete else None
    summaries["dispatch_reduction_percent"] = reduction(
        seq["dispatch_p95_ms"], concurrent["dispatch_p95_ms"]
    ) if complete else None
    by_id = {r["ticket_id"]: r for r in report["batches"]["sequential"]}
    summaries["disposition_differences"] = [r["ticket_id"] for r in
        report["batches"]["concurrent"] if r["ticket_id"] in by_id and
        r.get("observed_outcome") != by_id[r["ticket_id"]].get("observed_outcome")]
    return summaries


def save(report, path):
    report["summary"] = summarize(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def publish_progress(report, path, progress_path=evaluation.PROGRESS_PATH):
    """Only replace comparison rows in the first tracker; preserve accuracy/history."""
    summary = summarize(report)
    if not summary["publishable"]:
        raise ValueError("Two complete scored batches are required for publication.")
    values = {
        "p95 latency (sequential)": summary["sequential"]["metrics"]["p95_latency_ms"],
        "p95 latency (async)": summary["concurrent"]["metrics"]["p95_latency_ms"],
    }
    measured = report["measured_at"][:10]
    text = progress_path.read_text(encoding="utf-8")
    for name, value in values.items():
        replacement = f"| {name} | {value!r} ms (TASK-20) | {measured} |"
        text, count = re.subn(r"^\| " + re.escape(name) + r" \|[^\n]*$",
                              lambda match: replacement, text, count=1, flags=re.MULTILINE)
        if not count:
            raise ValueError(f"Missing tracker row: {name}")
    name = "Async latency reduction (TASK-20)"
    replacement = f"| {name} | {summary['full_run_reduction_percent']!r}% | {measured} |"
    if f"| {name} |" in text:
        text = re.sub(r"^\| " + re.escape(name) + r" \|[^\n]*$",
                      lambda match: replacement, text, count=1, flags=re.MULTILINE)
    else:
        text = re.sub(r"(^\| p95 latency \(async\) \|[^\n]*$)",
                      lambda match: match[1] + "\n" + replacement,
                      text, count=1, flags=re.MULTILINE)
    text += (f"\n\n## [{measured}] TASK-20 completed comparison\n\n"
             f"Source: `{path}`. Accuracy tracker remains the historical TASK-43 benchmark. "
             "Comparison rows above use two new fake-delivery batches. "
             "One live batch per mode cannot isolate model/pacing/cache variability.\n\n"
             "```json\n" + json.dumps(summary, indent=2) + "\n```\n")
    progress_path.write_text(text, encoding="utf-8")


async def run_comparison(report, path):
    cases = evaluation.load_cases()
    if len(cases) != evaluation.EXPECTED_TICKET_COUNT:
        raise ValueError("Comparison requires exactly 50 cases.")
    pinned = configuration()
    report["configuration"] = pinned
    # Load embeddings and query the existing index locally before run timing.
    if pinned["rag"]["enabled"]:
        await KnowledgeSearchTool().run(run_id=report["comparison_id"] + "-warmup",
                                        query="tracking shipment", top_k=1)
    client = evaluation.OpenRouterClient()
    save(report, path)
    for mode in ("sequential", "concurrent"):
        sender = evaluation.FakeReplySender()

        def checkpoint(row):
            report["batches"][mode].append(row)
            # Preserve the raw completed row before optional log enrichment.
            save(report, path)
            ids = {r["run_id"] for r in report["batches"][mode]}
            costs = evaluation.costs_by_run_id(ids, evaluation.LOG_PATH)
            durations = timings(ids, evaluation.LOG_PATH)
            for item in report["batches"][mode]:
                item.update(costs[item["run_id"]])
                item.update(durations[item["run_id"]])
            save(report, path)
            if configuration() != pinned:
                raise ValueError("Pinned configuration changed; comparison stopped.")

        if configuration() != pinned:
            raise ValueError("Pinned configuration changed; comparison stopped.")
        print(f"Starting {mode} batch: 50 tickets, fake sender only.", flush=True)
        def before_case(case):
            if configuration() != pinned:
                raise ValueError("Pinned configuration changed; comparison stopped.")
            return {}
        await evaluation._run_graphs(cases, evaluation_id=report["comparison_id"] + "-" + mode,
                                    reply_sender=sender, shared_client=client,
                                    tool_dispatch_mode=mode, on_result=checkpoint,
                                    tool_overrides=before_case)
        report.setdefault("simulated_reply_counts", {})[mode] = len(sender.calls)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Recompute a saved comparison offline.")
    args = parser.parse_args(argv)
    if args.report:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        print(json.dumps(summarize(report), indent=2))
        return 0 if summarize(report)["publishable"] else 2
    load_dotenv(evaluation.REPOSITORY_ROOT / ".env")
    comparison_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    path = evaluation.REPORTS_DIR / f"task20_{comparison_id}.json"
    report = {"task": "TASK-20", "comparison_id": comparison_id,
              "delivery_adapter": "fake", "batches": {"sequential": [], "concurrent": []},
              "measured_at": datetime.now().astimezone().isoformat(),
              "limitations": "One live batch per mode; model variability, pacing and caches confound causal claims. JSONL timings have millisecond precision rounded to three decimals."}
    save(report, path)
    old_flag = os.environ.get("ZOHO_DESK_SEND_ENABLED")
    os.environ["ZOHO_DESK_SEND_ENABLED"] = "true"
    try:
        asyncio.run(run_comparison(report, path))
    except (Exception, KeyboardInterrupt) as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if old_flag is None:
            os.environ.pop("ZOHO_DESK_SEND_ENABLED", None)
        else:
            os.environ["ZOHO_DESK_SEND_ENABLED"] = old_flag
        save(report, path)
    print(json.dumps(report["summary"], indent=2))
    print(f"Saved comparison: {path}")
    if report["summary"]["publishable"]:
        publish_progress(report, path)
        print("Updated TASK-20 comparison rows in PROGRESS.md.")
    return 0 if report["summary"]["publishable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
