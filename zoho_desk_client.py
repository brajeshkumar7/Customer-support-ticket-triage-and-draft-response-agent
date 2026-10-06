"""Host-side Zoho Desk sender, kept outside the tool sandbox image."""

import asyncio
import json
import os
import re
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from src.observability.logger import log_tool_event


_DESK_HOSTS = {
    "desk.zoho.com",
    "desk.zoho.in",
    "desk.zoho.com.au",
    "desk.zohocloud.ca",
    "desk.zoho.sa",
    "desk.zoho.jp",
    "desk.zoho.com.cn",
    "desk.zoho.eu",
    "desk.zoho.sg",
    "desk.zoho.ae",
}
# Zoho Desk REST endpoints use Desk-specific regional hosts. A Self Client
# token exchange can instead return Zoho's generic API gateway for that same
# data center; in that case, keep the configured Desk host after checking the
# region matches.
_ZOHOAPIS_TO_DESK_HOST = {
    "www.zohoapis.com": "desk.zoho.com",
    "www.zohoapis.in": "desk.zoho.in",
    "www.zohoapis.com.au": "desk.zoho.com.au",
    "www.zohoapis.ca": "desk.zohocloud.ca",
    "www.zohoapis.sa": "desk.zoho.sa",
    "www.zohoapis.jp": "desk.zoho.jp",
    "www.zohoapis.com.cn": "desk.zoho.com.cn",
    "www.zohoapis.eu": "desk.zoho.eu",
    "www.zohoapis.sg": "desk.zoho.sg",
    "www.zohoapis.ae": "desk.zoho.ae",
}
_ACCOUNTS_HOSTS = {
    "accounts.zoho.com",
    "accounts.zoho.in",
    "accounts.zoho.com.au",
    "accounts.zoho.ca",
    "accounts.zoho.sa",
    "accounts.zoho.jp",
    "accounts.zoho.com.cn",
    "accounts.zoho.eu",
    "accounts.zoho.sg",
    "accounts.zoho.ae",
}


class ZohoDeskConfigurationError(ValueError):
    """Zoho Desk sending is enabled but configuration is missing or invalid."""


class ZohoDeskDeliveryError(RuntimeError):
    """Zoho Desk did not confirm a ticket reply was sent."""

    def __init__(
        self,
        message: str,
        *,
        delivery_status: str,
        http_status: int | None = None,
    ) -> None:
        self.delivery_status = delivery_status
        self.http_status = http_status
        super().__init__(message)


def _https_origin(value: str, *, name: str, allowed_hosts: set[str]) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ZohoDeskConfigurationError(f"{name} must be a supported Zoho HTTPS domain.")
    return f"https://{parsed.hostname}"


class ZohoDeskClient:
    """Fetch existing Zoho Desk tickets and send customer-facing email replies."""

    def __init__(
        self,
        *,
        api_domain: str,
        accounts_domain: str,
        organization_id: str,
        from_email: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        timeout_seconds: float = 12.0,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.api_domain = _https_origin(
            api_domain, name="ZOHO_DESK_API_DOMAIN", allowed_hosts=_DESK_HOSTS
        )
        self.accounts_domain = _https_origin(
            accounts_domain,
            name="ZOHO_ACCOUNTS_DOMAIN",
            allowed_hosts=_ACCOUNTS_HOSTS,
        )
        if not re.fullmatch(r"[0-9]+", organization_id.strip()):
            raise ZohoDeskConfigurationError("ZOHO_DESK_ORG_ID must be numeric.")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", from_email.strip()):
            raise ZohoDeskConfigurationError("ZOHO_DESK_FROM_EMAIL must be an email address.")
        for name, value in (
            ("ZOHO_CLIENT_ID", client_id),
            ("ZOHO_CLIENT_SECRET", client_secret),
            ("ZOHO_REFRESH_TOKEN", refresh_token),
        ):
            if not value.strip():
                raise ZohoDeskConfigurationError(f"{name} is required.")
        if timeout_seconds <= 0:
            raise ValueError("Zoho Desk request timeout must be positive.")

        self.organization_id = organization_id.strip()
        self.from_email = from_email.strip()
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.refresh_token = refresh_token.strip()
        self.timeout_seconds = timeout_seconds
        self._opener = opener or urlopen
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "ZohoDeskClient":
        """Create the sender from a refresh token and region-specific domains."""
        required = {
            "ZOHO_DESK_API_DOMAIN": os.getenv("ZOHO_DESK_API_DOMAIN", ""),
            "ZOHO_ACCOUNTS_DOMAIN": os.getenv("ZOHO_ACCOUNTS_DOMAIN", ""),
            "ZOHO_DESK_ORG_ID": os.getenv("ZOHO_DESK_ORG_ID", ""),
            "ZOHO_DESK_FROM_EMAIL": os.getenv("ZOHO_DESK_FROM_EMAIL", ""),
            "ZOHO_CLIENT_ID": os.getenv("ZOHO_CLIENT_ID", ""),
            "ZOHO_CLIENT_SECRET": os.getenv("ZOHO_CLIENT_SECRET", ""),
            "ZOHO_REFRESH_TOKEN": os.getenv("ZOHO_REFRESH_TOKEN", ""),
        }
        missing = [key for key, value in required.items() if not value.strip()]
        if missing:
            raise ZohoDeskConfigurationError(
                "Missing Zoho Desk configuration: " + ", ".join(missing) + "."
            )
        return cls(
            api_domain=required["ZOHO_DESK_API_DOMAIN"],
            accounts_domain=required["ZOHO_ACCOUNTS_DOMAIN"],
            organization_id=required["ZOHO_DESK_ORG_ID"],
            from_email=required["ZOHO_DESK_FROM_EMAIL"],
            client_id=required["ZOHO_CLIENT_ID"],
            client_secret=required["ZOHO_CLIENT_SECRET"],
            refresh_token=required["ZOHO_REFRESH_TOKEN"],
        )

    async def send_public_reply(self, ticket_id: str, body: str) -> dict[str, Any]:
        """Resolve the ticket recipient, then send exactly one public email reply."""
        return await asyncio.to_thread(self._send_public_reply, ticket_id, body)

    async def send_controlled_reply(
        self, ticket_id: str, body: str, *, expected_email: str,
        expected_inbound_thread_id: str,
    ) -> dict[str, Any]:
        """Recheck recipient and thread immediately before the single POST."""
        return await asyncio.to_thread(
            self._send_public_reply, ticket_id, body, expected_email,
            expected_inbound_thread_id,
        )

    async def fetch_ticket(self, ticket_id: str) -> dict[str, Any]:
        """Fetch the limited ticket fields needed to run the agent, without sending."""
        started = time.perf_counter()
        try:
            result = await asyncio.to_thread(self._fetch_ticket, ticket_id)
        except Exception as error:
            log_tool_event(
                tool_name="zoho_desk_fetch_ticket",
                inputs={"zoho_ticket_id": ticket_id},
                output=None,
                error={"code": type(error).__name__},
                latency_ms=(time.perf_counter() - started) * 1000,
                run_id=f"zoho-ticket-{ticket_id}",
            )
            raise
        log_tool_event(
            tool_name="zoho_desk_fetch_ticket",
            inputs={"zoho_ticket_id": ticket_id},
            output={
                "channel": result.get("channel"),
                "has_subject": bool(result.get("subject")),
                "has_description": bool(result.get("description")),
            },
            error=None,
            latency_ms=(time.perf_counter() - started) * 1000,
            run_id=f"zoho-ticket-{ticket_id}",
        )
        return result

    async def list_modified_tickets(self, offset: int, limit: int = 50) -> list[dict[str, Any]]:
        """Read one page, newest first; callers persist their own cursor."""
        if offset < 0 or not 1 <= limit <= 50:
            raise ValueError("Invalid Zoho ticket page.")
        result = await asyncio.to_thread(
            self._api_request, "GET", "tickets", token=self._get_access_token(),
            query={"from": str(offset), "limit": str(limit), "sortBy": "-modifiedTime"},
        )
        data = result.get("data")
        if not isinstance(data, list):
            raise ZohoDeskDeliveryError("Zoho ticket listing was invalid.", delivery_status="failed")
        return data

    async def list_threads(self, ticket_id: str) -> list[dict[str, Any]]:
        """Return all thread summaries; refuse malformed or excessively large histories."""
        if not re.fullmatch(r"[0-9]+", str(ticket_id)):
            raise ZohoDeskConfigurationError("zoho_ticket_id must be numeric.")
        threads: list[dict[str, Any]] = []
        for offset in range(0, 1000, 50):
            page = await asyncio.to_thread(
                self._api_request, "GET", f"tickets/{ticket_id}/threads",
                token=self._get_access_token(),
                query={"from": str(offset), "limit": "50"},
            )
            data = page.get("data")
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise ZohoDeskDeliveryError("Zoho thread listing was invalid.", delivery_status="failed")
            threads.extend(data)
            if len(data) < 50:
                return threads
        raise ZohoDeskDeliveryError("Zoho thread history exceeds safe limit.", delivery_status="failed")

    async def fetch_thread(self, ticket_id: str, thread_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9]+", str(ticket_id)) or not re.fullmatch(r"[0-9]+", str(thread_id)):
            raise ZohoDeskConfigurationError("Zoho ticket and thread IDs must be numeric.")
        return await asyncio.to_thread(
            self._api_request, "GET", f"tickets/{ticket_id}/threads/{thread_id}",
            token=self._get_access_token(),
        )

    async def add_private_note(self, ticket_id: str, note: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9]+", str(ticket_id)):
            raise ZohoDeskConfigurationError("zoho_ticket_id must be numeric.")
        return await asyncio.to_thread(
            self._api_request, "POST", f"tickets/{ticket_id}/comments",
            token=self._get_access_token(),
            body={"content": note, "isPublic": False},
        )

    def _refresh_access_token(self) -> str:
        payload = urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ).encode("ascii")
        request = Request(
            f"{self.accounts_domain}/oauth/v2/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise ZohoDeskConfigurationError(
                f"Zoho OAuth token refresh failed with HTTP {error.code}."
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ZohoDeskDeliveryError(
                "Could not refresh Zoho credentials; no ticket reply was attempted.",
                delivery_status="failed",
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as error:
            raise ZohoDeskConfigurationError(
                "Zoho OAuth returned an invalid token response."
            ) from error

        token = result.get("access_token") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            raise ZohoDeskConfigurationError("Zoho OAuth did not return an access token.")
        api_domain = result.get("api_domain")
        if isinstance(api_domain, str) and api_domain.strip():
            trusted_api_origin = _https_origin(
                api_domain,
                name="Zoho OAuth api_domain",
                allowed_hosts=_DESK_HOSTS | set(_ZOHOAPIS_TO_DESK_HOST),
            )
            returned_host = urlsplit(trusted_api_origin).hostname
            mapped_desk_host = _ZOHOAPIS_TO_DESK_HOST.get(returned_host or "")
            if mapped_desk_host:
                configured_host = urlsplit(self.api_domain).hostname
                if configured_host != mapped_desk_host:
                    raise ZohoDeskConfigurationError(
                        "Zoho OAuth api_domain and ZOHO_DESK_API_DOMAIN belong to "
                        "different data centers."
                    )
            else:
                self.api_domain = trusted_api_origin
        expires_in = result.get("expires_in_sec", result.get("expires_in", 3600))
        try:
            lifetime = max(60, int(expires_in))
        except (TypeError, ValueError):
            lifetime = 3600
        self._access_token = token
        self._token_expires_at = time.monotonic() + lifetime
        return token

    def _get_access_token(self) -> str:
        with self._token_lock:
            if self._access_token and time.monotonic() < self._token_expires_at - 60:
                return self._access_token
            return self._refresh_access_token()

    def _fetch_ticket(self, ticket_id: str) -> dict[str, Any]:
        ticket_id = str(ticket_id).strip()
        if not re.fullmatch(r"[0-9]+", ticket_id):
            raise ZohoDeskConfigurationError("zoho_ticket_id must be numeric.")
        token = self._get_access_token()
        try:
            ticket = self._api_request("GET", f"tickets/{ticket_id}", token=token)
        except HTTPError as error:
            raise ZohoDeskDeliveryError(
                f"Zoho Desk could not retrieve the ticket (HTTP {error.code}).",
                delivery_status="failed",
                http_status=error.code,
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ZohoDeskDeliveryError(
                "Zoho Desk ticket lookup failed.", delivery_status="failed"
            ) from error
        except Exception as error:
            raise ZohoDeskDeliveryError(
                "Zoho Desk ticket details could not be read.", delivery_status="failed"
            ) from error

        returned_id = ticket.get("id", ticket_id)
        if str(returned_id) != ticket_id:
            raise ZohoDeskDeliveryError(
                "Zoho returned a different ticket than requested; no agent run was started.",
                delivery_status="failed",
            )
        return {
            "id": str(ticket.get("id", ticket_id)),
            "subject": ticket.get("subject"),
            "description": ticket.get("description"),
            "channel": ticket.get("channel"),
            "email": ticket.get("email"),
            "status": ticket.get("status"),
            "modifiedTime": ticket.get("modifiedTime"),
        }

    def _api_request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.api_domain}/api/v1/{path.lstrip('/')}"
        if query:
            parsed_url = urlsplit(url)
            url = urlunsplit(
                (
                    parsed_url.scheme,
                    parsed_url.netloc,
                    parsed_url.path,
                    urlencode(query),
                    parsed_url.fragment,
                )
            )
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            url,
            data=data,
            headers={
                "Authorization": f"Zoho-oauthtoken {token}",
                "orgId": self.organization_id,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )
        started = time.perf_counter()
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                http_status = getattr(response, "status", 200)
        except Exception as error:
            try:
                log_tool_event(tool_name="zoho_api", inputs={"method": method, "path": path},
                    output=None, error={"type": type(error).__name__},
                    latency_ms=(time.perf_counter() - started) * 1000)
            except OSError:
                pass
            raise
        try:
            log_tool_event(tool_name="zoho_api", inputs={"method": method, "path": path},
                output={"http_status": http_status}, error=None,
                latency_ms=(time.perf_counter() - started) * 1000)
        except OSError:
            pass
        if not raw:
            return {"_http_status": http_status}
        result = json.loads(raw.decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("Zoho Desk returned an unexpected response format.")
        result["_http_status"] = http_status
        return result

    def _send_public_reply(self, ticket_id: str, body: str,
                           expected_email: str | None = None,
                           expected_inbound_thread_id: str | None = None) -> dict[str, Any]:
        ticket_id = str(ticket_id).strip()
        if not re.fullmatch(r"[0-9]+", ticket_id):
            raise ZohoDeskConfigurationError("zoho_ticket_id must be numeric.")
        if not body.strip():
            raise ValueError("A non-empty response is required before sending.")
        token = self._get_access_token()

        try:
            ticket = self._api_request("GET", f"tickets/{ticket_id}", token=token)
        except HTTPError as error:
            raise ZohoDeskDeliveryError(
                f"Zoho Desk could not retrieve the ticket (HTTP {error.code}); no reply was attempted.",
                delivery_status="failed",
                http_status=error.code,
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ZohoDeskDeliveryError(
                "Zoho Desk ticket lookup failed; no reply was attempted.",
                delivery_status="failed",
            ) from error
        except Exception as error:
            raise ZohoDeskDeliveryError(
                "Zoho Desk ticket details could not be validated; no reply was attempted.",
                delivery_status="failed",
            ) from error
        recipient = ticket.get("email")
        if not isinstance(recipient, str) or not re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient.strip()
        ):
            raise ZohoDeskDeliveryError(
                "Zoho Desk ticket has no valid requester email; no reply was attempted.",
                delivery_status="failed",
            )
        if expected_email is not None and recipient.strip().casefold() != expected_email.casefold():
            raise ZohoDeskDeliveryError("Requester changed before send; no reply was attempted.", delivery_status="failed")
        if expected_inbound_thread_id is not None:
            if str(ticket.get("channel", "")).casefold() != "email" or str(ticket.get("status", "")).casefold() in {"closed", "spam", "deleted"}:
                raise ZohoDeskDeliveryError("Ticket channel or status changed; no reply was attempted.", delivery_status="failed")
            try:
                threads = self._api_request(
                    "GET", f"tickets/{ticket_id}/threads", token=token,
                    query={"from": "0", "limit": "50"},
                ).get("data")
            except Exception as error:
                raise ZohoDeskDeliveryError("Could not recheck threads; no reply was attempted.", delivery_status="failed") from error
            if not isinstance(threads, list) or not threads or len(threads) >= 50:
                raise ZohoDeskDeliveryError("Thread history is unavailable; no reply was attempted.", delivery_status="failed")
            latest = max(threads, key=lambda item: str(item.get("createdTime", "")))
            if (str(latest.get("id")) != expected_inbound_thread_id
                    or str(latest.get("direction", "")).casefold() not in {"in", "incoming"}):
                raise ZohoDeskDeliveryError("A newer or outgoing thread exists; no reply was attempted.", delivery_status="failed")

        reply = {
            "channel": "EMAIL",
            "to": recipient.strip(),
            "fromEmailAddress": self.from_email,
            "contentType": "plainText",
            "content": body,
            "isForward": False,
        }
        try:
            response = self._api_request(
                "POST",
                f"tickets/{ticket_id}/sendReply",
                token=token,
                body=reply,
                query={"isPrivate": "false", "sendImmediately": "true"},
            )
        except HTTPError as error:
            status = "failed" if 400 <= error.code < 500 else "unknown"
            raise ZohoDeskDeliveryError(
                f"Zoho Desk reply request returned HTTP {error.code}.",
                delivery_status=status,
                http_status=error.code,
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ZohoDeskDeliveryError(
                "Zoho Desk did not confirm whether the reply was sent.",
                delivery_status="unknown",
            ) from error
        if expected_inbound_thread_id is not None and not response.get("id"):
            raise ZohoDeskDeliveryError(
                "Zoho did not return a reply thread ID; delivery needs reconciliation.",
                delivery_status="unknown",
            )
        return {
            "zoho_ticket_id": ticket_id,
            "thread_id": response.get("id"),
            "http_status": response.get("_http_status", 200),
        }
