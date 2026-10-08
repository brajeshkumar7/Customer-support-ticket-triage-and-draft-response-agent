"""Offline evidence audit; never runs the agent, sends email, or calls a model.

Public: python docs/verify_evidence.py
Owner:  python docs/verify_evidence.py --private --junit PATH --output PATH
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs/measurements/task43_regression.json"
RAW = ROOT / "data/eval_reports/task29_20261007T095641Z_d2289193.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def equal(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and equal(actual[k], v) for k, v in expected.items())
    if isinstance(expected, float):
        return isinstance(actual, (int, float)) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12)
    return actual == expected


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit(private=False, junit=None):
    public = json.loads(PUBLIC.read_text(encoding="utf-8"))
    rows, metrics = public["cases"], public["metrics"]
    require(len(rows) == 50 and len({r["run_id"] for r in rows}) == 50, "Expected 50 unique runs")
    require(len({r["ticket_id"] for r in rows}) == 50, "Duplicate case IDs")
    require(public["delivery_adapter"] == "fake", "Unexpected delivery adapter")
    matrix = Counter()
    for row in rows:
        expected, observed = row["expected_outcome"], row["observed_outcome"]
        require(expected in {"auto_resolve", "escalate"}, "Unknown label")
        require(observed in {"simulated_sent", "escalated"}, "Unknown or real delivery outcome")
        matched = observed == ("simulated_sent" if expected == "auto_resolve" else "escalated")
        require(row["matches_expected"] == matched, "Stored match contradicts outcome")
        matrix[(expected, observed)] += 1
    matched = matrix[("auto_resolve", "simulated_sent")] + matrix[("escalate", "escalated")]
    sent = sum(r["observed_outcome"] == "simulated_sent" for r in rows)
    eligible = sum(r["expected_outcome"] == "auto_resolve" for r in rows)
    latencies = sorted(r["latency_ms"] for r in rows)
    computed = {
        "ticket_count": len(rows), "scored_ticket_count": len(rows), "unscored_count": 0,
        "matched_count": matched, "task_completion_rate": matched / len(rows),
        "false_send_count": matrix[("escalate", "simulated_sent")],
        "false_escalation_count": matrix[("auto_resolve", "escalated")],
        "p95_latency_ms": latencies[math.ceil(.95 * len(rows)) - 1],
        "total_reported_token_cost": sum(r["reported_cost"] for r in rows),
        "llm_calls_total": sum(r["llm_calls"] for r in rows),
        "tickets_with_missing_token_cost": sum(r["calls_missing_cost"] > 0 for r in rows),
    }
    require(equal(metrics, computed), "Public aggregate differs from case arithmetic")
    result = {
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Offline verification of existing evidence; no new model accuracy measurement",
        "public_measurement": PUBLIC.relative_to(ROOT).as_posix(),
        "public_measurement_sha256": digest(PUBLIC),
        "verifier_sha256": digest(Path(__file__)),
        "evaluation_id": public["evaluation_id"],
        "public_arithmetic_verified": True,
        "recomputed_metrics": computed,
        "confusion_matrix": {f"{a} -> {b}": matrix[(a, b)] for a in ("auto_resolve", "escalate") for b in ("simulated_sent", "escalated")},
        "derived_interpretation": {
            "simulated_reply_count": sent,
            "automation_coverage": sent / len(rows),
            "eligible_reply_capture": matrix[("auto_resolve", "simulated_sent")] / eligible,
            "always_escalate_baseline_match": (len(rows) - eligible) / len(rows),
            "match_gain_over_always_escalate_percentage_points": 100 * (matched - (len(rows) - eligible)) / len(rows),
            "baseline_scope": "Analytical constant-action baseline on existing labels, not a new agent run",
        },
        "private_provenance_verified": False,
        "limits": ["Author-labeled synthetic development cases", "Hashes establish byte consistency, not independent authenticity", "Public arithmetic alone cannot verify private logs or omitted workflow errors", "No real customer delivery or independent accuracy validation"],
    }
    if private:
        raw = json.loads(RAW.read_text(encoding="utf-8"))
        require(digest(RAW) == public["source_report_sha256"], "Raw report hash mismatch")
        require(all(not r.get("run_error") for r in raw["results"]), "Unscored raw result")
        source_rows = {r["run_id"]: r for r in raw["results"]}
        require(set(source_rows) == {r["run_id"] for r in rows}, "Raw/public run IDs differ")
        for row in rows:
            source = source_rows[row["run_id"]]
            for key, value in row.items():
                actual = source.get("safety_review", {}).get(key) if key in {"reason_code", "evidence_ids"} else source.get(key)
                require(equal(actual, value), f"Raw/public mismatch: {row['ticket_id']} {key}")
        sys.path.insert(0, str(ROOT))
        from src.eval.run_eval import calculate_metrics
        require(equal(raw["metrics"], calculate_metrics(raw["results"])), "Harness recomputation mismatch")
        require(equal(public["metrics"], raw["metrics"]), "Published metrics differ from raw metrics")
        events = {key: [] for key in source_rows}
        selected_digest = hashlib.sha256()
        for line in (ROOT / "data/logs/events.jsonl").open(encoding="utf-8"):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("run_id") in events:
                events[event["run_id"]].append(event)
                selected_digest.update(line.encode("utf-8"))
        for run_id, group in events.items():
            row = source_rows[run_id]
            calls = [e for e in group if e.get("event_type") == "llm_call"]
            require(len(calls) == row["llm_calls"], f"Call count mismatch: {run_id}")
            require(all(isinstance(e.get("token_cost"), (int, float)) for e in calls), "Missing logged cost")
            require(equal(sum(e["token_cost"] for e in calls), row["reported_cost"]), f"Cost mismatch: {run_id}")
            nodes = [e for e in group if e.get("event_type") == "node_transition"]
            require(bool(nodes) and not any(e.get("error") for e in nodes), f"Missing or failed node: {run_id}")
            expected_terminal = "remember" if row["observed_outcome"] == "simulated_sent" else "escalate"
            require(nodes[-1].get("node_name") == expected_terminal, f"Terminal route mismatch: {run_id}")
        traces = []
        for case_id in ("general_01", "billing_01", "general_03"):
            row = next(r for r in raw["results"] if r["ticket_id"] == case_id)
            traces.append({
                "case_id": case_id, "run_id": row["run_id"],
                "expected_outcome": row["expected_outcome"], "observed_outcome": row["observed_outcome"],
                "supervisor_status": row["supervisor_status"],
                "safety_reason_code": row["safety_review"].get("reason_code"),
                "safety_send_allowed": row["safety_review"].get("send_allowed"),
                "nodes": [e["node_name"] for e in events[row["run_id"]] if e.get("event_type") == "node_transition"],
            })
        result.update(private_provenance_verified=True, raw_report_sha256=digest(RAW),
                      harness_recomputation_verified=True,
                      correlated_event_count=sum(map(len, events.values())),
                      correlated_jsonl_sha256=selected_digest.hexdigest(),
                      per_run_call_cost_and_terminal_route_verified=True, selected_traces=traces)
    if junit:
        suites = ET.parse(junit).getroot()
        cases = list(suites.iter("testcase"))
        counts = {"collected_results": len(cases), "failures": len(list(suites.iter("failure"))),
                  "errors": len(list(suites.iter("error"))), "skipped": len(list(suites.iter("skipped")))}
        counts["passed"] = counts["collected_results"] - counts["failures"] - counts["errors"] - counts["skipped"]
        require(bool(cases) and counts["failures"] == counts["errors"] == 0, "Test evidence contains failures or no tests")
        paths = sorted([*ROOT.glob("src/**/*.py"), *ROOT.glob("tests/**/*.py"),
                        *ROOT.glob("data/test_tickets/*"), *ROOT.glob("knowledgebase/*"),
                        *ROOT.glob("data/policies/*.json"), *ROOT.glob("data/approved_knowledge/*.json"),
                        ROOT / "requirements.txt", ROOT / "zoho_desk_client.py"])
        hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths if p.is_file()}
        result["offline_test_evidence"] = {**counts, "junit_sha256": digest(junit),
                                           "suite_records": [{k: s.get(k) for k in ("timestamp", "time", "tests", "failures", "errors", "skipped")} for s in suites.iter("testsuite")],
                                           "python_version": sys.version,
                                           "file_sha256": hashes, "scope": "Existing Python regression suite; no live provider or deployment validation"}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", action="store_true", help="Also verify ignored raw report and local JSONL")
    parser.add_argument("--junit", type=Path, help="Include a fresh pytest JUnit result")
    parser.add_argument("--output", type=Path, help="Write a new audit JSON; existing output is never overwritten")
    args = parser.parse_args()
    payload = audit(args.private, args.junit)
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
    print(json.dumps({k: v for k, v in payload.items() if k != "offline_test_evidence"}, indent=2))
    if "offline_test_evidence" in payload:
        print(json.dumps({k: v for k, v in payload["offline_test_evidence"].items() if k != "file_sha256"}, indent=2))
