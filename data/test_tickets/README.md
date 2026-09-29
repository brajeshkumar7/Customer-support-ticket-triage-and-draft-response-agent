# Test Tickets

25 synthetic support tickets for the eval (TASKS.md TASK-18), with expected
outcomes recorded in `manifest.csv` and ticket text in `tickets.jsonl` so
TASK-19 can score runs against a fixed set.

Cover: order status, returns, damage, billing, general questions, PLUS
deliberate edge cases that SHOULD trigger escalation (ambiguous intent,
policy conflict, angry/high-stakes customer) - PRD.md Section 5.

`manifest.csv` columns are `ticket_id,category,expected_outcome,notes`.
Categories use `order_status`, `returns`, `damaged_item`, `billing_dispute`,
and `general_question`; outcomes are `auto_resolve` or `escalate`. An
`auto_resolve` label means the available fixture/FAQ evidence is sufficient
for a safe resolution if delivery is enabled; it does not guarantee that a
reply is sent during an evaluation. Billing disputes are labeled for
escalation because no billing transaction lookup is available.

Each non-empty line in `tickets.jsonl` is one JSON object with exactly
`ticket_id` and `ticket_text`. IDs must match the manifest exactly. These
files are evaluation data only; this task does not run tickets through the
agent or add evaluation-running code.
