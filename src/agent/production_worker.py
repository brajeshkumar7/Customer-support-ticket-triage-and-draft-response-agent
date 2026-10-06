"""Single-worker Zoho poller for controlled, informational replies only.

Run with ``python -m src.agent.production_worker``. Test sending requires a
database allowlist row and reviewed knowledge hash. Live mode cannot start.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.agent.deployment import DeploymentConfig
from src.agent.job_store import JobStore
from src.agent.production_policy import approved_knowledge, decide_public_reply
from src.agent.run_zoho import _plain_text
from src.observability.logger import purge_deployment_logs
from zoho_desk_client import ZohoDeskClient, ZohoDeskDeliveryError

LOG = logging.getLogger(__name__)
QUOTED_HISTORY = re.compile(
    r"<blockquote\b|-{2,}\s*original message\s*-{2,}|\bon .{8,120} wrote\s*:|"
    r"(?:^|\n)\s*>\s|(?:^|\n)\s*from\s*:.{0,120}(?:\n|$)", re.I,
)


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Zoho record has no timestamp.")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _latest_thread(threads: list[dict[str, Any]]) -> dict[str, Any]:
    if not threads:
        raise ValueError("Ticket has no thread history.")
    return max(threads, key=lambda item: _timestamp(item.get("createdTime")))


class ProductionWorker:
    def __init__(self, *, config: DeploymentConfig, zoho: Any, store: Any,
                 knowledge: dict | None = None) -> None:
        if config.mode not in {"shadow", "test"}:
            raise ValueError("Worker must run in shadow or test mode.")
        self.config = config
        self.zoho = zoho
        self.store = store
        self.knowledge = knowledge if knowledge is not None else (
            approved_knowledge() if config.mode == "test" else None
        )

    async def poll_once(self) -> None:
        """Enqueue each new inbound email once, then drain pending jobs."""
        cursor = self.store.cursor(self.config.organization_id)
        if cursor is None:
            # First launch starts at now. Never mass-reply to historical
            # customer tickets merely because a new worker was deployed.
            self.store.save_cursor(self.config.organization_id, datetime.now(timezone.utc))
            return
        cutoff = cursor - timedelta(minutes=2) if cursor else None
        newest = cursor
        for offset in range(0, 10000, 50):
            page = await self.zoho.list_modified_tickets(offset, 50)
            if not page:
                break
            reached_cursor = False
            for item in page:
                modified = _timestamp(item.get("modifiedTime"))
                if cutoff and modified < cutoff:
                    reached_cursor = True
                    continue
                if newest is None or modified > newest:
                    newest = modified
                ticket_id = str(item.get("id", ""))
                if not ticket_id.isdigit():
                    continue
                await self._enqueue_ticket(ticket_id, cutoff=cutoff)
            if reached_cursor or len(page) < 50:
                break
        else:
            raise RuntimeError("Zoho poll exceeded 10000 tickets; cursor was not advanced.")
        if newest is not None:
            self.store.save_cursor(self.config.organization_id, newest)
        for job in self.store.pending(self.config.organization_id):
            await self.process_job(job)
        for job in self.store.unknown(self.config.organization_id):
            await self.reconcile_unknown(job)
        counts = self.store.status_counts(self.config.organization_id)
        if counts.get("unknown") or counts.get("pending") or counts.get("human"):
            LOG.warning("Worker attention needed: %s", counts)
        self.store.purge()
        purge_deployment_logs()

    async def reconcile_unknown(self, job: dict[str, str]) -> None:
        """Only confirm a matching Zoho outgoing thread; never resend."""
        org, ticket_id, inbound_id = self.config.organization_id, job["ticket_id"], job["thread_id"]
        digest = job.get("reply_sha256", "")
        if not digest:
            return  # Crash before the send attempt cannot be inferred safely.
        try:
            threads = await self.zoho.list_threads(ticket_id)
            inbound = next(item for item in threads if str(item.get("id")) == inbound_id)
            inbound_time = _timestamp(inbound.get("createdTime"))
            for thread in threads:
                if (str(thread.get("direction", "")).casefold() not in {"out", "outgoing"}
                    or _timestamp(thread.get("createdTime")) <= inbound_time):
                    continue
                detail = await self.zoho.fetch_thread(ticket_id, str(thread["id"]))
                content = detail.get("content")
                if isinstance(content, str) and hashlib.sha256(_plain_text(content).encode("utf-8")).hexdigest() == digest:
                    self.store.transition(org, ticket_id, inbound_id, "unknown", "sent",
                                          reason="reconciled", sent_thread_id=str(thread["id"]))
                    return
        except Exception:
            LOG.warning("Could not reconcile uncertain send for ticket %s", ticket_id)

    async def _enqueue_ticket(self, ticket_id: str, *, cutoff: datetime | None) -> None:
        ticket = await self.zoho.fetch_ticket(ticket_id)
        if str(ticket.get("channel", "")).casefold() != "email":
            return
        email = ticket.get("email")
        if not isinstance(email, str) or "@" not in email:
            return
        threads = await self.zoho.list_threads(ticket_id)
        latest = _latest_thread(threads)
        if cutoff and _timestamp(latest.get("createdTime")) < cutoff:
            return
        if str(latest.get("channel", "")).casefold() != "email":
            return
        if str(latest.get("direction", "")).casefold() not in {"in", "incoming"}:
            return
        thread_id = str(latest.get("id", ""))
        if thread_id.isdigit():
            self.store.enqueue(self.config.organization_id, ticket_id, thread_id, email)

    async def process_job(self, job: dict[str, str]) -> None:
        org = self.config.organization_id
        ticket_id, inbound_id, email = job["ticket_id"], job["thread_id"], job["email"]
        if not self.store.transition(org, ticket_id, inbound_id, "pending", "processing"):
            return

        async def handoff(reason: str) -> None:
            self.store.transition(org, ticket_id, inbound_id, "processing", "human", reason=reason)
            if self.config.mode != "test" or not self.store.allowed(org, ticket_id, email):
                return
            try:
                await self.zoho.add_private_note(ticket_id,
                    f"Automation handoff for inbound thread {inbound_id}: {reason}. A human must review before replying.")
            except Exception:
                LOG.error("Private handoff note failed for ticket %s (%s)", ticket_id, reason)

        try:
            ticket = await self.zoho.fetch_ticket(ticket_id)
            threads = await self.zoho.list_threads(ticket_id)
            latest = _latest_thread(threads)
            if (str(ticket.get("channel", "")).casefold() != "email"
                or str(ticket.get("status", "")).casefold() in {"closed", "spam", "deleted"}
                or str(ticket.get("email", "")).casefold() != email.casefold()
                or str(latest.get("id")) != inbound_id
                or str(latest.get("direction", "")).casefold() not in {"in", "incoming"}):
                await handoff("ticket_or_thread_changed")
                return
            if self.config.mode == "test" and not self.store.allowed(org, ticket_id, email):
                await handoff("test_allowlist_missing_or_expired")
                return
            if self.config.mode == "test" and not self.store.test_sending_enabled(org):
                await handoff("test_kill_switch_off")
                return
            detail = await self.zoho.fetch_thread(ticket_id, inbound_id)
            thread_sender = parseaddr(str(detail.get("fromEmailAddress", "")))[1]
            if thread_sender.casefold() != email.casefold():
                await handoff("inbound_sender_does_not_match_requester")
                return
            if detail.get("isContentTruncated") is True:
                await handoff("thread_content_truncated")
                return
            content = detail.get("content")
            if not isinstance(content, str) or not content.strip():
                await handoff("thread_content_unavailable")
                return
            if QUOTED_HISTORY.search(content):
                await handoff("quoted_or_forwarded_history_requires_review")
                return
            subject = ticket.get("subject")
            ticket_text = (f"{_plain_text(subject)}\n" if isinstance(subject, str) else "") + _plain_text(content)
            if len(ticket_text) > 10000:
                await handoff("ticket_too_large")
                return
            if self.config.mode == "shadow":
                # Shadow records a decision but makes no change in Zoho.
                draft_knowledge = json.loads((Path(__file__).resolve().parents[2] /
                    "data" / "approved_knowledge" / "v1.json").read_text(encoding="utf-8"))
                decision = decide_public_reply(ticket_text, knowledge=draft_knowledge)
                self.store.transition(org, ticket_id, inbound_id, "processing", "shadow",
                                      reason=f"{decision.kind}:{decision.reason}")
                return
            decision = decide_public_reply(ticket_text, knowledge=self.knowledge)
            if decision.kind != "informational" or not decision.body:
                await handoff(decision.reason)
                return
            if not self.store.test_sending_enabled(org) or not self.store.allowed(org, ticket_id, email):
                await handoff("test_authorization_changed")
                return
            # Persist the attempt before touching Zoho. A crash or timeout
            # leaves an unknown result that cannot be automatically resent.
            digest = hashlib.sha256(decision.body.encode("utf-8")).hexdigest()
            if not self.store.transition(org, ticket_id, inbound_id, "processing", "sending",
                                         reason=decision.reason, reply_sha256=digest):
                return
            try:
                result = await self.zoho.send_controlled_reply(
                    ticket_id, decision.body, expected_email=email,
                    expected_inbound_thread_id=inbound_id,
                )
            except ZohoDeskDeliveryError as error:
                status = "unknown" if error.delivery_status == "unknown" else "human"
                self.store.transition(org, ticket_id, inbound_id, "sending", status,
                                      reason=type(error).__name__)
                LOG.error("Controlled send %s for ticket %s (%s)", status, ticket_id, type(error).__name__)
                return
            except Exception:
                self.store.transition(org, ticket_id, inbound_id, "sending", "unknown",
                                      reason="unexpected_send_error")
                return
            sent_id = str(result.get("thread_id", ""))
            if not sent_id.isdigit():
                self.store.transition(org, ticket_id, inbound_id, "sending", "unknown",
                                      reason="reply_thread_id_missing")
                return
            self.store.transition(org, ticket_id, inbound_id, "sending", "sent",
                                  sent_thread_id=sent_id)
        except Exception as error:
            # Only pre-send failures can safely become a fresh human task.
            self.store.transition(org, ticket_id, inbound_id, "processing", "human",
                                  reason=type(error).__name__)
            LOG.exception("Worker failed for ticket %s", ticket_id)


async def main() -> None:
    load_dotenv()
    config = DeploymentConfig.from_env()
    if config.mode == "off":
        LOG.info("Worker is off; no Zoho or database calls will be made.")
        while True:
            await asyncio.sleep(3600)
    store = JobStore(config.database_url)
    lock_connection = store.acquire_worker_lock(config.organization_id)
    try:
        store.initialize()
        worker = ProductionWorker(config=config, zoho=ZohoDeskClient.from_env(), store=store)
        while True:
            # A lost advisory-lock connection must stop this process before
            # another worker can acquire the organization lock.
            lock_connection.execute("SELECT 1")
            try:
                await worker.poll_once()
            except Exception:
                LOG.exception("Polling failed; no cursor advance for failed batch")
            await asyncio.sleep(config.poll_seconds)
    finally:
        lock_connection.close()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(main())
