from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIStatusError

import src.openrouter_client as openrouter_module
import src.agent.rate_limit as rate_limit_module
from src.openrouter_client import (
    OpenRouterClient,
    OpenRouterConfigurationError,
    OpenRouterRateLimitError,
    parse_openrouter_models,
)


def make_api_error(status_code: int) -> APIStatusError:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return APIStatusError(
        f"HTTP {status_code}",
        response=response,
        body={"error": f"HTTP {status_code}"},
    )


def fake_client(create: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )


def test_models_are_parsed_as_an_ordered_fallback_list() -> None:
    assert parse_openrouter_models(" primary , fallback-a, fallback-b ") == (
        "primary",
        "fallback-a",
        "fallback-b",
    )


@pytest.mark.parametrize("value", ["", "one-model", "a,b,c,d", "a,a"])
def test_models_reject_invalid_fallback_configuration(value: str) -> None:
    with pytest.raises(OpenRouterConfigurationError):
        parse_openrouter_models(value)


def test_client_loads_fallback_models_from_environment(monkeypatch) -> None:
    monkeypatch.setattr(openrouter_module, "load_dotenv", lambda: None)
    monkeypatch.setenv("OPENROUTER_MODELS", "fallback-a, fallback-b")
    create = AsyncMock()

    wrapper = OpenRouterClient(client=fake_client(create))

    assert wrapper.models == ("fallback-a", "fallback-b")


def test_client_configures_default_limiter_from_environment(monkeypatch) -> None:
    monkeypatch.setattr(openrouter_module, "load_dotenv", lambda: None)
    monkeypatch.setattr(rate_limit_module, "load_dotenv", lambda: None)
    monkeypatch.setenv("OPENROUTER_REQUESTS_PER_MINUTE", "37")
    create = AsyncMock()

    wrapper = OpenRouterClient(
        models=["fallback-a", "fallback-b"],
        client=fake_client(create),
    )

    assert wrapper._rate_limiter.requests_per_minute == 37


@pytest.mark.asyncio
async def test_completion_sends_primary_and_fallback_models_on_each_request(
    monkeypatch,
) -> None:
    monkeypatch.setattr(openrouter_module, "load_dotenv", lambda: None)
    create = AsyncMock(return_value="completion")
    wrapper = OpenRouterClient(
        models=["fallback-a", "fallback-b"],
        client=fake_client(create),
    )

    result = await wrapper.create_chat_completion(
        model="primary",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0,
    )

    assert result == "completion"
    create.assert_awaited_once()
    request = create.await_args.kwargs
    assert request["model"] == "primary"
    assert request["extra_body"]["models"] == ["fallback-a", "fallback-b"]
    assert request["messages"] == [{"role": "user", "content": "hello"}]


@pytest.mark.asyncio
async def test_client_uses_environment_rpm_limit(monkeypatch) -> None:
    monkeypatch.setattr(openrouter_module, "load_dotenv", lambda: None)
    monkeypatch.setattr(rate_limit_module, "load_dotenv", lambda: None)
    monkeypatch.setenv("OPENROUTER_REQUESTS_PER_MINUTE", "1")
    now = [0.0]
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        now[0] += delay

    create = AsyncMock(return_value="completion")
    limiter = rate_limit_module.OpenRouterRateLimiter(
        clock=lambda: now[0],
        sleep=fake_sleep,
    )
    wrapper = OpenRouterClient(
        models=["fallback-a", "fallback-b"],
        client=fake_client(create),
        sleep=fake_sleep,
        rate_limiter=limiter,
    )

    await wrapper.create_chat_completion(model="primary", messages=[])
    await wrapper.create_chat_completion(model="primary", messages=[])

    assert create.await_count == 2
    assert delays == [60.0]


@pytest.mark.asyncio
async def test_each_429_retry_acquires_an_rpm_slot(monkeypatch) -> None:
    monkeypatch.setattr(openrouter_module, "load_dotenv", lambda: None)
    monkeypatch.setattr(rate_limit_module, "load_dotenv", lambda: None)
    monkeypatch.setenv("OPENROUTER_REQUESTS_PER_MINUTE", "1")
    now = [0.0]
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        now[0] += delay

    create = AsyncMock(side_effect=[make_api_error(429), "recovered"])
    limiter = rate_limit_module.OpenRouterRateLimiter(
        clock=lambda: now[0],
        sleep=fake_sleep,
    )
    wrapper = OpenRouterClient(
        models=["fallback-a", "fallback-b"],
        client=fake_client(create),
        sleep=fake_sleep,
        rate_limiter=limiter,
    )

    assert await wrapper.create_chat_completion(model="primary", messages=[]) == "recovered"
    assert create.await_count == 2
    assert delays == [1.0, 59.0]


@pytest.mark.asyncio
async def test_429_retries_with_exponential_backoff_then_raises_typed_error(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setattr(openrouter_module, "load_dotenv", lambda: None)
    create = AsyncMock(side_effect=_raise_429)
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    wrapper = OpenRouterClient(
        models=["fallback-a", "fallback-b"],
        client=fake_client(create),
        sleep=fake_sleep,
    )

    with pytest.raises(OpenRouterRateLimitError, match="3 retries") as raised:
        await wrapper.create_chat_completion(
            model="primary", messages=[{"role": "user", "content": "hi"}]
        )

    assert raised.value.attempts == 4
    assert create.await_count == 4
    assert delays == [1.0, 2.0, 4.0]
    assert sum("HTTP 429" in record.message for record in caplog.records) == 4
    assert all(
        call.kwargs["extra_body"]["models"] == ["fallback-a", "fallback-b"]
        for call in create.await_args_list
    )


@pytest.mark.asyncio
async def test_429_retry_can_succeed_and_non_429_errors_are_not_retried(
    monkeypatch,
) -> None:
    monkeypatch.setattr(openrouter_module, "load_dotenv", lambda: None)
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    create = AsyncMock(side_effect=[make_api_error(429), "recovered"])
    wrapper = OpenRouterClient(
        models=["fallback-a", "fallback-b"],
        client=fake_client(create),
        sleep=fake_sleep,
    )
    assert await wrapper.create_chat_completion(model="primary", messages=[]) == "recovered"
    assert create.await_count == 2
    assert delays == [1.0]

    create = AsyncMock(side_effect=make_api_error(500))
    wrapper = OpenRouterClient(
        models=["fallback-a", "fallback-b"],
        client=fake_client(create),
        sleep=fake_sleep,
    )
    with pytest.raises(APIStatusError) as raised:
        await wrapper.create_chat_completion(model="primary", messages=[])
    assert raised.value.status_code == 500
    assert create.await_count == 1


async def _raise_429(**_: object) -> None:
    raise make_api_error(429)
