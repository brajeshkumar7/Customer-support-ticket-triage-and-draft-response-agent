"""Jev API contract and safe failure behavior, without network requests."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIStatusError, AsyncOpenAI

import src.openrouter_client as client_module
from src.agent.jev_triage import (
    CATEGORY_CRITERIA, URGENCY_CRITERIA, JevTriageError,
    parse_triage_decision, triage_questions,
)
from src.agent.graph import build_graph
from src.memory.short_term import ShortTermMemory
from src.openrouter_client import OpenRouterClient, OpenRouterRateLimitError


@pytest.fixture(autouse=True)
def isolate_triage_from_pdf_retrieval(monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "false")


def decision(category="order status", urgency="low"):
    return {
        "model": "typesafe/jev-1.13-20260917", "id": "decision-id", "provider": "TypeSafe",
        "answers": {
            name: {"type": "choice", "choice": selected, "confidence": 1.0,
                   "probabilities": {key: float(key == selected) for key in criteria}}
            for name, selected, criteria in (
                ("category", category, CATEGORY_CRITERIA), ("urgency", urgency, URGENCY_CRITERIA))
        },
        "usage": {"input_tokens": 500, "output_tokens": 0, "cost": 0.000021},
    }


def test_choice_contract_preserves_full_distribution_without_conflating_review_confidence():
    result = decision()
    result["answers"]["category"]["probabilities"].update({"order status": 0.7, "general question": 0.3})
    result["answers"]["category"]["confidence"] = 0.4
    category, urgency, metadata = parse_triage_decision(result, requested_model="typesafe/jev-1.13")
    assert (category, urgency) == ("order status", "low")
    assert metadata["category"]["probabilities"]["general question"] == 0.3
    assert metadata["category"]["confidence"] == 0.4
    assert metadata["model"] == result["model"]
    assert "confidence_score" not in metadata


@pytest.mark.parametrize("bad", [
    {"type": "score"},
    {"choice": "invented"},
    {"confidence": float("nan")},
    {"confidence": True},
    {"probabilities": {"order status": 1}},
    {"probabilities": {key: 0 for key in CATEGORY_CRITERIA}},
    {"probabilities": {key: -0.2 if key == "order status" else 0.24 for key in CATEGORY_CRITERIA}},
])
def test_malformed_choice_rejected(bad):
    response = decision()
    response["answers"]["category"].update(bad)
    with pytest.raises(JevTriageError):
        parse_triage_decision(response, requested_model="typesafe/jev-1.13")


@pytest.mark.asyncio
async def test_unclear_choice_escalates_without_chat_calls_or_sends(monkeypatch):
    monkeypatch.setattr("src.agent.graph.log_node_event", lambda **_kwargs: None)
    monkeypatch.setattr("src.agent.graph.log_tool_event", lambda **_kwargs: None)
    client = type("Client", (), {})()
    client.create_decision = AsyncMock(return_value=decision("unclear"))
    client.create_chat_completion = AsyncMock(side_effect=AssertionError("No chat fallback"))
    graph = build_graph(short_term_memory=ShortTermMemory("unclear-1"),
                        long_term_memory=object(), use_long_term_memory=False,
                        client=client, primary_model="draft-model", triage_model="typesafe/jev-1.13")
    result = await graph.ainvoke({"ticket_id": "unclear-1", "ticket_text": "Random unrelated text"})
    assert not result.get("workflow_error")
    assert result["category"] == "unclear"
    assert result["triage_decision"]["category"]["choice"] == "unclear"
    assert "one support category" in result["escalation_reason"]
    assert result["terminal_status"] == "escalated"
    assert result["response_sent"] is False
    client.create_chat_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_graph_preserves_jev_category_and_applies_only_priority_safety_floor(monkeypatch):
    monkeypatch.setattr("src.agent.graph.log_node_event", lambda **_kwargs: None)
    client = type("Client", (), {})()
    client.create_decision = AsyncMock(return_value=decision("damaged item", "low"))
    client.create_chat_completion = AsyncMock(side_effect=AssertionError("Only triage is streamed"))
    memory = ShortTermMemory("priority-1")
    graph = build_graph(short_term_memory=memory, long_term_memory=object(),
                        use_long_term_memory=False, client=client,
                        primary_model="draft-model", triage_model="typesafe/jev-1.13")
    updates = graph.astream({"ticket_id": "priority-1", "ticket_text": "My blender caught fire; I need to return it."},
                           stream_mode="updates")
    try:
        async for update in updates:
            if "classify" in update:
                assert update["classify"]["category"] == "damaged item"
                assert update["classify"]["urgency"] == "high"
                assert update["classify"]["category_basis"] == "jev_choice"
                assert update["classify"]["triage_decision"]["urgency"]["choice"] == "low"
                break
    finally:
        await updates.aclose()
    assert memory.get("triage_decision")["model"] == "typesafe/jev-1.13-20260917"
    client.create_chat_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_unclear_answer_is_scored_as_handoff_not_an_api_failure(monkeypatch):
    from src.eval import run_eval

    monkeypatch.setenv("OPENROUTER_PRIMARY_MODEL", "draft-model")
    monkeypatch.setattr("src.agent.graph.log_node_event", lambda **_kwargs: None)
    monkeypatch.setattr("src.agent.graph.log_tool_event", lambda **_kwargs: None)
    monkeypatch.setattr(run_eval, "costs_by_run_id", lambda ids, _path: {
        run_id: {"reported_cost": 0, "total_cost": None, "llm_calls": 0, "calls_missing_cost": 0}
        for run_id in ids})
    client = type("Client", (), {})()
    client.create_decision = AsyncMock(return_value=decision("unclear"))
    client.create_chat_completion = AsyncMock(side_effect=AssertionError("No chat fallback"))
    memory = type("Memory", (), {"query": lambda self, _text: []})()
    rows = await run_eval._run_graphs(
        [{"ticket_id": "ambiguous", "ticket_text": "Random unrelated text", "category": "general_question",
          "expected_outcome": "escalate", "notes": "Ambiguous support intent"}],
        evaluation_id="jev-offline", reply_sender=run_eval.FakeReplySender(),
        shared_client=client, evaluation_memory=memory)
    assert rows[0]["run_error"] is None
    assert rows[0]["observed_outcome"] == "escalated"
    assert rows[0]["matches_expected"] is True
    assert rows[0]["triage_decision"]["category"]["choice"] == "unclear"
    metrics = run_eval.calculate_metrics(rows)
    assert metrics["unscored_count"] == 0
    assert metrics["category_classification"]["accuracy"] == 0


@pytest.mark.asyncio
async def test_actual_sdk_transport_sends_decisions_contract_and_logs_provider_cost(monkeypatch):
    monkeypatch.setattr(client_module, "load_dotenv", lambda: None)
    events = []
    monkeypatch.setattr(client_module, "log_llm_event", lambda **kwargs: events.append(kwargs))
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=decision())

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http_client:
        sdk = AsyncOpenAI(api_key="test-only", base_url="https://openrouter.ai/api/v1",
                          http_client=http_client, max_retries=0)
        wrapper = OpenRouterClient(client=sdk, models=["chat-a", "chat-b"])
        result = await wrapper.create_decision(model="typesafe/jev-1.13", state={"ticket_text": "Where is ORD-1001?"},
                                               questions=triage_questions(), run_id="test-run", call_name="classify")
    assert len(requests) == 1
    assert str(requests[0].url) == "https://openrouter.ai/api/alpha/decisions"
    body = json.loads(requests[0].content)
    assert set(body) == {"model", "state", "questions"}
    assert body["questions"]["category"]["type"] == "choice"
    assert body["questions"]["urgency"]["type"] == "choice"
    assert result == decision()
    assert events[0]["token_cost"] == decision()["usage"]["cost"]
    assert events[0]["output"]["answers"] == decision()["answers"]
    assert events[0]["call_name"] == "classify"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,attempts", [(429, 4), (403, 1)])
async def test_decisions_retry_cap_and_shared_budget(status, attempts, monkeypatch):
    monkeypatch.setattr(client_module, "load_dotenv", lambda: None)
    monkeypatch.setattr(client_module, "log_llm_event", lambda **_kwargs: None)
    monkeypatch.setattr(client_module, "log_rate_limit_event", lambda **_kwargs: None)
    request = httpx.Request("POST", "https://openrouter.ai/api/alpha/decisions")
    error = APIStatusError("API error", response=httpx.Response(status, request=request), body=None)
    sdk = type("Sdk", (), {})()
    sdk.post = AsyncMock(side_effect=error)
    limiter = type("Limiter", (), {"acquire": AsyncMock()})()
    sleep = AsyncMock()
    wrapper = OpenRouterClient(client=sdk, models=["chat-a", "chat-b"], rate_limiter=limiter, sleep=sleep)
    with pytest.raises(OpenRouterRateLimitError if status == 429 else APIStatusError):
        await wrapper.create_decision(model="typesafe/jev-1.13", state="ticket", questions=triage_questions())
    assert sdk.post.await_count == attempts
    assert limiter.acquire.await_count == attempts
    assert [call.args[0] for call in sleep.await_args_list] == ([1.0, 2.0, 4.0] if status == 429 else [])


@pytest.mark.asyncio
async def test_chat_and_decisions_use_same_rate_limiter(monkeypatch):
    monkeypatch.setattr(client_module, "load_dotenv", lambda: None)
    monkeypatch.setattr(client_module, "log_llm_event", lambda **_kwargs: None)
    sdk = type("Sdk", (), {})()
    sdk.post = AsyncMock(return_value=decision())
    sdk.chat = type("Chat", (), {"completions": type("Completions", (), {"create": AsyncMock(return_value={})})()})()
    limiter = type("Limiter", (), {"acquire": AsyncMock()})()
    wrapper = OpenRouterClient(client=sdk, models=["chat-a", "chat-b"], rate_limiter=limiter)
    await wrapper.create_decision(model="typesafe/jev-1.13", state="ticket", questions=triage_questions())
    await wrapper.create_chat_completion(model="draft-model", messages=[])
    assert limiter.acquire.await_count == 2
