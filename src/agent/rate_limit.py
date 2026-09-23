"""Environment-configured pacing and bounded retries for OpenRouter calls."""

import asyncio
import math
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TypeVar

from dotenv import load_dotenv

T = TypeVar("T")

REQUESTS_PER_MINUTE_ENV = "OPENROUTER_REQUESTS_PER_MINUTE"
DEFAULT_REQUESTS_PER_MINUTE = 20
MAX_429_RETRIES = 3
MAX_BACKOFF_SECONDS = 30.0
WINDOW_SECONDS = 60.0


class RateLimitConfigurationError(ValueError):
    """Raised when the configured OpenRouter request limit is invalid."""


def configured_requests_per_minute() -> int:
    """Read and validate the request limit from the process environment or .env."""
    load_dotenv()
    raw_value = os.getenv(REQUESTS_PER_MINUTE_ENV)
    if raw_value is None:
        return DEFAULT_REQUESTS_PER_MINUTE

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RateLimitConfigurationError(
            f"{REQUESTS_PER_MINUTE_ENV} must be a positive integer; got {raw_value!r}"
        ) from exc
    if value <= 0:
        raise RateLimitConfigurationError(
            f"{REQUESTS_PER_MINUTE_ENV} must be a positive integer; got {raw_value!r}"
        )
    return value


class OpenRouterRateLimiter:
    """A process-local sliding-window limiter for OpenRouter requests."""

    def __init__(
        self,
        requests_per_minute: int | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        limit = (
            configured_requests_per_minute()
            if requests_per_minute is None
            else requests_per_minute
        )
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise RateLimitConfigurationError(
                "requests_per_minute must be a positive integer"
            )
        self.requests_per_minute = limit
        self._clock = clock
        self.sleep = sleep
        self._request_times: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request fits within the configured rolling minute."""
        async with self._lock:
            while True:
                now = self._clock()
                while (
                    self._request_times
                    and now - self._request_times[0] >= WINDOW_SECONDS
                ):
                    self._request_times.popleft()

                if len(self._request_times) < self.requests_per_minute:
                    self._request_times.append(now)
                    return

                wait_seconds = WINDOW_SECONDS - (now - self._request_times[0])
                await self.sleep(max(wait_seconds, 0.0))


def parse_retry_after(
    value: str | None,
    *,
    now: datetime | None = None,
) -> float | None:
    """Parse Retry-After seconds or HTTP-date into a nonnegative delay."""
    if value is None:
        return None

    try:
        delay = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        delay = (retry_at - current_time).total_seconds()

    if not math.isfinite(delay) or delay < 0:
        return None
    return delay


def fallback_backoff_seconds(retry_number: int) -> float:
    """Return capped exponential fallback delay (first retry is one second)."""
    if retry_number < 1:
        raise ValueError("retry_number must be at least 1")
    return min(2.0 ** (retry_number - 1), MAX_BACKOFF_SECONDS)


def _status_code(error: Exception) -> int | None:
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    return status


def _retry_after_header(error: Exception) -> str | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        return None
    for name, value in headers.items():
        if str(name).casefold() == "retry-after":
            return str(value)
    return None


async def call_with_rate_limit(
    request: Callable[[], Awaitable[T]],
    limiter: OpenRouterRateLimiter | None = None,
) -> T:
    """Pace an async request and retry HTTP 429 responses at most three times.

    A valid server Retry-After value takes precedence. Otherwise retries use
    exponential backoff beginning at one second and capped at 30 seconds.
    Non-429 exceptions and exhausted 429 errors propagate to the caller.
    """
    active_limiter = limiter or OpenRouterRateLimiter()

    for retry_number in range(MAX_429_RETRIES + 1):
        await active_limiter.acquire()
        try:
            return await request()
        except Exception as error:
            if _status_code(error) != 429 or retry_number == MAX_429_RETRIES:
                raise

            delay = parse_retry_after(_retry_after_header(error))
            if delay is None:
                delay = fallback_backoff_seconds(retry_number + 1)
            await active_limiter.sleep(delay)

    raise RuntimeError("unreachable rate-limit retry state")
