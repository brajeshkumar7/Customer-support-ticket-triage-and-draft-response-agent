import json
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.agent.graph import build_graph
from src.memory.long_term import LongTermMemory
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


@pytest.fixture
def long_term_memory():
    class MemoryStub:
        def __init__(self):
            self.facts = []

        def query(self, text: str):
            return list(self.facts[:5])

        def add(self, text: str, metadata):
            fact_id = str(uuid4())
            self.facts.append({"id": fact_id, "text": text, "metadata": metadata})
            return fact_id

    return MemoryStub()


@pytest.fixture
def chroma_long_term_memory(tmp_path) -> LongTermMemory:
    return LongTermMemory(persist_dir=tmp_path / "chroma", collection_name="graph_facts")


@pytest.mark.asyncio
async def test_graph_gathers_tool_facts_and_drafts_from_results(long_term_memory):
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
        long_term_memory=long_term_memory,
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
    assert result["recalled_facts"] == []
    assert result["memory_errors"] == []
    assert result["remembered_fact_id"]
    assert memory.get("tool_results") == result["tool_results"]
    assert memory.get("recalled_facts") == []
    assert memory.get("remembered_fact_id") == result["remembered_fact_id"]
    assert "status=shipped" in memory.get("remembered_summary")
    response_payload = json.loads(client.calls[2]["messages"][1]["content"])
    assert response_payload["tool_results"] == result["tool_results"]
    assert response_payload["historical_memory_context"] == []
    assert len(client.calls) == 3

    graph_nodes = set(graph.get_graph().nodes)
    assert graph_nodes == {
        "__start__", "recall", "classify", "gather_facts", "respond", "remember", "__end__"
    }
    graph_edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert ("__start__", "recall") in graph_edges
    assert ("recall", "classify") in graph_edges
    assert ("classify", "gather_facts") in graph_edges
    assert ("gather_facts", "respond") in graph_edges
    assert ("respond", "remember") in graph_edges
    assert ("remember", "__end__") in graph_edges


@pytest.mark.asyncio
async def test_three_tools_are_dispatched_concurrently(long_term_memory):
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
        long_term_memory=long_term_memory,
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
async def test_tool_failure_is_recorded_and_does_not_abort_graph(long_term_memory):
    client = FakeOpenRouterClient(
        [
            '{"category":"order status","urgency":"medium"}',
            '{"order_id":"ORD-9999","reason":"package is missing"}',
            "I could not verify the order. Please confirm its number.",
        ]
    )
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-tool-error"),
        long_term_memory=long_term_memory,
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
async def test_invalid_classification_fails_without_retry(classification: str, long_term_memory):
    client = FakeOpenRouterClient([classification])
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-invalid"),
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
    )

    with pytest.raises(ValueError):
        await graph.ainvoke(
            {"ticket_id": "ticket-invalid", "ticket_text": "Where is my package?"}
        )

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_graph_rejects_mismatched_ticket_id_before_calling_llm(long_term_memory):
    client = FakeOpenRouterClient([])
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-store"),
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
    )

    with pytest.raises(ValueError, match="ticket_id must match"):
        await graph.ainvoke(
            {"ticket_id": "ticket-state", "ticket_text": "Where is my package?"}
        )

    assert client.calls == []


@pytest.mark.asyncio
async def test_related_runs_recall_the_first_run_summary(chroma_long_term_memory):
    first_ticket_id = "ticket-memory-first"
    first_text = "My package ORD-1001 has not arrived. Can you check its status?"
    first_client = FakeOpenRouterClient(
        [
            '{"category":"order status","urgency":"low"}',
            '{"order_id":"ORD-1001","reason":"package has not arrived"}',
            "The current lookup says the package is in transit.",
        ]
    )
    first_graph = build_graph(
        short_term_memory=ShortTermMemory(first_ticket_id),
        long_term_memory=chroma_long_term_memory,
        client=first_client,
        primary_model="test-model",
    )
    first_result = await first_graph.ainvoke(
        {"ticket_id": first_ticket_id, "ticket_text": first_text}
    )

    second_ticket_id = "ticket-memory-second"
    second_text = "I am following up about the delayed shipment for ORD-1001."
    second_client = FakeOpenRouterClient(
        [
            '{"category":"order status","urgency":"low"}',
            '{"order_id":"ORD-1001","reason":"following up on delayed shipment"}',
            "The current lookup still says the package is in transit.",
        ]
    )
    second_graph = build_graph(
        short_term_memory=ShortTermMemory(second_ticket_id),
        long_term_memory=chroma_long_term_memory,
        client=second_client,
        primary_model="test-model",
    )
    second_result = await second_graph.ainvoke(
        {"ticket_id": second_ticket_id, "ticket_text": second_text}
    )

    first_summary = first_result["remembered_fact_id"]
    recalled_ids = {fact["id"] for fact in second_result["recalled_facts"]}
    assert first_summary in recalled_ids
    assert second_result["memory_errors"] == []
    extraction_payload = json.loads(second_client.calls[1]["messages"][1]["content"])
    response_payload = json.loads(second_client.calls[2]["messages"][1]["content"])
    assert extraction_payload["historical_memory_context"] == second_result["recalled_facts"]
    assert response_payload["historical_memory_context"] == second_result["recalled_facts"]
    assert any("status=shipped" in fact["text"] for fact in second_result["recalled_facts"])


class BrokenLongTermMemory:
    def query(self, text: str):
        raise RuntimeError("Chroma query unavailable")

    def add(self, text: str, metadata):
        raise RuntimeError("Chroma write unavailable")


@pytest.mark.asyncio
async def test_memory_failures_are_reported_without_aborting_graph():
    client = FakeOpenRouterClient(
        [
            '{"category":"general question","urgency":"low"}',
            '{"order_id":null,"reason":"a general question"}',
            "I could not verify that yet. Please share more details.",
        ]
    )
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-memory-failure"),
        long_term_memory=BrokenLongTermMemory(),
        client=client,
        primary_model="test-model",
    )

    result = await graph.ainvoke(
        {"ticket_id": "ticket-memory-failure", "ticket_text": "I have a question."}
    )

    assert result["draft_response"] == "I could not verify that yet. Please share more details."
    assert result["recalled_facts"] == []
    assert [error["operation"] for error in result["memory_errors"]] == ["recall", "remember"]
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_recalled_memory_cannot_supply_an_order_id(long_term_memory):
    long_term_memory.add(
        "Historical note: this customer previously mentioned order ORD-1001.",
        {"ticket_id": "older-ticket", "category": "order status"},
    )
    client = FakeOpenRouterClient(
        [
            '{"category":"order status","urgency":"low"}',
            '{"order_id":"ORD-1001","reason":"status request"}',
            "Please provide the order number so I can check its status.",
        ]
    )
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-no-id"),
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
    )

    result = await graph.ainvoke(
        {"ticket_id": "ticket-no-id", "ticket_text": "Where is my package?"}
    )

    assert result["recalled_facts"]
    assert result["order_id"] is None
    assert result["tool_results"]["order_lookup"]["ok"] is False
