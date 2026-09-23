import json
import threading
from types import SimpleNamespace

import pytest

from src.agent.graph import build_graph
from src.memory.short_term import ShortTermMemory
from src.tools.base import BaseTool, ToolNotFoundError


def completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class FakeOpenRouterClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict] = []

    async def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return completion(next(self.responses))


class BarrierTool(BaseTool):
    def __init__(self, tool_name: str, barrier: threading.Barrier) -> None:
        self.tool_name = tool_name
        self.barrier = barrier

    def _execute(self, **kwargs):
        self.barrier.wait(timeout=2)
        return {"started_together": True}


class FailingTool(BaseTool):
    tool_name = "order_lookup"

    def _execute(self, **kwargs):
        raise ToolNotFoundError(self.tool_name, "Mock order was not found.")


class SuccessfulFakeTool(BaseTool):
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name

    def _execute(self, **kwargs):
        return {"fixture_fact": f"available from {self.tool_name}"}


@pytest.mark.asyncio
async def test_graph_gathers_tool_facts_and_drafts_from_results():
    ticket_id = "ticket-123"
    ticket_text = "My package ORD-1001 has not arrived. Can you check its status?"
    draft_response = "Order ORD-1001 is in transit according to the mock lookup."
    client = FakeOpenRouterClient(
        [
            '{"category":"order status","urgency":"medium"}',
            '{"order_id":"ORD-1001","reason":"package has not arrived"}',
            draft_response,
        ]
    )
    memory = ShortTermMemory(ticket_id)
    graph = build_graph(
        short_term_memory=memory,
        client=client,
        primary_model="test-model",
    )

    result = await graph.ainvoke({"ticket_id": ticket_id, "ticket_text": ticket_text})

    assert result["ticket_id"] == ticket_id
    assert result["category"] == "order status"
    assert result["urgency"] == "medium"
    assert result["order_id"] == "ORD-1001"
    assert result["tool_results"]["order_lookup"]["data"]["tracking_status"] == "In transit"
    assert result["tool_results"]["policy_checker"]["ok"] is True
    assert result["tool_results"]["policy_checker"]["data"]["eligible"] is False
    assert result["tool_results"]["faq_search"]["data"]["matches"]
    assert result["draft_response"] == draft_response
    assert memory.get("tool_results") == result["tool_results"]
    response_payload = json.loads(client.calls[2]["messages"][1]["content"])
    assert response_payload["tool_results"] == result["tool_results"]
    assert len(client.calls) == 3

    graph_nodes = set(graph.get_graph().nodes)
    assert graph_nodes == {"__start__", "classify", "gather_facts", "respond", "__end__"}
    graph_edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert ("classify", "gather_facts") in graph_edges
    assert ("gather_facts", "respond") in graph_edges
    assert ("respond", "__end__") in graph_edges


@pytest.mark.asyncio
async def test_three_tools_are_dispatched_concurrently():
    barrier = threading.Barrier(3)
    client = FakeOpenRouterClient(
        [
            '{"category":"general question","urgency":"low"}',
            '{"order_id":"ORD-1001","reason":"shipping question"}',
            "Draft grounded in the facts.",
        ]
    )
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-concurrent"),
        client=client,
        primary_model="test-model",
        order_lookup_tool=BarrierTool("order_lookup", barrier),
        policy_checker_tool=BarrierTool("policy_checker", barrier),
        faq_search_tool=BarrierTool("faq_search", barrier),
    )

    result = await graph.ainvoke(
        {"ticket_id": "ticket-concurrent", "ticket_text": "Shipping question for ORD-1001"}
    )

    assert all(result["tool_results"][name]["ok"] for name in (
        "order_lookup", "policy_checker", "faq_search"
    ))


@pytest.mark.asyncio
async def test_tool_failure_is_recorded_and_does_not_abort_graph():
    client = FakeOpenRouterClient(
        [
            '{"category":"order status","urgency":"medium"}',
            '{"order_id":"ORD-9999","reason":"package is missing"}',
            "I could not verify the order. Please confirm its number.",
        ]
    )
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-tool-error"),
        client=client,
        primary_model="test-model",
        order_lookup_tool=FailingTool(),
        policy_checker_tool=SuccessfulFakeTool("policy_checker"),
        faq_search_tool=SuccessfulFakeTool("faq_search"),
    )

    result = await graph.ainvoke(
        {"ticket_id": "ticket-tool-error", "ticket_text": "Where is ORD-9999?"}
    )

    assert result["tool_results"]["order_lookup"]["ok"] is False
    assert result["tool_results"]["order_lookup"]["error"]["type"] == "ToolNotFoundError"
    assert result["tool_results"]["policy_checker"]["ok"] is True
    assert result["draft_response"] == "I could not verify the order. Please confirm its number."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "classification",
    [
        "not-json",
        '{"category":"unknown","urgency":"low"}',
        '{"category":"order status","urgency":"critical"}',
    ],
)
async def test_invalid_classification_fails_without_retry(classification: str):
    client = FakeOpenRouterClient([classification])
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-invalid"),
        client=client,
        primary_model="test-model",
    )

    with pytest.raises(ValueError):
        await graph.ainvoke(
            {"ticket_id": "ticket-invalid", "ticket_text": "Where is my package?"}
        )

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_graph_rejects_mismatched_ticket_id_before_calling_llm():
    client = FakeOpenRouterClient([])
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-store"),
        client=client,
        primary_model="test-model",
    )

    with pytest.raises(ValueError, match="ticket_id must match"):
        await graph.ainvoke(
            {"ticket_id": "ticket-state", "ticket_text": "Where is my package?"}
        )

    assert client.calls == []
