"""Provider-neutral interface for sending an approved ticket reply."""

from typing import Any, Protocol


class ReplySender(Protocol):
    """Adapter that posts one reply to an existing support ticket."""

    async def send_public_reply(self, ticket_id: str, body: str) -> dict[str, Any]:
        """Send one public reply and return provider metadata."""

