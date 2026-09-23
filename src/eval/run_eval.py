"""
Eval harness. Implements PRD.md Section 5 (Success Metrics) and
TASKS.md Phase 5.

Runs the agent against data/test_tickets/, computes:
- auto-resolution rate
- escalation accuracy (correctly escalated vs. should-have-escalated)
- mean retries-to-success, failure rate after cap
- p95 latency (sequential vs. async - see TASK-20)
- cost per successful run

Writes results into PROGRESS.md's metrics tracker table (manually, or extend
this script to append automatically).
"""
