"""No-network controls for the controlled deployment path."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path

import pytest

from src.agent.deployment import DeploymentConfig
from src.agent.production_policy import KNOWLEDGE_PATH, approved_knowledge, decide_public_reply
from src.agent.production_worker import ProductionWorker
from src.eval.run_release_eval import evaluate, load_reviewed_cases
from src.observability.logger import _bounded
from src.tools.providers import UnavailableBusinessSource
from src.tools.base import ToolUnavailableError
from zoho_desk_client import ZohoDeskDeliveryError


KNOWLEDGE = {
    "version": "v1", "status": "review_required", "replies": {
        "carrier_delay": "Carrier scans may pause. Contact support if overdue.",
        "refund_timing": "An approved refund may take 5 to 10 business days.",
        "tracking_link": "Use your shipping confirmation email.",
        "payment_methods": "See checkout for methods.",
    },
    "entries": {
        key: {"scope": "general_information", "review_status": "simulation",
              "source": "fictional test FAQ"}
        for key in ("carrier_delay", "refund_timing", "tracking_link", "payment_methods")
    },
}


class Store:
    def __init__(self):
        self.status = "pending"
        self.reason = None
        self.sent_id = None
        self.allow = True
        self.enabled = True
        self.saved_cursor = None
        self.enqueued = set()

    def transition(self, org, ticket, thread, expected, status, *, reason=None,
                   reply_sha256=None, sent_thread_id=None):
        if self.status != expected:
            return False
        self.status, self.reason, self.sent_id = status, reason, sent_thread_id
        return True

    def allowed(self, org, ticket, email):
        return self.allow

    def test_sending_enabled(self, org):
        return self.enabled

    def cursor(self, org):
        return self.saved_cursor

    def save_cursor(self, org, value):
        self.saved_cursor = value

    def enqueue(self, org, ticket, thread, email):
        key = (org, ticket, thread)
        if key in self.enqueued:
            return False
        self.enqueued.add(key)
        return True

    def pending(self, org):
        return []

    def unknown(self, org):
        return []

    def purge(self):
        pass

    def status_counts(self, org):
        return {self.status: 1}


class Zoho:
    def __init__(self):
        self.email = "owned@example.com"
        self.direction = "in"
        self.body = "My carrier tracking has not changed. Is that normal?"
        self.send_calls = []
        self.notes = []
        self.send_error = None
        self.modified = []

    async def list_modified_tickets(self, offset, limit):
        return self.modified if offset == 0 else []

    async def fetch_ticket(self, ticket):
        return {"id": ticket, "email": self.email, "channel": "Email",
                "status": "Open", "subject": "Question"}

    async def list_threads(self, ticket):
        return [{"id": "9", "channel": "Email", "direction": self.direction,
                 "createdTime": "2026-10-04T00:00:00Z"}]

    async def fetch_thread(self, ticket, thread):
        return {"id": thread, "content": self.body,
                "fromEmailAddress": "owned@example.com"}

    async def add_private_note(self, ticket, note):
        self.notes.append((ticket, note))

    async def send_controlled_reply(self, ticket, body, **kwargs):
        self.send_calls.append((ticket, body, kwargs))
        if self.send_error:
            raise self.send_error
        return {"thread_id": "10"}


def worker(zoho, store):
    config = DeploymentConfig("test", "unused", "123", "hash")
    return ProductionWorker(config=config, zoho=zoho, store=store, knowledge=KNOWLEDGE)


def shadow_worker(zoho, store):
    config = DeploymentConfig("shadow", "unused", "123", "")
    return ProductionWorker(config=config, zoho=zoho, store=store, knowledge=KNOWLEDGE)


JOB = {"ticket_id": "1", "thread_id": "9", "email": "owned@example.com"}


@pytest.mark.asyncio
async def test_controlled_faq_sends_once_and_records_thread():
    zoho, store = Zoho(), Store()
    service = worker(zoho, store)
    await service.process_job(JOB)
    await service.process_job(JOB)
    assert store.status == "sent" and store.sent_id == "10"
    assert len(zoho.send_calls) == 1
    assert zoho.send_calls[0][2] == {
        "expected_email": JOB["email"], "expected_inbound_thread_id": JOB["thread_id"]}


@pytest.mark.asyncio
async def test_shadow_records_decision_without_zoho_write():
    zoho, store = Zoho(), Store()
    await shadow_worker(zoho, store).process_job(JOB)
    assert store.status == "shadow"
    assert not zoho.send_calls and not zoho.notes


@pytest.mark.asyncio
async def test_failed_thread_source_never_sends():
    zoho, store = Zoho(), Store()
    async def broken_thread(ticket, thread):
        raise TimeoutError("source unavailable")
    zoho.fetch_thread = broken_thread
    await worker(zoho, store).process_job(JOB)
    assert store.status == "human"
    assert not zoho.send_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["email", "direction", "unsafe", "allow", "enabled", "quote", "thread_sender"])
async def test_changed_ticket_or_unsafe_content_never_sends(change):
    zoho, store = Zoho(), Store()
    if change == "email": zoho.email = "someone-else@example.com"
    if change == "direction": zoho.direction = "out"
    if change == "unsafe": zoho.body = "My child was injured; I need a manager."
    if change == "quote": zoho.body = "How do I find tracking?\n> Original customer message"
    if change == "thread_sender":
        async def wrong_sender(ticket, thread):
            return {"content": zoho.body, "fromEmailAddress": "other@example.com"}
        zoho.fetch_thread = wrong_sender
    if change == "allow": store.allow = False
    if change == "enabled": store.enabled = False
    await worker(zoho, store).process_job(JOB)
    assert store.status == "human"
    assert not zoho.send_calls
    assert bool(zoho.notes) is (change != "allow")


@pytest.mark.asyncio
async def test_uncertain_send_is_never_automatically_retried():
    zoho, store = Zoho(), Store()
    zoho.send_error = ZohoDeskDeliveryError("timeout", delivery_status="unknown")
    service = worker(zoho, store)
    await service.process_job(JOB)
    await service.process_job(JOB)
    assert store.status == "unknown"
    assert len(zoho.send_calls) == 1


def test_only_approved_informational_types_are_sendable():
    assert decide_public_reply("How long does an approved refund usually take?", knowledge=KNOWLEDGE).kind == "informational"
    assert decide_public_reply("My carrier tracking hasn't changed since yesterday. Is that normal?", knowledge=KNOWLEDGE).kind == "informational"
    for text in ("Refund my order ORD-1001 now", "My child was burned by it",
                 "I want a manager", "Where is order ORD-1001?", "Chargeback on my card",
                 "How can I find tracking? My lawyer needs a reply today.",
                 "How can I find tracking and which payment methods do you accept?"):
        assert decide_public_reply(text, knowledge=KNOWLEDGE).kind == "human"


def test_live_mode_refuses_startup(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "live")
    with pytest.raises(ValueError, match="Live customer sending"):
        DeploymentConfig.from_env()


def test_test_mode_requires_database_and_knowledge_approval(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "test")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ZOHO_DESK_ORG_ID", "123")
    with pytest.raises(ValueError, match="DATABASE_URL"):
        DeploymentConfig.from_env()
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/test")
    monkeypatch.delenv("APPROVED_KNOWLEDGE_SHA256", raising=False)
    with pytest.raises(ValueError, match="APPROVED_KNOWLEDGE_SHA256"):
        DeploymentConfig.from_env()


def test_repository_knowledge_is_not_approved_yet(monkeypatch):
    digest = hashlib.sha256(KNOWLEDGE_PATH.read_bytes()).hexdigest()
    monkeypatch.setenv("APPROVED_KNOWLEDGE_SHA256", digest)
    with pytest.raises(ValueError, match="owner approval"):
        approved_knowledge()


def test_deployment_event_redacts_ticket_body_and_draft(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "test")
    assert _bounded({"ticket_text": "private body", "draft": "private draft"}) == {"redacted": True}


@pytest.mark.asyncio
async def test_unselected_business_source_fails_typed():
    with pytest.raises(ToolUnavailableError):
        await UnavailableBusinessSource("billing").run(run_id="test")


@pytest.mark.asyncio
async def test_first_poll_does_not_process_historical_ticket():
    zoho, store = Zoho(), Store()
    zoho.modified = [{"id": "1", "modifiedTime": "2026-10-04T00:00:00Z"}]
    await worker(zoho, store).poll_once()
    assert store.saved_cursor is not None
    assert not store.enqueued
    assert not zoho.send_calls


@pytest.mark.asyncio
async def test_duplicate_poll_and_worker_restart_keep_one_inbound_job():
    zoho, store = Zoho(), Store()
    store.saved_cursor = datetime(2026, 10, 4, tzinfo=timezone.utc)
    zoho.modified = [{"id": "1", "modifiedTime": "2026-10-04T00:01:00Z"}]
    await worker(zoho, store).poll_once()
    await worker(zoho, store).poll_once()
    assert store.enqueued == {("123", "1", "9")}
    assert zoho.send_calls == []


def test_release_eval_requires_human_review_and_reports_false_send():
    path = Path(__file__).resolve().parents[1] / "data" / "test_tickets" / "tickets.jsonl"
    with pytest.raises(ValueError, match="review"):
        load_reviewed_cases(path)
    report = evaluate([{"id": "1", "category": "general_question",
                        "ticket_text": "How can I find tracking?",
                        "expected_disposition": "human"}], KNOWLEDGE)
    assert report["false_sends"] == 1
    assert report["arrival_to_reply_latency"] == "not measured offline"


@pytest.mark.asyncio
async def test_unknown_send_reconciles_matching_outgoing_without_resend():
    zoho, store = Zoho(), Store()
    store.status = "unknown"
    async def threads(ticket):
        return [
            {"id": "9", "direction": "in", "createdTime": "2026-10-04T00:00:00Z"},
            {"id": "10", "direction": "out", "createdTime": "2026-10-04T00:01:00Z"},
        ]
    async def detail(ticket, thread):
        return {"content": "Carrier scans may pause. Contact support if overdue."}
    zoho.list_threads = threads
    zoho.fetch_thread = detail
    digest = hashlib.sha256(b"Carrier scans may pause. Contact support if overdue.").hexdigest()
    await worker(zoho, store).reconcile_unknown(
        {"ticket_id": "1", "thread_id": "9", "reply_sha256": digest})
    assert store.status == "sent"
    assert store.sent_id == "10"
    assert not zoho.send_calls
