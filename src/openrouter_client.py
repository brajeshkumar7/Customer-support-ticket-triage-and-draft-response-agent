"""OpenAI-compatible OpenRouter client with bounded account-level 429 retries."""

import asyncio
import os
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from dotenv import load_dotenv
from openai import APIStatusError, AsyncOpenAI

from src.agent.rate_limit import OpenRouterRateLimiter
from src.observability.logger import log_llm_event, log_rate_limit_event

T = TypeVar("T")

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
        run_id: str | None = None,
        call_name: str = "chat_completion",
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

        safe_inputs = {
            "model": model,
            "messages": list(messages),
            "options": {key: value for key, value in request_options.items()
                        if key not in {"model", "messages"}},
        }
        for retry_number in range(MAX_429_RETRIES + 1):
            attempt = retry_number + 1
            await self._rate_limiter.acquire()
            started = time.perf_counter()
            try:
                response = await self._client.chat.completions.create(**request_options)
            except APIStatusError as error:
                latency_ms = (time.perf_counter() - started) * 1000
                failure = {
                    "type": type(error).__name__,
                    "status_code": error.status_code,
                }
                _write_llm_event(
                    run_id=run_id,
                    call_name=call_name,
                    inputs={**safe_inputs, "attempt": attempt},
                    output=None,
                    latency_ms=latency_ms,
                    token_cost=None,
                    error=failure,
                )
                if error.status_code != 429:
                    raise

                delay = (
                    INITIAL_BACKOFF_SECONDS * (2**retry_number)
                    if retry_number < MAX_429_RETRIES
                    else 0.0
                )
                _write_rate_limit_event(
                    run_id=run_id,
                    call_name=call_name,
                    inputs={"model": model, "attempt": attempt},
                    output={"status_code": 429, "retry_delay_seconds": delay},
                    latency_ms=latency_ms,
                    error={"type": type(error).__name__, "status_code": 429},
                )
                if retry_number == MAX_429_RETRIES:
                    raise OpenRouterRateLimitError(attempts=attempt) from error

                await self._sleep(delay)
            except Exception as error:
                _write_llm_event(
                    run_id=run_id,
                    call_name=call_name,
                    inputs={**safe_inputs, "attempt": attempt},
                    output=None,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    token_cost=None,
                    error={"type": type(error).__name__},
                )
                raise
            else:
                _write_llm_event(
                    run_id=run_id,
                    call_name=call_name,
                    inputs={**safe_inputs, "attempt": attempt},
                    output=_completion_log_output(response),
                    latency_ms=(time.perf_counter() - started) * 1000,
                    token_cost=_completion_cost(response),
                )
                return response

        raise RuntimeError("unreachable OpenRouter retry state")


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    result = getattr(value, name, None)
    if result is not None:
        return result
    extras = getattr(value, "model_extra", None)
    return extras.get(name) if isinstance(extras, dict) else None


def _completion_cost(response: Any) -> float | None:
    usage = _field(response, "usage")
    cost = _field(usage, "cost")
    try:
        return float(cost) if cost is not None else None
    except (TypeError, ValueError):
        return None


def _completion_log_output(response: Any) -> dict[str, Any]:
    choices = _field(response, "choices") or []
    first_choice = choices[0] if choices else None
    message = _field(first_choice, "message")
    usage = _field(response, "usage")
    return {
        "model": _field(response, "model"),
        "content": _field(message, "content"),
        "usage": usage,
    }


def _write_llm_event(**event: Any) -> None:
    try:
        log_llm_event(**event)
    except OSError:
        # Observability failure must not change the API result.
        pass


def _write_rate_limit_event(**event: Any) -> None:
    try:
        log_rate_limit_event(**event)
    except OSError:
        # The bounded retry path remains available if the disk is unavailable.
        pass
