"""In-memory working state scoped to one support ticket run."""

from typing import Any


class ShortTermMemory:
    """Store run-local values under a ticket ID namespace.

    Create one instance for each agent run. Values are held only in this
    process and are discarded when the instance is released.
    """

    def __init__(self, ticket_id: str) -> None:
        if not ticket_id:
            raise ValueError("ticket_id must be a non-empty string")
        self.ticket_id = ticket_id
        self._values: dict[tuple[str, str], Any] = {}

    def set(self, key: str, value: Any) -> None:
        """Set a value for this ticket run."""
        self._values[(self.ticket_id, key)] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Return a value for this ticket run, or ``default`` if absent."""
        return self._values.get((self.ticket_id, key), default)

    def clear(self) -> None:
        """Discard all state for this ticket run."""
        self._values.clear()
