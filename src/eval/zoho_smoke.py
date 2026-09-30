"""Send one explicitly confirmed smoke-test reply to a controlled Zoho ticket."""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable, Sequence
from typing import Any

from dotenv import load_dotenv

from src.observability.logger import log_tool_event
from zoho_desk_client import ZohoDeskClient

SMOKE_REPLY = (
    "This is a controlled integration smoke test for the support-ticket agent. "
    "No action is needed. Please disregard this test message."
)


class SmokeTestError(RuntimeError):
    """Raised when the single-ticket Zoho smoke check cannot safely run."""


def send_smoke_reply(
    ticket_id: str,
    *,
    client: Any,
    run_id: str,
) -> dict[str, Any]:
    """Send exactly one fixed public smoke reply and log metadata only."""
    started = time.perf_counter()
    try:
        result = client.send_public_reply(ticket_id, SMOKE_REPLY)
        if hasattr(result, "__await__"):
            import asyncio

            result = asyncio.run(result)
    except Exception as error:
        log_tool_event(
            tool_name="zoho_desk_smoke_reply",
            inputs={"zoho_ticket_id": ticket_id},
            output=None,
            error={"code": type(error).__name__},
            latency_ms=(time.perf_counter() - started) * 1000,
            run_id=run_id,
        )
        raise SmokeTestError(
            f"Zoho smoke reply was not confirmed ({type(error).__name__}). Check the ticket before retrying."
        ) from error

    status = result.get("http_status") if isinstance(result, dict) else None
    log_tool_event(
        tool_name="zoho_desk_smoke_reply",
        inputs={"zoho_ticket_id": ticket_id},
        output={"delivery_status": "sent", "http_status": status},
        error=None,
        latency_ms=(time.perf_counter() - started) * 1000,
        run_id=run_id,
    )
    return {"delivery_status": "sent", "http_status": status}


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[[], Any] | None = None,
    confirm_input: Callable[[str], str] = input,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket-id", required=True, help="Existing numeric Zoho ticket API ID.")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Allow one fixed public smoke-test reply after interactive confirmation.",
    )
    args = parser.parse_args(argv)
    ticket_id = args.ticket_id.strip()
    if not ticket_id.isdigit():
        parser.error("--ticket-id must contain digits only.")
    if not args.send:
        print("No reply sent. Re-run with --send only for a ticket and contact you control.")
        return 0

    load_dotenv()
    if os.getenv("ZOHO_DESK_SEND_ENABLED", "").strip().lower() not in {"true", "1", "yes", "on"}:
        parser.error("Set ZOHO_DESK_SEND_ENABLED=true before the explicitly requested smoke send.")
    print(
        f"This will post one public smoke-test reply to Zoho ticket {ticket_id}. "
        "Use only an existing ticket and contact you control."
    )
    ownership = confirm_input(
        "Type CONTROLLED to confirm this is your existing test ticket/contact: "
    ).strip()
    if ownership != "CONTROLLED":
        print("Ownership confirmation did not match; no reply sent.")
        return 2
    confirmation = confirm_input(f"Type the ticket ID {ticket_id} to confirm: ").strip()
    if confirmation != ticket_id:
        print("Confirmation did not match; no reply sent.")
        return 2

    factory = client_factory or ZohoDeskClient.from_env
    try:
        outcome = send_smoke_reply(
            ticket_id,
            client=factory(),
            run_id=f"zoho-smoke-{ticket_id}",
        )
    except Exception as error:
        print(str(error))
        return 1
    print(f"Smoke reply status: {outcome['delivery_status']} (HTTP {outcome['http_status']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
