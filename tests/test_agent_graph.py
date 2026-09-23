import json
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.agent.graph import build_graph
from src.agent.supervisor import SUPERVISOR_CHECKLIST, SUPERVISOR_RETRY_CAP
from src.memory.long_term import LongTermMemory
from src.memory.short_term import ShortTermMemory
from src.tools.base import BaseTool, ToolNotFoundError
from zoho_desk_client import ZohoDeskDeliveryError

SUPERVISOR_PASS = json.dumps(
    {
        "checks": [
            {"id": check["id"], "passed": True, "reason": "The draft meets this check."}
            for check in SUPERVISOR_CHECKLIST
        ]
    }
)


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


class FakeZohoDeskClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, str]] = []

    async def send_public_reply(self, ticket_id: str, body: str):
        self.calls.append({"ticket_id": ticket_id, "body": body})
        if self.error:
            raise self.error
        return {"zoho_ticket_id": ticket_id, "http_status": 200}


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


class CountingFakeTool(SuccessfulFakeTool):
    def __init__(self, tool_name: str) -> None:
        super().__init__(tool_name)
        self.call_count = 0

    def _execute(self, **kwargs):
        self.call_count += 1
        return super()._execute(**kwargs)


@pytest.fixture(autouse=True)
def disable_zoho_desk_sending_by_default(monkeypatch):
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "false")
    for name in (
        "ZOHO_DESK_API_DOMAIN",
        "ZOHO_DESK_ORG_ID",
        "ZOHO_DESK_FROM_EMAIL",
        "ZOHO_ACCOUNTS_DOMAIN",
        "ZOHO_CLIENT_ID",
        "ZOHO_CLIENT_SECRET",
        "ZOHO_REFRESH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def enabled_fake_zoho_desk(monkeypatch):
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "true")
    return FakeZohoDeskClient()


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
async def test_graph_gathers_facts_reviews_and_sends_reply(
    long_term_memory, enabled_fake_zoho_desk, monkeypatch
):
    zoho_desk_events = []
    monkeypatch.setattr(
        "src.agent.graph.log_tool_event",
        lambda **event: zoho_desk_events.append(event),
    )
    ticket_id = "ticket-123"
    ticket_text = "My package ORD-1001 has not arrived. Can you check its status?"
    draft_response = "Order ORD-1001 is in transit according to the mock lookup."
    client = FakeOpenRouterClient(
        [
            '{"category":"order status","urgency":"medium"}',
            '{"order_id":"ORD-1001","reason":"package has not arrived"}',
            draft_response,
            SUPERVISOR_PASS,
        ]
    )
    memory = ShortTermMemory(ticket_id)
    graph = build_graph(
        short_term_memory=memory,
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
        zoho_desk_client=enabled_fake_zoho_desk,
    )

    result = await graph.ainvoke(
        {
            "ticket_id": ticket_id,
            "zoho_ticket_id": "12345",
            "ticket_text": ticket_text,
        }
    )

    assert result["ticket_id"] == ticket_id
    assert result["category"] == "order status"
    assert result["urgency"] == "medium"
    assert result["order_id"] == "ORD-1001"
    assert result["tool_results"]["order_lookup"]["data"]["tracking_status"] == "In transit"
    assert result["tool_results"]["policy_checker"]["ok"] is True
    assert result["tool_results"]["policy_checker"]["data"]["eligible"] is False
    assert result["tool_results"]["faq_search"]["data"]["matches"]
    assert result["draft_response"] == draft_response
    assert result["supervisor_status"] == "PASS"
    assert result["supervisor_reason"]["failed_checks"] == []
    assert result["retry_count"] == 0
    assert result["escalated"] is False
    assert result["confidence_score"] == 1.0
    assert result["response_sent"] is True
    assert result["terminal_status"] == "sent"
    assert result["zoho_delivery_status"] == "sent"
    assert enabled_fake_zoho_desk.calls == [
        {"ticket_id": "12345", "body": draft_response}
    ]
    assert len(zoho_desk_events) == 1
    assert zoho_desk_events[0]["tool_name"] == "zoho_desk_send_public_reply"
    assert zoho_desk_events[0]["output"]["delivery_status"] == "sent"
    assert zoho_desk_events[0]["latency_ms"] >= 0
    logged_event = json.dumps(zoho_desk_events[0])
    assert "test-token" not in logged_event
    assert ticket_text not in logged_event
    assert draft_response not in logged_event
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
    assert "factual_claims_grounded" in client.calls[3]["messages"][0]["content"]
    assert memory.get("supervisor_status") == "PASS"
    assert len(client.calls) == 4

    graph_nodes = set(graph.get_graph().nodes)
    assert graph_nodes == {
        "__start__", "recall", "classify", "gather_facts", "respond", "supervisor",
        "prepare_retry", "send_response", "escalate", "remember", "__end__"
    }
    graph_edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert ("__start__", "recall") in graph_edges
    assert ("recall", "classify") in graph_edges
    assert ("classify", "gather_facts") in graph_edges
    assert ("gather_facts", "respond") in graph_edges
    assert ("respond", "supervisor") in graph_edges
    assert ("supervisor", "prepare_retry") in graph_edges
    assert ("supervisor", "escalate") in graph_edges
    assert ("supervisor", "send_response") in graph_edges
    assert ("prepare_retry", "respond") in graph_edges
    assert ("send_response", "remember") in graph_edges
    assert ("send_response", "escalate") in graph_edges
    assert ("escalate", "__end__") in graph_edges
    assert ("remember", "__end__") in graph_edges


@pytest.mark.asyncio
async def test_three_tools_are_dispatched_concurrently(long_term_memory, enabled_fake_zoho_desk):
    barrier = threading.Barrier(3)
    client = FakeOpenRouterClient(
        [
            '{"category":"general question","urgency":"low"}',
            '{"order_id":"ORD-1001","reason":"shipping question"}',
            "Draft grounded in the facts.",
            SUPERVISOR_PASS,
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
        zoho_desk_client=enabled_fake_zoho_desk,
    )

    result = await graph.ainvoke(
        {
            "ticket_id": "ticket-concurrent",
            "zoho_ticket_id": "12345",
            "ticket_text": "Shipping question for ORD-1001",
        }
    )

    assert all(result["tool_results"][name]["ok"] for name in (
        "order_lookup", "policy_checker", "faq_search"
    ))


@pytest.mark.asyncio
async def test_tool_failure_is_recorded_and_does_not_abort_graph(
    long_term_memory, enabled_fake_zoho_desk
):
    client = FakeOpenRouterClient(
        [
            '{"category":"order status","urgency":"medium"}',
            '{"order_id":"ORD-9999","reason":"package is missing"}',
            "I could not verify the order. Please confirm its number.",
            SUPERVISOR_PASS,
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
        zoho_desk_client=enabled_fake_zoho_desk,
    )

    result = await graph.ainvoke(
        {
            "ticket_id": "ticket-tool-error",
            "zoho_ticket_id": "12345",
            "ticket_text": "Where is ORD-9999?",
        }
    )

    assert result["tool_results"]["order_lookup"]["ok"] is False
    assert result["tool_results"]["order_lookup"]["error"]["type"] == "ToolNotFoundError"
    assert result["tool_results"]["policy_checker"]["ok"] is True
    assert result["draft_response"] == "I could not verify the order. Please confirm its number."


@pytest.mark.asyncio
async def test_supervisor_feedback_repairs_unsupported_claim(
    long_term_memory, enabled_fake_zoho_desk
):
    ticket_id = "ticket-unsupported-claim"
    unsupported_draft = (
        "Your refund has already been issued and will arrive in three days."
    )
    supervisor_fail = json.dumps(
        {
            "checks": [
                {
                    "id": "factual_claims_grounded",
                    "passed": False,
                    "reason": (
                        "The claim that the refund has already been issued and will "
                        "arrive in three days is unsupported; no successful tool "
                        "returned either fact."
                    ),
                },
                {
                    "id": "no_unsupported_claims",
                    "passed": False,
                    "reason": "No tool returned a refund issuance or delivery date.",
                },
                {
                    "id": "urgency_appropriate_tone",
                    "passed": True,
                    "reason": "The wording is calm and appropriate for medium urgency.",
                },
            ]
        }
    )
    client = FakeOpenRouterClient(
        [
            '{"category":"return request","urgency":"medium"}',
            '{"order_id":"ORD-1002","reason":"requesting a refund"}',
            unsupported_draft,
            supervisor_fail,
            (
                "I cannot confirm a refund has been issued. The order has not been "
                "delivered, so the policy check says refund eligibility cannot yet "
                "be evaluated."
            ),
            SUPERVISOR_PASS,
        ]
    )
    memory = ShortTermMemory(ticket_id)
    tools = {
        name: CountingFakeTool(name)
        for name in ("order_lookup", "policy_checker", "faq_search")
    }
    graph = build_graph(
        short_term_memory=memory,
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
        order_lookup_tool=tools["order_lookup"],
        policy_checker_tool=tools["policy_checker"],
        faq_search_tool=tools["faq_search"],
        zoho_desk_client=enabled_fake_zoho_desk,
    )

    result = await graph.ainvoke(
        {
            "ticket_id": ticket_id,
            "zoho_ticket_id": "12345",
            "ticket_text": "I want a refund for order ORD-1002.",
        }
    )

    assert result["draft_response"].startswith("I cannot confirm a refund")
    assert result["supervisor_status"] == "PASS"
    assert result["retry_count"] == 1
    assert result["escalated"] is False
    assert set(result["supervisor_feedback"]["failed_checks"]) == {
        "factual_claims_grounded",
        "no_unsupported_claims",
    }
    failed_reasons = " ".join(
        check["reason"]
        for check in result["supervisor_feedback"]["checks"]
        if not check["passed"]
    ).lower()
    assert "unsupported" in failed_reasons
    assert "refund" in failed_reasons
    assert result["remembered_fact_id"]
    assert result["failed_attempts"][0]["draft_response"] == unsupported_draft
    assert result["failed_attempts"][0]["supervisor_feedback"] == result["supervisor_feedback"]
    assert memory.get("supervisor_status") == "PASS"
    assert len(client.calls) == 6
    retry_prompt = json.loads(client.calls[4]["messages"][1]["content"])
    assert retry_prompt["supervisor_feedback"] == result["supervisor_feedback"]
    assert all(tool.call_count == 1 for tool in tools.values())


@pytest.mark.asyncio
async def test_supervisor_retry_cap_escalates_without_an_extra_draft(long_term_memory):
    ticket_id = "ticket-retry-cap"
    failing_review = json.dumps(
        {
            "checks": [
                {
                    "id": check["id"],
                    "passed": check["id"] == "urgency_appropriate_tone",
                    "reason": (
                        "Unsupported refund claim remains in the draft."
                        if check["id"] != "urgency_appropriate_tone"
                        else "Tone is appropriate."
                    ),
                }
                for check in SUPERVISOR_CHECKLIST
            ]
        }
    )
    client = FakeOpenRouterClient(
        [
            '{"category":"return request","urgency":"medium"}',
            '{"order_id":"ORD-1002","reason":"requesting a refund"}',
            *[
                response
                for _ in range(SUPERVISOR_RETRY_CAP + 1)
                for response in ("Your refund was issued.", failing_review)
            ],
        ]
    )
    tools = {
        name: CountingFakeTool(name)
        for name in ("order_lookup", "policy_checker", "faq_search")
    }
    graph = build_graph(
        short_term_memory=ShortTermMemory(ticket_id),
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
        order_lookup_tool=tools["order_lookup"],
        policy_checker_tool=tools["policy_checker"],
        faq_search_tool=tools["faq_search"],
    )

    result = await graph.ainvoke(
        {"ticket_id": ticket_id, "ticket_text": "I need a refund for ORD-1002."}
    )

    assert result["retry_count"] == SUPERVISOR_RETRY_CAP
    assert result["escalated"] is True
    assert result["terminal_status"] == "escalated"
    assert "failed factual_claims_grounded" in result["escalation_reason"]
    assert result["escalation_payload"]["ticket"]["ticket_text"] == (
        "I need a refund for ORD-1002."
    )
    assert result["escalation_payload"]["tool_results"] == result["tool_results"]
    assert len(result["escalation_payload"]["failed_attempts"]) == SUPERVISOR_RETRY_CAP + 1
    assert all(
        attempt["supervisor_feedback"]["failed_checks"]
        for attempt in result["escalation_payload"]["failed_attempts"]
    )
    assert result["escalation_payload"]["current_draft"] == "Your refund was issued."
    assert "remembered_fact_id" not in result
    assert len(client.calls) == 2 + 2 * (SUPERVISOR_RETRY_CAP + 1)
    assert all(tool.call_count == 1 for tool in tools.values())


@pytest.mark.asyncio
async def test_zoho_desk_sending_disabled_escalates_with_reviewed_draft(
    long_term_memory,
):
    client = FakeOpenRouterClient(
        [
            '{"category":"general question","urgency":"low"}',
            '{"order_id":null,"reason":"question"}',
            "Please share more details so I can help.",
            SUPERVISOR_PASS,
        ]
    )
    sender = FakeZohoDeskClient()
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-disabled"),
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
        zoho_desk_client=sender,
    )

    result = await graph.ainvoke(
        {"ticket_id": "ticket-disabled", "ticket_text": "I have a question."}
    )

    assert sender.calls == []
    assert result["supervisor_status"] == "PASS"
    assert result["confidence_score"] == 1.0
    assert result["response_sent"] is False
    assert result["terminal_status"] == "escalated"
    assert result["escalation_payload"]["current_draft"] == result["draft_response"]
    assert "disabled" in result["escalation_reason"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status", "reason_fragment"),
    [
        (
            ZohoDeskDeliveryError(
                "Zoho Desk returned HTTP 403.", delivery_status="failed", http_status=403
            ),
            "failed",
            "rejected",
        ),
        (
            ZohoDeskDeliveryError(
                "Zoho Desk did not confirm whether the reply was sent.",
                delivery_status="unknown",
            ),
            "unknown",
            "verify the ticket",
        ),
    ],
)
async def test_zoho_desk_send_failures_escalate_without_replaying(
    monkeypatch, long_term_memory, error, expected_status, reason_fragment
):
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "true")
    client = FakeOpenRouterClient(
        [
            '{"category":"general question","urgency":"low"}',
            '{"order_id":null,"reason":"question"}',
            "Please share more details so I can help.",
            SUPERVISOR_PASS,
        ]
    )
    sender = FakeZohoDeskClient(error=error)
    ticket_id = "ticket-send-error"
    graph = build_graph(
        short_term_memory=ShortTermMemory(ticket_id),
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
        zoho_desk_client=sender,
    )

    result = await graph.ainvoke(
        {
            "ticket_id": ticket_id,
            "zoho_ticket_id": "12345",
            "ticket_text": "I have a question.",
        }
    )

    assert len(sender.calls) == 1
    assert result["zoho_delivery_status"] == expected_status
    assert result["terminal_status"] == "escalated"
    assert result["response_sent"] is False
    assert reason_fragment in result["escalation_reason"].lower()
    assert result["escalation_payload"]["ticket"]["ticket_text"] == "I have a question."
    assert result["escalation_payload"]["tool_results"] == result["tool_results"]


@pytest.mark.asyncio
async def test_missing_zoho_ticket_id_escalates_without_sending(
    monkeypatch, long_term_memory
):
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "true")
    client = FakeOpenRouterClient(
        [
            '{"category":"general question","urgency":"low"}',
            '{"order_id":null,"reason":"question"}',
            "Please share more details so I can help.",
            SUPERVISOR_PASS,
        ]
    )
    sender = FakeZohoDeskClient()
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-no-zoho-id"),
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
        zoho_desk_client=sender,
    )

    result = await graph.ainvoke(
        {"ticket_id": "ticket-no-zoho-id", "ticket_text": "I have a question."}
    )

    assert sender.calls == []
    assert result["zoho_delivery_status"] == "missing_ticket_id"
    assert result["terminal_status"] == "escalated"
    assert result["escalation_payload"]["current_draft"] == result["draft_response"]


@pytest.mark.asyncio
async def test_missing_zoho_desk_configuration_escalates_without_sending(
    monkeypatch, long_term_memory
):
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "true")
    for name in (
        "ZOHO_DESK_API_DOMAIN",
        "ZOHO_DESK_ORG_ID",
        "ZOHO_DESK_FROM_EMAIL",
        "ZOHO_CLIENT_ID",
        "ZOHO_CLIENT_SECRET",
        "ZOHO_REFRESH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    client = FakeOpenRouterClient(
        [
            '{"category":"general question","urgency":"low"}',
            '{"order_id":null,"reason":"question"}',
            "Please share more details so I can help.",
            SUPERVISOR_PASS,
        ]
    )
    sender = FakeZohoDeskClient()
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-no-zoho-credentials"),
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
        zoho_desk_client=sender,
    )

    result = await graph.ainvoke(
        {
            "ticket_id": "ticket-no-zoho-credentials",
            "zoho_ticket_id": "12345",
            "ticket_text": "I have a question.",
        }
    )

    assert sender.calls == []
    assert result["zoho_delivery_status"] == "not_configured"
    assert result["terminal_status"] == "escalated"
    assert "missing zoho desk configuration" in result["escalation_reason"].lower()


@pytest.mark.asyncio
async def test_supervisor_node_failure_escalates_with_current_draft(long_term_memory):
    class SupervisorFailureClient(FakeOpenRouterClient):
        async def create_chat_completion(self, **kwargs):
            if len(self.calls) == 3:
                self.calls.append(kwargs)
                raise RuntimeError("simulated reviewer failure")
            return await super().create_chat_completion(**kwargs)

    draft = "Please share more details so I can help."
    client = SupervisorFailureClient(
        [
            '{"category":"general question","urgency":"low"}',
            '{"order_id":null,"reason":"question"}',
            draft,
        ]
    )
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-supervisor-error"),
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
    )

    result = await graph.ainvoke(
        {
            "ticket_id": "ticket-supervisor-error",
            "ticket_text": "I have a question.",
        }
    )

    assert result["terminal_status"] == "escalated"
    assert result["response_sent"] is False
    assert result["workflow_error"]["node"] == "supervisor"
    assert result["escalation_payload"]["current_draft"] == draft
    assert len(result["escalation_payload"]["failed_attempts"]) == 1
    failure = result["escalation_payload"]["failed_attempts"][0]
    assert failure["draft_response"] == draft
    assert failure["supervisor_feedback"]["failed_checks"] == ["supervisor_review"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "classification",
    [
        "not-json",
        '{"category":"unknown","urgency":"low"}',
        '{"category":"order status","urgency":"critical"}',
    ],
)
async def test_invalid_classification_escalates_explicitly(classification: str, long_term_memory):
    client = FakeOpenRouterClient([classification])
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-invalid"),
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
    )

    result = await graph.ainvoke(
        {"ticket_id": "ticket-invalid", "ticket_text": "Where is my package?"}
    )

    assert len(client.calls) == 1
    assert result["terminal_status"] == "escalated"
    assert result["escalation_payload"]["ticket"]["ticket_text"] == "Where is my package?"
    assert result["workflow_error"]["node"] == "classify"


@pytest.mark.asyncio
async def test_graph_escalates_mismatched_ticket_id_before_calling_llm(long_term_memory):
    client = FakeOpenRouterClient([])
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-store"),
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
    )

    result = await graph.ainvoke(
        {"ticket_id": "ticket-state", "ticket_text": "Where is my package?"}
    )

    assert client.calls == []
    assert result["terminal_status"] == "escalated"
    assert result["workflow_error"]["node"] == "recall"


@pytest.mark.asyncio
async def test_related_runs_recall_the_first_run_summary(
    chroma_long_term_memory, enabled_fake_zoho_desk
):
    first_ticket_id = "ticket-memory-first"
    first_text = "My package ORD-1001 has not arrived. Can you check its status?"
    first_client = FakeOpenRouterClient(
        [
            '{"category":"order status","urgency":"low"}',
            '{"order_id":"ORD-1001","reason":"package has not arrived"}',
            "The current lookup says the package is in transit.",
            SUPERVISOR_PASS,
        ]
    )
    first_graph = build_graph(
        short_term_memory=ShortTermMemory(first_ticket_id),
        long_term_memory=chroma_long_term_memory,
        client=first_client,
        primary_model="test-model",
        zoho_desk_client=enabled_fake_zoho_desk,
    )
    first_result = await first_graph.ainvoke(
        {
            "ticket_id": first_ticket_id,
            "zoho_ticket_id": "12345",
            "ticket_text": first_text,
        }
    )

    second_ticket_id = "ticket-memory-second"
    second_text = "I am following up about the delayed shipment for ORD-1001."
    second_client = FakeOpenRouterClient(
        [
            '{"category":"order status","urgency":"low"}',
            '{"order_id":"ORD-1001","reason":"following up on delayed shipment"}',
            "The current lookup still says the package is in transit.",
            SUPERVISOR_PASS,
        ]
    )
    second_graph = build_graph(
        short_term_memory=ShortTermMemory(second_ticket_id),
        long_term_memory=chroma_long_term_memory,
        client=second_client,
        primary_model="test-model",
        zoho_desk_client=enabled_fake_zoho_desk,
    )
    second_result = await second_graph.ainvoke(
        {
            "ticket_id": second_ticket_id,
            "zoho_ticket_id": "12346",
            "ticket_text": second_text,
        }
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
async def test_memory_failures_are_reported_without_aborting_graph(enabled_fake_zoho_desk):
    client = FakeOpenRouterClient(
        [
            '{"category":"general question","urgency":"low"}',
            '{"order_id":null,"reason":"a general question"}',
            "I could not verify that yet. Please share more details.",
            SUPERVISOR_PASS,
        ]
    )
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-memory-failure"),
        long_term_memory=BrokenLongTermMemory(),
        client=client,
        primary_model="test-model",
        zoho_desk_client=enabled_fake_zoho_desk,
    )

    result = await graph.ainvoke(
        {
            "ticket_id": "ticket-memory-failure",
            "zoho_ticket_id": "12345",
            "ticket_text": "I have a question.",
        }
    )

    assert result["draft_response"] == "I could not verify that yet. Please share more details."
    assert result["recalled_facts"] == []
    assert [error["operation"] for error in result["memory_errors"]] == ["recall", "remember"]
    assert len(client.calls) == 4


@pytest.mark.asyncio
async def test_recalled_memory_cannot_supply_an_order_id(long_term_memory, enabled_fake_zoho_desk):
    long_term_memory.add(
        "Historical note: this customer previously mentioned order ORD-1001.",
        {"ticket_id": "older-ticket", "category": "order status"},
    )
    client = FakeOpenRouterClient(
        [
            '{"category":"order status","urgency":"low"}',
            '{"order_id":"ORD-1001","reason":"status request"}',
            "Please provide the order number so I can check its status.",
            SUPERVISOR_PASS,
        ]
    )
    graph = build_graph(
        short_term_memory=ShortTermMemory("ticket-no-id"),
        long_term_memory=long_term_memory,
        client=client,
        primary_model="test-model",
        zoho_desk_client=enabled_fake_zoho_desk,
    )

    result = await graph.ainvoke(
        {
            "ticket_id": "ticket-no-id",
            "zoho_ticket_id": "12345",
            "ticket_text": "Where is my package?",
        }
    )

    assert result["recalled_facts"]
    assert result["order_id"] is None
    assert result["tool_results"]["order_lookup"]["ok"] is False
