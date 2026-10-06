"""Provider-neutral interface for sending an approved ticket reply."""

from abc import ABC, abstractmethod
from typing import Any, Protocol


class ReplySender(Protocol):
    """Adapter that posts one reply to an existing support ticket."""

    async def send_public_reply(self, ticket_id: str, body: str) -> dict[str, Any]:
        """Send one public reply and return provider metadata."""


class SimulationOnlyReplySender(ABC):
    """Explicit marker for senders that cannot deliver a public message."""

    @abstractmethod
    async def send_public_reply(self, ticket_id: str, body: str) -> dict[str, Any]:
        """Record a simulated reply without contacting a delivery provider."""

