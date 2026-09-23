import json
from urllib.error import HTTPError
from urllib.parse import urlsplit

import pytest

from zoho_desk_client import (
    ZohoDeskClient,
    ZohoDeskConfigurationError,
    ZohoDeskDeliveryError,
)


class FakeResponse:
    def __init__(self, body: dict | None = None, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(body or {}).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def make_client(opener) -> ZohoDeskClient:
    return ZohoDeskClient(
        api_domain="https://desk.zoho.com",
        accounts_domain="https://accounts.zoho.com",
        organization_id="987654321",
        from_email="support@example.com",
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        timeout_seconds=4,
        opener=opener,
    )


@pytest.mark.asyncio
async def test_refreshes_oauth_and_sends_public_email_reply_once():
    requests = []

    def opener(request, *, timeout):
        requests.append((request, timeout))
        path = urlsplit(request.full_url).path
        if path.endswith("/oauth/v2/token"):
            return FakeResponse(
                {
                    "access_token": "short-lived-access-token",
                    "expires_in_sec": 3600,
                    "api_domain": "https://desk.zoho.in",
                }
            )
        if request.get_method() == "GET":
            return FakeResponse({"id": "12345", "email": "customer@example.com"})
        return FakeResponse({"id": "reply-thread-1"})

    client = make_client(opener)
    result = await client.send_public_reply("12345", "Approved response.")

    token_request, ticket_request, reply_request = [item[0] for item in requests]
    assert len(requests) == 3
    assert token_request.full_url == "https://accounts.zoho.com/oauth/v2/token"
    assert json.loads(ticket_request.data or b"{}") == {}
    assert ticket_request.get_method() == "GET"
    assert ticket_request.full_url == "https://desk.zoho.in/api/v1/tickets/12345"
    assert ticket_request.get_header("Authorization") == (
        "Zoho-oauthtoken short-lived-access-token"
    )
    assert ticket_request.get_header("Orgid") == "987654321"
    assert reply_request.get_method() == "POST"
    assert reply_request.full_url == (
        "https://desk.zoho.in/api/v1/tickets/12345/sendReply?isPrivate=false&sendImmediately=true"
    )
    assert reply_request.get_header("Authorization") == (
        "Zoho-oauthtoken short-lived-access-token"
    )
    assert json.loads(reply_request.data) == {
        "channel": "EMAIL",
        "to": "customer@example.com",
        "fromEmailAddress": "support@example.com",
        "contentType": "plainText",
        "content": "Approved response.",
        "isForward": False,
    }
    assert all(timeout == 4 for _, timeout in requests)
    assert result == {
        "zoho_ticket_id": "12345",
        "thread_id": "reply-thread-1",
        "http_status": 200,
    }


@pytest.mark.asyncio
async def test_reuses_access_token_for_subsequent_ticket_replies():
    requests = []

    def opener(request, *, timeout):
        requests.append(request)
        if urlsplit(request.full_url).path.endswith("/oauth/v2/token"):
            return FakeResponse({"access_token": "token", "expires_in_sec": 3600})
        if request.get_method() == "GET":
            return FakeResponse({"email": "customer@example.com"})
        return FakeResponse({"id": "thread"})

    client = make_client(opener)
    await client.send_public_reply("100", "First reply")
    await client.send_public_reply("101", "Second reply")

    assert sum(urlsplit(request.full_url).path.endswith("/oauth/v2/token") for request in requests) == 1
    assert sum(request.get_method() == "POST" for request in requests) == 2


@pytest.mark.asyncio
async def test_invalid_ticket_id_is_rejected_before_any_request():
    calls = []
    client = make_client(lambda request, **kwargs: calls.append(request))

    with pytest.raises(ZohoDeskConfigurationError, match="numeric"):
        await client.send_public_reply("../unsafe", "Reply")

    assert calls == []


@pytest.mark.asyncio
async def test_ticket_without_requester_email_fails_before_sending():
    requests = []

    def opener(request, *, timeout):
        requests.append(request)
        if urlsplit(request.full_url).path.endswith("/oauth/v2/token"):
            return FakeResponse({"access_token": "token"})
        return FakeResponse({"id": "12345", "email": None})

    client = make_client(opener)
    with pytest.raises(ZohoDeskDeliveryError) as error:
        await client.send_public_reply("12345", "Reply")

    assert error.value.delivery_status == "failed"
    assert len(requests) == 2
    assert all(request.get_method() != "POST" for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_status"),
    [(403, "failed"), (503, "unknown")],
)
async def test_reply_http_error_classification_and_no_retry(status_code, expected_status):
    requests = []

    def opener(request, *, timeout):
        requests.append(request)
        path = urlsplit(request.full_url).path
        if path.endswith("/oauth/v2/token"):
            return FakeResponse({"access_token": "token"})
        if request.get_method() == "GET":
            return FakeResponse({"email": "customer@example.com"})
        raise HTTPError(request.full_url, status_code, "failure", {}, None)

    client = make_client(opener)
    with pytest.raises(ZohoDeskDeliveryError) as error:
        await client.send_public_reply("12345", "Reply")

    assert error.value.delivery_status == expected_status
    assert error.value.http_status == status_code
    assert sum(request.get_method() == "POST" for request in requests) == 1


@pytest.mark.asyncio
async def test_timeout_during_reply_is_unknown_and_not_replayed():
    requests = []

    def opener(request, *, timeout):
        requests.append(request)
        path = urlsplit(request.full_url).path
        if path.endswith("/oauth/v2/token"):
            return FakeResponse({"access_token": "token"})
        if request.get_method() == "GET":
            return FakeResponse({"email": "customer@example.com"})
        raise TimeoutError("network timed out")

    client = make_client(opener)
    with pytest.raises(ZohoDeskDeliveryError) as error:
        await client.send_public_reply("12345", "Reply")

    assert error.value.delivery_status == "unknown"
    assert sum(request.get_method() == "POST" for request in requests) == 1


def test_rejects_non_zoho_api_domains():
    with pytest.raises(ZohoDeskConfigurationError, match="Zoho HTTPS domain"):
        ZohoDeskClient(
            api_domain="https://attacker.example",
            accounts_domain="https://accounts.zoho.com",
            organization_id="123",
            from_email="support@example.com",
            client_id="id",
            client_secret="secret",
            refresh_token="refresh",
        )
