import pytest

from src.tools.base import ToolInputError, ToolNotFoundError
from src.tools.faq_search import FAQSearchTool
from src.tools.order_lookup import OrderLookupTool
from src.tools.policy_checker import PolicyCheckerTool


@pytest.mark.asyncio
async def test_order_lookup_returns_fixture_order():
    result = await OrderLookupTool().run(order_id="ORD-1001")

    assert result.tool_name == "order_lookup"
    assert result.data["status"] == "shipped"
    assert result.data["tracking_status"] == "In transit"


@pytest.mark.asyncio
async def test_order_lookup_raises_typed_error_for_missing_or_unknown_order():
    tool = OrderLookupTool()

    with pytest.raises(ToolInputError):
        await tool.run(order_id=None)
    with pytest.raises(ToolNotFoundError):
        await tool.run(order_id="ORD-9999")


@pytest.mark.asyncio
async def test_policy_checker_applies_delivery_and_claim_windows():
    tool = PolicyCheckerTool()

    eligible_damage = await tool.run(order_id="ORD-1003", reason="The lamp arrived damaged.")
    late_damage = await tool.run(order_id="ORD-1002", reason="The coffee maker is broken.")
    eligible_return = await tool.run(order_id="ORD-1002", reason="I changed my mind.")
    undelivered = await tool.run(order_id="ORD-1001", reason="I want a refund.")

    assert eligible_damage.data["eligible"] is True
    assert eligible_damage.data["policy_window_days"] == 7
    assert late_damage.data["eligible"] is False
    assert eligible_return.data["eligible"] is True
    assert eligible_return.data["policy_window_days"] == 30
    assert undelivered.data["eligible"] is False


@pytest.mark.asyncio
async def test_faq_search_returns_ranked_matches_and_empty_result():
    tool = FAQSearchTool()

    matches = await tool.run(query="How can I track my delayed package?")
    no_matches = await tool.run(query="purple penguin astronomy")

    assert matches.data["matches"]
    assert matches.data["matches"][0]["id"] in {"shipping-status", "shipping-delay"}
    assert no_matches.data["matches"] == []

    with pytest.raises(ToolInputError):
        await tool.run(query="  ")
