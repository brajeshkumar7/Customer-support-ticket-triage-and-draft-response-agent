"""Shared read-only access to the mock order fixture."""

import json
from pathlib import Path
from typing import Any

from src.tools.base import ToolExecutionError, ToolNotFoundError

ORDER_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "data" / "mock_orders.json"


def load_orders() -> dict[str, dict[str, Any]]:
    try:
        with ORDER_FIXTURE_PATH.open(encoding="utf-8") as fixture:
            records = json.load(fixture)
    except (OSError, json.JSONDecodeError) as error:
        raise ToolExecutionError("order_data", "Could not load mock order data.") from error

    if not isinstance(records, list):
        raise ToolExecutionError("order_data", "Mock order data must be a JSON list.")
    orders: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("order_id"), str):
            raise ToolExecutionError("order_data", "Mock order record has an invalid shape.")
        order_id = record["order_id"].upper()
        if order_id in orders:
            raise ToolExecutionError("order_data", f"Duplicate mock order ID: {order_id}.")
        orders[order_id] = record
    return orders


def find_order(order_id: str, *, tool_name: str = "order_lookup") -> dict[str, Any]:
    normalized_id = order_id.strip().upper()
    order = load_orders().get(normalized_id)
    if order is None:
        raise ToolNotFoundError(tool_name, f"Order {normalized_id} was not found.")
    return order
