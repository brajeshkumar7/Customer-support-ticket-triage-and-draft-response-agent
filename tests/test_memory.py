from src.memory.long_term import LongTermMemory
from src.memory.short_term import ShortTermMemory


def test_short_term_memory_is_scoped_to_ticket_run() -> None:
    run_memory = ShortTermMemory("ticket-123")
    run_memory.set("category", "returns")

    assert run_memory.get("category") == "returns"
    assert ShortTermMemory("ticket-456").get("category") is None


def test_long_term_memory_adds_and_queries_fact(tmp_path) -> None:
    memory = LongTermMemory(
        persist_dir=tmp_path / "chroma",
        collection_name="test_facts",
    )
    fact_id = memory.add(
        "Customers may return unopened items within 30 days.",
        metadata={"category": "returns", "source": "test"},
    )

    matches = memory.query("return period for unopened items", n_results=1)

    assert matches
    assert matches[0]["id"] == fact_id
    assert matches[0]["text"] == "Customers may return unopened items within 30 days."
    assert matches[0]["metadata"] == {"category": "returns", "source": "test"}
