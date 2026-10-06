"""Manage the controlled worker allowlist and emergency send switch."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone

from dotenv import load_dotenv

from src.agent.deployment import DeploymentConfig
from src.agent.job_store import JobStore


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    allow = actions.add_parser("allow-test-ticket")
    allow.add_argument("--ticket-id", required=True)
    allow.add_argument("--email", required=True)
    allow.add_argument("--expires", required=True, help="ISO-8601 timestamp with timezone")
    actions.add_parser("enable-test-sending")
    actions.add_parser("disable-test-sending")
    reviewed = actions.add_parser("mark-reviewed")
    reviewed.add_argument("--ticket-id", required=True)
    reviewed.add_argument("--thread-id", required=True)
    args = parser.parse_args()
    config = DeploymentConfig.from_env()
    if config.mode != "test":
        parser.error("Worker administration requires DEPLOYMENT_MODE=test.")
    store = JobStore(config.database_url)
    store.initialize()
    if args.action == "allow-test-ticket":
        if not re.fullmatch(r"[0-9]+", args.ticket_id) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", args.email):
            parser.error("Provide an exact numeric Zoho API ticket ID and controlled requester email.")
        try:
            expiry = datetime.fromisoformat(args.expires.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                raise ValueError("Timezone required")
            store.allow_test_ticket(config.organization_id, args.ticket_id, args.email, expiry)
        except ValueError as error:
            parser.error(str(error))
        print("Controlled ticket/contact allowlisted until", expiry.astimezone(timezone.utc).isoformat())
    elif args.action == "mark-reviewed":
        if not args.ticket_id.isdigit() or not args.thread_id.isdigit():
            parser.error("Ticket and inbound thread IDs must be numeric.")
        if not store.mark_reviewed(config.organization_id, args.ticket_id, args.thread_id):
            parser.error("No human/unknown job matches; inspect Zoho and the ledger first.")
        print("Human review recorded; this job will not be retried.")
    else:
        enabled = args.action == "enable-test-sending"
        store.set_test_sending(config.organization_id, enabled)
        print("Test sending enabled" if enabled else "Test sending disabled")


if __name__ == "__main__":
    main()
