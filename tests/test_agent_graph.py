import json
from types import SimpleNamespace

import pytest

from src.agent.graph import build_graph
from src.memory.short_term import ShortTermMemory


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


@pytest.mark.asyncio
async def test_graph_classifies_and_drafts_response_for_sample_ticket():
    ticket_id = "ticket-123"
    ticket_text = "My package has not arrived. Can you check its status?"
    draft_response = (
        "I am sorry your package has not arrived. Could you share your order "
        "number so we can look into its status?"
    )
    client = FakeOpenRouterClient(
        ['{"category":"order status","urgency":"medium"}', draft_response]
    )
    memory = ShortTermMemory(ticket_id)
    graph = build_graph(
        short_term_memory=memory,
        client=client,
        primary_model="test-model",
    )

    result = await graph.ainvoke({"ticket_id": ticket_id, "ticket_text": ticket_text})

    assert result["ticket_id"] == ticket_id
    assert result["ticket_text"] == ticket_text
    assert result["category"] == "order status"
    assert result["urgency"] == "medium"
    assert result["draft_response"] == draft_response
    assert memory.get("ticket_text") == ticket_text
    assert memory.get("category") == "order status"
    assert memory.get("urgency") == "medium"
    assert memory.get("draft_response") == draft_response
    assert len(client.calls) == 2
    respond_input = json.loads(client.calls[1]["messages"][1]["content"])
    assert set(respond_input) == {"ticket_text", "category", "urgency"}

    graph_nodes = set(graph.get_graph().nodes)
    assert graph_nodes == {"__start__", "classify", "respond", "__end__"}
    graph_edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert ("classify", "respond") in graph_edges
    assert ("respond", "__end__") in graph_edges


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
