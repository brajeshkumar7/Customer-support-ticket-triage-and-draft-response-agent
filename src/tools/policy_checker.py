"""Mock return/refund eligibility checks against the order fixture."""

import re
from typing import Any

from src.tools.base import BaseTool, ToolInputError
from src.tools.order_data import find_order
from src.knowledge.policy import load_policy
from src.agent.safety import SAFETY_PATTERN, POLICY_EXCEPTION_PATTERN

_DAMAGE_TERMS = {
    "damaged", "damage", "broken", "defective", "smoke", "smoking", "smoked",
    "spark", "sparks", "sparked", "sparking", "overheated", "overheating",
    "hazard", "hazardous",
}


class PolicyCheckerTool(BaseTool):
    tool_name = "policy_checker"

    def _execute(self, **kwargs: Any) -> dict[str, Any]:
        order_id = kwargs.get("order_id")
        reason = kwargs.get("reason")
        if not isinstance(order_id, str) or not order_id.strip():
            raise ToolInputError(self.tool_name, "An order_id is required for policy checking.")
        if not isinstance(reason, str) or not reason.strip():
            raise ToolInputError(self.tool_name, "A stated reason is required for policy checking.")

        policy = load_policy()
        reason_terms = set(re.findall(r"[a-z0-9]+", reason.lower()))
        rule_id = "damage" if reason_terms & _DAMAGE_TERMS else "returns"
        provenance = {"policy_id": policy["policy_id"], "policy_version": policy["version"],
                      "policy_sha256": policy["policy_sha256"], "rule_ids": [rule_id],
                      "requires_human_review": bool(SAFETY_PATTERN.search(reason) or POLICY_EXCEPTION_PATTERN.search(reason))}
        order = find_order(order_id, tool_name=self.tool_name)
        if policy["requires_delivered"] and order.get("status") != "delivered":
            return {
                **provenance,
                "order_id": order["order_id"],
                "eligible": False,
                "policy_window_days": None,
                "reason": "The order must be delivered before a return or refund can be evaluated.",
            }

        days_since_delivery = order.get("delivered_days_ago")
        if type(days_since_delivery) is not int or days_since_delivery < 0:
            raise ToolInputError(
                self.tool_name,
                f"Order {order_id} has invalid delivery-age data in the fixture.",
            )

        is_damage_claim = rule_id == "damage"
        policy_window_days = policy["rules"][rule_id]["window_days"]
        eligible = days_since_delivery <= policy_window_days
        label = "damaged-item claim" if is_damage_claim else "return request"
        explanation = f"The {label} is {'within' if eligible else 'outside'} the {policy_window_days}-day reporting window."
        return {
            **provenance,
            "order_id": order["order_id"],
            "eligible": eligible,
            "policy_window_days": policy_window_days,
            "days_since_delivery": days_since_delivery,
            "reason": explanation,
        }
