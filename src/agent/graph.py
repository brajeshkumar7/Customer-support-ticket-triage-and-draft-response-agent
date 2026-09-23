"""
LangGraph state machine for the support-ticket triage agent.
Implements PRD.md Section 4: Orchestration + Supervisor loop.

This is the core graph: classify -> gather facts (tools) -> draft response
-> supervisor/critic check -> (retry with feedback | escalate | send).

See TASKS.md Phase 1-2 for build order. See DECISIONS.md before changing the
retry cap or the graph topology.
"""
