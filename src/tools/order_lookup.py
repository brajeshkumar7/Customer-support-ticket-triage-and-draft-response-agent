"""
Mock order-lookup tool. Implements PRD.md Section 2, tool #1.
Returns order status/details for a given order ID from mock/fixture data.
Called concurrently with other tools via asyncio - see src/agent/graph.py
and PRD.md Section 4 (async tool dispatch).
"""
