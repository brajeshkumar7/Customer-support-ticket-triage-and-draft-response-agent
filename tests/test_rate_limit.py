from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

import src.agent.rate_limit as rate_limit
from src.agent.rate_limit import (
    OpenRouterRateLimiter,
    RateLimitConfigurationError,
    call_with_rate_limit,
    configured_requests_per_minute,
    fallback_backoff_seconds,
    parse_retry_after,
)


class FakeResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.headers = headers or {}


class FakeAPIError(Exception):
    def __init__(self, status_code: int, headers: dict[str, str] | None = None):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.response = FakeResponse(status_code, headers)


def test_request_limit_defaults_to_free_tier_value(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit, "load_dotenv", lambda: None)
    monkeypatch.delenv("OPENROUTER_REQUESTS_PER_MINUTE", raising=False)

    assert configured_requests_per_minute() == 20


def test_request_limit_uses_environment_value(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit, "load_dotenv", lambda: None)
    monkeypatch.setenv("OPENROUTER_REQUESTS_PER_MINUTE", "75")

    assert configured_requests_per_minute() == 75


@pytest.mark.parametrize("raw_value", ["0", "-1", "abc", "2.5"])
def test_request_limit_rejects_invalid_values(monkeypatch, raw_value: str) -> None:
    monkeypatch.setattr(rate_limit, "load_dotenv", lambda: None)
    monkeypatch.setenv("OPENROUTER_REQUESTS_PER_MINUTE", raw_value)

    with pytest.raises(RateLimitConfigurationError, match="positive integer"):
        configured_requests_per_minute()


@pytest.mark.asyncio
async def test_limiter_waits_for_the_rolling_minute_window() -> None:
    now = [0.0]
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        now[0] += delay

    limiter = OpenRouterRateLimiter(2, clock=lambda: now[0], sleep=fake_sleep)
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()

    assert sleeps == [60.0]


def test_retry_after_accepts_http_date() -> None:
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    header = format_datetime(now + timedelta(seconds=5), usegmt=True)

    assert parse_retry_after(header, now=now) == 5.0


@pytest.mark.asyncio
async def test_429_retry_honors_retry_after_header() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def request() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise FakeAPIError(429, {"Retry-After": "2.5"})
        return "ok"

    limiter = OpenRouterRateLimiter(60, sleep=fake_sleep)
    result = await call_with_rate_limit(request, limiter)

    assert result == "ok"
    assert attempts == 2
    assert sleeps == [2.5]


@pytest.mark.asyncio
async def test_429_without_valid_header_uses_exponential_backoff() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def request() -> str:
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise FakeAPIError(429, {"retry-after": "not-a-delay"})
        return "ok"

    limiter = OpenRouterRateLimiter(60, sleep=fake_sleep)
    assert await call_with_rate_limit(request, limiter) == "ok"

    assert attempts == 3
    assert sleeps == [1.0, 2.0]
    assert fallback_backoff_seconds(10) == 30.0


@pytest.mark.asyncio
async def test_429_retries_stop_after_three_retries() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def request() -> None:
        nonlocal attempts
        attempts += 1
        raise FakeAPIError(429)

    limiter = OpenRouterRateLimiter(60, sleep=fake_sleep)
    with pytest.raises(FakeAPIError):
        await call_with_rate_limit(request, limiter)

    assert attempts == 4
    assert sleeps == [1.0, 2.0, 4.0]


@pytest.mark.asyncio
async def test_non_429_error_is_not_retried() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def request() -> None:
        nonlocal attempts
        attempts += 1
        raise FakeAPIError(500)

    limiter = OpenRouterRateLimiter(60, sleep=fake_sleep)
    with pytest.raises(FakeAPIError):
        await call_with_rate_limit(request, limiter)

    assert attempts == 1
    assert sleeps == []
