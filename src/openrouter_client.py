"""OpenAI-compatible OpenRouter client with bounded account-level 429 retries."""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from dotenv import load_dotenv
from openai import APIStatusError, AsyncOpenAI

from src.agent.rate_limit import OpenRouterRateLimiter

T = TypeVar("T")
logger = logging.getLogger(__name__)

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MAX_429_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0


class OpenRouterConfigurationError(ValueError):
    """Raised when required OpenRouter settings are missing or invalid."""


class OpenRouterRateLimitError(RuntimeError):
    """Raised after an OpenRouter account-level 429 exhausts bounded retries."""

    def __init__(self, attempts: int) -> None:
        self.attempts = attempts
        super().__init__(
            f"OpenRouter continued returning HTTP 429 after {attempts} attempts "
            f"({MAX_429_RETRIES} retries)."
        )


def parse_openrouter_models(raw_models: str | Sequence[str]) -> tuple[str, ...]:
    """Parse a comma-separated list of OpenRouter fallback model IDs."""
    if isinstance(raw_models, str):
        models = tuple(item.strip() for item in raw_models.split(",") if item.strip())
    else:
        models = tuple(item.strip() for item in raw_models if item.strip())

    if not 2 <= len(models) <= 3:
        raise OpenRouterConfigurationError(
            "OPENROUTER_MODELS must contain 2 or 3 comma-separated fallback "
            "model IDs in priority order."
        )
    if len(set(models)) != len(models):
        raise OpenRouterConfigurationError("OPENROUTER_MODELS cannot contain duplicates.")
    return models


class OpenRouterClient:
    """Wrap OpenAI-compatible chat completion calls to OpenRouter."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        models: str | Sequence[str] | None = None,
        client: Any | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rate_limiter: OpenRouterRateLimiter | None = None,
    ) -> None:
        load_dotenv()
        configured_key = api_key or os.getenv("OPENROUTER_API_KEY")
        configured_url = base_url or os.getenv(
            "OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL
        )
        configured_models = models if models is not None else os.getenv("OPENROUTER_MODELS", "")

        if client is None and not configured_key:
            raise OpenRouterConfigurationError("OPENROUTER_API_KEY is required.")

        self.models = parse_openrouter_models(configured_models)
        self._client = client or AsyncOpenAI(
            api_key=configured_key,
            base_url=configured_url,
        )
        self._sleep = sleep
        self._rate_limiter = rate_limiter or OpenRouterRateLimiter(sleep=sleep)

    async def create_chat_completion(
        self,
        *,
        model: str,
        messages: Sequence[dict[str, Any]],
        **options: Any,
    ) -> Any:
        """Create a completion with model fallback and bounded 429 retries.

        ``model`` is the primary model for this call. The ordered
        ``OPENROUTER_MODELS`` configuration is sent in full as the fallbacks.
        """
        if not model.strip():
            raise ValueError("model must be a non-empty primary model ID")
        if "model" in options or "messages" in options:
            raise TypeError("Pass model and messages by keyword, not through options.")

        extra_body = options.pop("extra_body", None) or {}
        if not isinstance(extra_body, dict):
            raise TypeError("extra_body must be a dictionary when provided.")
        request_options = {
            **options,
            "model": model,
            "messages": list(messages),
            "extra_body": {**extra_body, "models": list(self.models)},
        }

        for retry_number in range(MAX_429_RETRIES + 1):
            await self._rate_limiter.acquire()
            try:
                return await self._client.chat.completions.create(**request_options)
            except APIStatusError as error:
                if error.status_code != 429:
                    raise

                attempt = retry_number + 1
                if retry_number == MAX_429_RETRIES:
                    logger.warning(
                        "OpenRouter returned HTTP 429 on attempt %d/%d; retry limit exhausted.",
                        attempt,
                        MAX_429_RETRIES + 1,
                    )
                    raise OpenRouterRateLimitError(attempts=attempt) from error

                delay = INITIAL_BACKOFF_SECONDS * (2**retry_number)
                logger.warning(
                    "OpenRouter returned HTTP 429 on attempt %d/%d; retrying in %.1f seconds.",
                    attempt,
                    MAX_429_RETRIES + 1,
                    delay,
                )
                await self._sleep(delay)

        raise RuntimeError("unreachable OpenRouter retry state")
