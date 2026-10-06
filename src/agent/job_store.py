"""PostgreSQL job ledger: unique inbound threads and irreversible send states."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg


SCHEMA = """
CREATE TABLE IF NOT EXISTS worker_cursor (
    org_id text PRIMARY KEY, modified_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS worker_controls (
    org_id text PRIMARY KEY, test_sending_enabled boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS test_allowlist (
    org_id text NOT NULL, ticket_id text NOT NULL, requester_email text NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (org_id, ticket_id, requester_email)
);
CREATE TABLE IF NOT EXISTS ticket_jobs (
    org_id text NOT NULL, ticket_id text NOT NULL, inbound_thread_id text NOT NULL,
    requester_email text NOT NULL, status text NOT NULL DEFAULT 'pending',
    reply_sha256 text, sent_thread_id text, reason_code text,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, ticket_id, inbound_thread_id)
);
CREATE INDEX IF NOT EXISTS ticket_jobs_status_idx ON ticket_jobs(status, created_at);
"""


class JobStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(self.database_url, connect_timeout=5,
                               options="-c statement_timeout=5000")

    def initialize(self) -> None:
        with self._connect() as conn:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    conn.execute(statement)
            # A crash during processing might have happened after an external
            # send. Recovery routes it to reconciliation, never another send.
            conn.execute("UPDATE ticket_jobs SET status='unknown', reason_code='restart_during_processing', updated_at=now() WHERE status IN ('processing', 'sending')")

    def acquire_worker_lock(self, org_id: str):
        """Hold one session-level advisory lock for the worker lifetime."""
        conn = self._connect()
        try:
            acquired = conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (org_id,)).fetchone()
            if not acquired or not acquired[0]:
                raise RuntimeError("Another worker owns this Zoho organization.")
            return conn
        except Exception:
            conn.close()
            raise

    def cursor(self, org_id: str) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute("SELECT modified_at FROM worker_cursor WHERE org_id=%s", (org_id,)).fetchone()
            return row[0] if row else None

    def save_cursor(self, org_id: str, value: datetime) -> None:
        with self._connect() as conn:
            conn.execute("""INSERT INTO worker_cursor(org_id, modified_at) VALUES (%s,%s)
                ON CONFLICT(org_id) DO UPDATE SET modified_at=GREATEST(worker_cursor.modified_at, EXCLUDED.modified_at)""", (org_id, value))

    def enqueue(self, org_id: str, ticket_id: str, thread_id: str, email: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("""INSERT INTO ticket_jobs(org_id,ticket_id,inbound_thread_id,requester_email)
                VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING ticket_id""",
                (org_id, ticket_id, thread_id, email.casefold())).fetchone()
            return row is not None

    def pending(self, org_id: str) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute("""SELECT ticket_id,inbound_thread_id,requester_email
                FROM ticket_jobs WHERE org_id=%s AND status='pending' ORDER BY created_at""", (org_id,)).fetchall()
        return [{"ticket_id": a, "thread_id": b, "email": c} for a, b, c in rows]

    def transition(self, org_id: str, ticket_id: str, thread_id: str, expected: str,
                   status: str, *, reason: str | None = None, reply_sha256: str | None = None,
                   sent_thread_id: str | None = None) -> bool:
        with self._connect() as conn:
            row = conn.execute("""UPDATE ticket_jobs SET status=%s, reason_code=%s,
                reply_sha256=COALESCE(%s,reply_sha256),
                sent_thread_id=COALESCE(%s,sent_thread_id), updated_at=now()
                WHERE org_id=%s AND ticket_id=%s AND inbound_thread_id=%s AND status=%s
                RETURNING ticket_id""", (status, reason, reply_sha256, sent_thread_id,
                                             org_id, ticket_id, thread_id, expected)).fetchone()
            return row is not None

    def allowed(self, org_id: str, ticket_id: str, email: str) -> bool:
        with self._connect() as conn:
            return conn.execute("""SELECT 1 FROM test_allowlist WHERE org_id=%s AND ticket_id=%s
                AND lower(requester_email)=lower(%s) AND expires_at > now()""",
                (org_id, ticket_id, email)).fetchone() is not None

    def test_sending_enabled(self, org_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT test_sending_enabled FROM worker_controls WHERE org_id=%s", (org_id,)).fetchone()
            return bool(row and row[0])

    def set_test_sending(self, org_id: str, enabled: bool) -> None:
        with self._connect() as conn:
            conn.execute("""INSERT INTO worker_controls(org_id,test_sending_enabled) VALUES (%s,%s)
                ON CONFLICT(org_id) DO UPDATE SET test_sending_enabled=EXCLUDED.test_sending_enabled""",
                (org_id, enabled))

    def unknown(self, org_id: str) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute("""SELECT ticket_id,inbound_thread_id,reply_sha256
                FROM ticket_jobs WHERE org_id=%s AND status='unknown'""", (org_id,)).fetchall()
        return [{"ticket_id": a, "thread_id": b, "reply_sha256": c or ""} for a, b, c in rows]

    def status_counts(self, org_id: str) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT status, count(*) FROM ticket_jobs WHERE org_id=%s GROUP BY status", (org_id,)).fetchall()
        return {status: count for status, count in rows}

    def allow_test_ticket(self, org_id: str, ticket_id: str, email: str,
                          expires_at: datetime) -> None:
        if expires_at <= datetime.now(timezone.utc):
            raise ValueError("Test allowlist expiry must be in the future.")
        with self._connect() as conn:
            conn.execute("""INSERT INTO test_allowlist VALUES (%s,%s,%s,%s)
                ON CONFLICT(org_id,ticket_id,requester_email)
                DO UPDATE SET expires_at=EXCLUDED.expires_at""",
                (org_id, ticket_id, email.casefold(), expires_at))

    def purge(self, *, days: int = 30) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM test_allowlist WHERE expires_at <= now()")
            conn.execute("""DELETE FROM ticket_jobs WHERE status IN ('sent','shadow','reviewed')
                AND updated_at < now() - (%s * interval '1 day')""", (days,))

    def mark_reviewed(self, org_id: str, ticket_id: str, thread_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("""UPDATE ticket_jobs SET status='reviewed', updated_at=now()
                WHERE org_id=%s AND ticket_id=%s AND inbound_thread_id=%s
                AND status IN ('human','unknown') RETURNING ticket_id""",
                (org_id, ticket_id, thread_id)).fetchone()
            return row is not None
