import asyncio
import os

import pytest

from src.agent.run_synthetic import SimulatedReplySender, main as synthetic_main
from src.agent.run_zoho import main as zoho_main, process_ticket


class FakeGraph:
    def __init__(self, sender=None, *, terminal_status="sent"):
        self.sender = sender
        self.terminal_status = terminal_status
        self.input = None
        self.send_calls = []

    async def ainvoke(self, graph_input):
        self.input = graph_input
        delivery = None
        if self.terminal_status == "sent" and self.sender:
            delivery = await self.sender.send_public_reply(
                graph_input["zoho_ticket_id"], "approved draft"
            )
            self.send_calls.append(delivery)
        return {
            "terminal_status": self.terminal_status,
            "supervisor_status": "PASS" if self.terminal_status == "sent" else "FAIL",
            "zoho_delivery_status": "sent" if self.terminal_status == "sent" else None,
            "response_sent": self.terminal_status == "sent",
            "zoho_send_result": delivery or {},
        }


def test_synthetic_command_injects_simulated_sender_and_isolated_memory(monkeypatch, capsys):
    monkeypatch.delenv("ZOHO_DESK_SEND_ENABLED", raising=False)
    created = {}

    def graph_builder(**kwargs):
        created.update(kwargs)
        graph = FakeGraph(kwargs["reply_sender"])
        created["graph"] = graph
        return graph

    def memory_factory(*, ephemeral=False):
        created["ephemeral"] = ephemeral
        return object()

    result = synthetic_main(
        ["--case-id", "order_01"],
        cases_loader=lambda: [
            {"ticket_id": "order_01", "ticket_text": "Status ORD-1001"}
        ],
        graph_builder=graph_builder,
        memory_factory=memory_factory,
    )

    assert result == 0
    assert isinstance(created["reply_sender"], SimulatedReplySender)
    assert created["ephemeral"] is True
    assert created["graph"].input["zoho_ticket_id"] == "SIMULATED-order_01"
    assert len(created["reply_sender"].calls) == 1
    assert '"delivery": "simulated"' in capsys.readouterr().out
    assert "ZOHO_DESK_SEND_ENABLED" not in os.environ


def test_zoho_command_does_not_fetch_without_send_or_confirmation(monkeypatch):
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "true")
    calls = []
    assert zoho_main(["--ticket-id", "12345"], client_factory=lambda: calls.append("client")) == 0
    assert zoho_main(
        ["--ticket-id", "12345", "--send"],
        client_factory=lambda: calls.append("client"),
        confirm_input=lambda _prompt: "NO",
    ) == 2
    assert calls == []


def test_zoho_command_requires_send_enabled_and_numeric_ticket_id(monkeypatch):
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "false")
    client_calls = []
    with pytest.raises(SystemExit):
        zoho_main(
            ["--ticket-id", "abc", "--send"],
            client_factory=lambda: client_calls.append("created"),
        )
    with pytest.raises(SystemExit):
        zoho_main(
            ["--ticket-id", "12345", "--send"],
            client_factory=lambda: client_calls.append("created"),
            confirm_input=lambda _prompt: "CONTROLLED",
        )
    assert client_calls == []


@pytest.mark.parametrize(
    ("ticket", "message"),
    [
        ({"channel": "Phone", "subject": "Help", "description": "Text"}, "Email tickets"),
        ({"channel": "Email", "subject": "Help", "description": "<p> </p>"}, "no usable description"),
    ],
)
def test_zoho_command_rejects_non_email_or_empty_ticket_before_graph(ticket, message):
    graph_calls = []

    class Client:
        async def fetch_ticket(self, _ticket_id):
            return ticket

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            process_ticket(
                "12345",
                client=Client(),
                graph_builder=lambda **kwargs: graph_calls.append(kwargs),
                memory_factory=lambda: object(),
            )
        )
    assert graph_calls == []


def test_zoho_command_fetches_ticket_and_passes_it_to_graph(monkeypatch, capsys):
    monkeypatch.setenv("ZOHO_DESK_SEND_ENABLED", "true")
    created = {}

    class Client:
        async def fetch_ticket(self, ticket_id):
            created["fetched_id"] = ticket_id
            return {
                "id": ticket_id,
                "subject": "Package <b>not</b> arrived",
                "description": "<p>My package ORD-1001 is missing.</p>",
                "channel": "Email",
            }

        async def send_public_reply(self, ticket_id, body):
            created.setdefault("sent", []).append((ticket_id, body))
            return {"http_status": 200}

    def graph_builder(**kwargs):
        created["builder_args"] = kwargs
        graph = FakeGraph(kwargs["reply_sender"])
        created["graph"] = graph
        return graph

    result = zoho_main(
        ["--ticket-id", "279251000000372001", "--send"],
        client_factory=Client,
        graph_builder=graph_builder,
        memory_factory=lambda: object(),
        confirm_input=lambda prompt: (
            "CONTROLLED" if prompt.startswith("Type CONTROLLED") else "279251000000372001"
        ),
    )

    graph_input = created["graph"].input
    assert result == 0
    assert created["fetched_id"] == "279251000000372001"
    assert graph_input["zoho_ticket_id"] == "279251000000372001"
    assert "Subject: Package not arrived" in graph_input["ticket_text"]
    assert "My package ORD-1001 is missing." in graph_input["ticket_text"]
    assert created["sent"] == [("279251000000372001", "approved draft")]
    assert '"terminal_status": "sent"' in capsys.readouterr().out


def test_zoho_processes_one_ticket_and_does_not_send_after_graph_escalation():
    sender = SimulatedReplySender()

    class Client:
        async def fetch_ticket(self, _ticket_id):
            return {"channel": "Email", "subject": "Issue", "description": "Help"}

        async def send_public_reply(self, ticket_id, body):
            return await sender.send_public_reply(ticket_id, body)

    graph = None

    def graph_builder(**kwargs):
        nonlocal graph
        graph = FakeGraph(kwargs["reply_sender"], terminal_status="escalated")
        return graph

    result = asyncio.run(
        process_ticket(
            "12345", client=Client(), graph_builder=graph_builder,
            memory_factory=lambda: object(),
        )
    )

    assert result["terminal_status"] == "escalated"
    assert graph.send_calls == []
    assert sender.calls == []
