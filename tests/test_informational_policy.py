"""Network-free checks for the shared local approval rule and frozen holdout."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.agent.graph import build_graph
from src.agent.reply_sender import SimulationOnlyReplySender
from src.agent.production_policy import decide_public_reply, simulation_knowledge
from src.eval.run_holdout import FROZEN_SHA256, HOLDOUT_PATH, holdout_tools, load_holdout, summarize
from src.eval.export_public_metrics import public_measurement
from src.memory.short_term import ShortTermMemory
from src.tools.base import ToolResult
from src.tools.providers import CustomerOrderEvidence, verify_customer_order_evidence


@pytest.fixture(autouse=True)
def legacy_template_policy_without_rag(monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "false")


def test_holdout_is_frozen_balanced_and_author_labeled():
    rows = load_holdout()
    assert hashlib.sha256(HOLDOUT_PATH.read_bytes()).hexdigest() == FROZEN_SHA256
    assert len(rows) == len({row["id"] for row in rows}) == 200
    assert all(sum(row["category"] == category for row in rows) == 40 for category in {
        "order_status", "returns", "damaged_item", "billing_dispute", "general_question"
    })
    assert all(row["label_provenance"] == "author_drafted_templated_synthetic" for row in rows)
    assert holdout_tools({"scenario": "provider_failure", "category": "order_status"})
    assert holdout_tools({"scenario": "payment_methods", "category": "general_question"}) == {}


def test_public_measurement_excludes_ticket_and_draft_text():
    report = {"task": "TASK-29", "delivery_adapter": "fake", "metrics": {"matched_count": 50},
              "results": [{"ticket_id": f"case-{index}", "run_id": f"run-{index}",
                           "observed_outcome": "escalated", "ticket_text": "private ticket",
                           "draft_response": "private draft", "safety_review": {
                               "reason_code": "human_required", "reason": "private explanation"}}
                          for index in range(50)]}
    exported = public_measurement(report, report_sha256="hash")
    assert len(exported["cases"]) == 50
    assert exported["cases"][0]["reason_code"] == "human_required"
    assert "private" not in str(exported)


def test_holdout_summary_marks_uncovered_simulated_reply_unsafe():
    row = {"ticket_id": "case", "category": "general_question",
           "expected_outcome": "auto_resolve", "expected_disposition": "informational",
           "observed_outcome": "simulated_sent", "matches_expected": True,
           "required_evidence": ["payment_methods"], "safety_review": {"evidence_ids": []},
           "draft_response": "unsupported", "expected_template": "approved",
           "latency_ms": 2.0, "retry_count": 0, "supervisor_status": "PASS",
           "reported_cost": 0.0, "total_cost": 0.0, "llm_calls": 0,
           "calls_missing_cost": 0}
    report = summarize([row])
    assert report["unsupported_public_claim_count"] == 1
    assert report["evidence_coverage"] == {"covered": 0, "simulated_sends": 1}


@pytest.mark.parametrize("ticket", [
    "Where is ORD-1001?",
    "My order says delivered but it is missing. Where is the tracking link?",
    "Please refund my purchase.",
    "My speaker started smoking.",
    "I was charged twice.",
    "How can I track my shipment and update my address?",
    "Do you guarantee overnight shipping and what does it cost?",
    "Which payment methods can I use at checkout, and can you wrap the gift?",
    "Where is the tracking link? Do you sell gift cards?",
    "When will my refund appear in my account?",
    "When will my refund be approved?",
    "Can you investigate my tracking delay and contact the carrier?",
    "Please send me my tracking link for this order.",
    "My account was hacked, but my refund was approved. How long will it take?",
])
def test_shared_policy_requires_human_for_unverified_or_actionable_requests(ticket):
    decision = decide_public_reply(ticket, knowledge=simulation_knowledge())
    assert decision.kind == "human"
    assert decision.body is None
    assert decision.reason_code


@pytest.mark.parametrize(("ticket", "evidence"), [
    ("Which payment methods can I use at checkout?", "payment_methods"),
    ("Where is the tracking link after an order ships?", "tracking_link"),
    ("My carrier tracking has not changed. Is that normal?", "carrier_delay"),
    ("After an approved refund, how long does posting usually take?", "refund_timing"),
    ("Do carrier scans pause sometimes, and what if the delivery window passes?", "carrier_delay"),
    ("My refund has already been approved. About how long does it usually take for the money to appear in my account?", "refund_timing"),
])
def test_shared_policy_links_exact_template_to_versioned_evidence(ticket, evidence):
    knowledge = simulation_knowledge()
    decision = decide_public_reply(ticket, knowledge=knowledge)
    assert decision.kind == "informational"
    assert decision.reason_code == "supported_faq"
    assert decision.evidence_ids == (evidence,)
    assert decision.body == knowledge["replies"][evidence]
    assert decision.knowledge_version == "v1"


def test_future_customer_evidence_contract_fails_closed():
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    valid = CustomerOrderEvidence("ORD-1001", "owner@example.com", "shipped",
                                  "in_transit", now - timedelta(minutes=2),
                                  "hypothetical-authoritative-adapter")
    assert verify_customer_order_evidence(valid, ticket_requester_email="OWNER@example.com", now=now) == (True, "verified")
    variants = [
        (replace(valid, requester_email="other@example.com"), "requester_mismatch"),
        (replace(valid, observed_at=now - timedelta(days=1)), "stale_or_invalid_timestamp"),
        (replace(valid, order_status="delivered"), "conflicting_facts"),
        (replace(valid, source=""), "source_unavailable"),
    ]
    for evidence, expected in variants:
        assert verify_customer_order_evidence(
            evidence, ticket_requester_email="owner@example.com", now=now
        ) == (False, expected)


@pytest.mark.asyncio
async def test_graph_uses_no_models_or_business_tools_for_approved_faq(monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "false")
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "true")

    class NeverCalled:
        async def create_chat_completion(self, **_kwargs):
            raise AssertionError("No model call is needed for an exact FAQ reply.")

    class Memory:
        def query(self, _text):
            return []

        def add(self, _text, _metadata):
            return "memory-id"

    class Sender(SimulationOnlyReplySender):
        def __init__(self):
            self.calls = []

        async def send_public_reply(self, ticket_id, body):
            self.calls.append((ticket_id, body))
            return {"simulated": True}

    class NeverTool:
        async def run(self, **_kwargs):
            raise AssertionError("FAQ template needs no mock business tool.")

    sender = Sender()
    graph = build_graph(short_term_memory=ShortTermMemory("faq-fast"),
                        long_term_memory=Memory(), client=NeverCalled(),
                        primary_model="test-model", reply_sender=sender,
                        order_lookup_tool=NeverTool(), policy_checker_tool=NeverTool(),
                        faq_search_tool=NeverTool())
    result = await graph.ainvoke({"ticket_id": "faq-fast", "zoho_ticket_id": "123",
                                  "ticket_text": "Which payment methods can I use at checkout?"})
    assert result["terminal_status"] == "sent"
    assert result["safety_review"]["evidence_ids"] == ["payment_methods"]
    assert len(sender.calls) == 1
    assert sender.calls[0][1] == simulation_knowledge()["replies"]["payment_methods"]


@pytest.mark.asyncio
@pytest.mark.parametrize("record_problem", ["requester_mismatch", "stale", "conflicting"])
async def test_customer_specific_fake_records_never_authorize_send(monkeypatch, record_problem):
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "true")

    class Client:
        def __init__(self):
            self.outputs = iter([
                '{"category":"order status","urgency":"medium"}',
                '{"order_id":"ORD-1001","reason":"status request"}',
                "I will ask a person to verify your order.",
                '{"checks":[{"id":"factual_claims_grounded","passed":true,"reason":"No business claim."},'
                '{"id":"no_unsupported_claims","passed":true,"reason":"No unsupported claim."},'
                '{"id":"urgency_appropriate_tone","passed":true,"reason":"Appropriate."}]}',
            ])

        async def create_chat_completion(self, **_kwargs):
            from types import SimpleNamespace
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(self.outputs)))])

        async def create_decision(self, **kwargs):
            import json
            labels = json.loads(next(self.outputs))
            return {"model": kwargs["model"], "answers": {
                name: {"type": "choice", "choice": labels[name], "confidence": 1.0,
                       "probabilities": {key: float(key == labels[name]) for key in question["criteria"]}}
                for name, question in kwargs["questions"].items()}}

    class Snapshot:
        async def run(self, **_kwargs):
            return ToolResult("order_lookup", {"order_id": "ORD-1001", "status": "shipped",
                                               "verification_problem": record_problem})

    class OtherTool:
        async def run(self, **_kwargs):
            return ToolResult("other", {})

    class Memory:
        def query(self, _text):
            return []

        def add(self, _text, _metadata):
            return "memory-id"

    class Sender(SimulationOnlyReplySender):
        def __init__(self):
            self.calls = []

        async def send_public_reply(self, *_args):
            self.calls.append(1)
            return {"simulated": True}

    sender = Sender()
    graph = build_graph(short_term_memory=ShortTermMemory(record_problem),
                        long_term_memory=Memory(), client=Client(),
                        primary_model="test-model", order_lookup_tool=Snapshot(),
                        policy_checker_tool=OtherTool(), faq_search_tool=OtherTool(),
                        reply_sender=sender)
    result = await graph.ainvoke({"ticket_id": record_problem, "zoho_ticket_id": "123",
                                  "ticket_text": "Where is ORD-1001?"})
    assert result["tool_results"]["order_lookup"]["data"]["verification_problem"] == record_problem
    assert result["terminal_status"] == "escalated"
    assert result["safety_review"]["reason_code"] == "customer_facts_unverified"
    assert sender.calls == []


@pytest.mark.asyncio
async def test_raw_graph_refuses_non_simulation_sender_even_for_approved_faq(monkeypatch):
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "true")

    class Client:
        async def create_chat_completion(self, **_kwargs):
            raise AssertionError("Exact FAQ needs no model call.")

    class Memory:
        def query(self, _text):
            return []

        def add(self, _text, _metadata):
            return "memory-id"

    class Sender:
        def __init__(self):
            self.calls = []

        async def send_public_reply(self, ticket_id, body):
            self.calls.append((ticket_id, body))
            raise AssertionError("A public sender must never be called by the local graph.")

    sender = Sender()
    graph = build_graph(short_term_memory=ShortTermMemory("blocked-real"),
                        long_term_memory=Memory(), client=Client(),
                        primary_model="test-model", reply_sender=sender)
    result = await graph.ainvoke({"ticket_id": "blocked-real", "zoho_ticket_id": "123",
                                  "ticket_text": "Which payment methods can I use at checkout?"})
    assert result["terminal_status"] == "escalated"
    assert result["supervisor_status"] == "PASS"
    assert sender.calls == []
