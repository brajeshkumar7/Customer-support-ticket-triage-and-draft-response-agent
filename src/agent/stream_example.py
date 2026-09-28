"""Demonstrate LangGraph node updates as an async run progresses."""

import asyncio
import json

from src.agent.graph import SAMPLE_TICKET, build_graph
from src.memory.long_term import LongTermMemory
from src.memory.short_term import ShortTermMemory


async def main() -> None:
    ticket_id = "stream-sample-ticket"
    graph = build_graph(
        short_term_memory=ShortTermMemory(ticket_id),
        long_term_memory=LongTermMemory(),
    )

    # Deliberately omit zoho_ticket_id so this demo cannot post a desk reply.
    async for node_updates in graph.astream(
        {"ticket_id": ticket_id, "ticket_text": SAMPLE_TICKET},
        stream_mode="updates",
    ):
        for node_name, partial_state in node_updates.items():
            print(f"\n[{node_name}]", flush=True)
            print(json.dumps(partial_state, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
