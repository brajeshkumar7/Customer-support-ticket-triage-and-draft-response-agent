"""Mock order lookup backed by the small local order fixture."""

import re
from typing import Any

from src.tools.base import BaseTool, ToolInputError
from src.tools.order_data import find_order

_ORDER_ID_PATTERN = re.compile(r"^ORD-\d{4}$", re.IGNORECASE)


class OrderLookupTool(BaseTool):
    tool_name = "order_lookup"

    def _execute(self, **kwargs: Any) -> dict[str, Any]:
        order_id = kwargs.get("order_id")
        if not isinstance(order_id, str) or not _ORDER_ID_PATTERN.fullmatch(order_id.strip()):
            raise ToolInputError(self.tool_name, "order_id must use the format ORD-1234.")
        return dict(find_order(order_id))
