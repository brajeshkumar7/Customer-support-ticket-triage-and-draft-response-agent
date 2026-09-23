"""
Critic/supervisor node: evaluates worker output against a checklist.
Implements PRD.md Section 4: Supervisor loop, and Section 5's
retries-to-success / failure-rate metrics.

On failure: inject feedback into next attempt, cap at N retries (log N and
why in DECISIONS.md), then fail loudly -> escalate, never fail silently.
"""
