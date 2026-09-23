"""Mock return/refund eligibility checks against the order fixture."""

import re
from typing import Any

from src.tools.base import BaseTool, ToolInputError
from src.tools.order_data import find_order

_DAMAGE_TERMS = {"damaged", "damage", "broken", "defective"}


class PolicyCheckerTool(BaseTool):
    tool_name = "policy_checker"

    def _execute(self, **kwargs: Any) -> dict[str, Any]:
        order_id = kwargs.get("order_id")
        reason = kwargs.get("reason")
        if not isinstance(order_id, str) or not order_id.strip():
            raise ToolInputError(self.tool_name, "An order_id is required for policy checking.")
        if not isinstance(reason, str) or not reason.strip():
            raise ToolInputError(self.tool_name, "A stated reason is required for policy checking.")

        order = find_order(order_id, tool_name=self.tool_name)
        if order.get("status") != "delivered":
            return {
                "order_id": order["order_id"],
                "eligible": False,
                "policy_window_days": None,
                "reason": "The order must be delivered before a return or refund can be evaluated.",
            }

        days_since_delivery = order.get("delivered_days_ago")
        if not isinstance(days_since_delivery, int) or days_since_delivery < 0:
            raise ToolInputError(
                self.tool_name,
                f"Order {order_id} has invalid delivery-age data in the fixture.",
            )

        reason_terms = set(re.findall(r"[a-z0-9]+", reason.lower()))
        is_damage_claim = bool(reason_terms & _DAMAGE_TERMS)
        policy_window_days = 7 if is_damage_claim else 30
        eligible = days_since_delivery <= policy_window_days
        if is_damage_claim:
            explanation = (
                "The damaged-item claim is within the 7-day reporting window."
                if eligible
                else "The damaged-item claim is outside the 7-day reporting window."
            )
        else:
            explanation = (
                "The return request is within the 30-day window."
                if eligible
                else "The return request is outside the 30-day window."
            )
        return {
            "order_id": order["order_id"],
            "eligible": eligible,
            "policy_window_days": policy_window_days,
            "days_since_delivery": days_since_delivery,
            "reason": explanation,
        }
