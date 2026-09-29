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

TASK-19 uses a fake reply sender for all 25 synthetic cases. It does not
require Zoho ticket IDs, create tickets, or send public replies. A simulated
sent outcome measures the graph's approved-reply path; it does not establish
that a real provider delivered the reply.

Run the benchmark from the repository root with
`.venv\\Scripts\\python.exe -m src.eval.run_eval`. It uses the configured
OpenRouter models, writes a report under `data/eval_reports/`, and updates
measured metrics in `PROGRESS.md` after all cases run. Recompute a saved report
without model or network calls with
`.venv\\Scripts\\python.exe -m src.eval.run_eval --report PATH`.

Test live Zoho delivery separately with one existing ticket and contact you
control. Set `ZOHO_DESK_SEND_ENABLED=true`, then run
`.venv\\Scripts\\python.exe -m src.eval.zoho_smoke --ticket-id ID --send`.
The command asks you to confirm the ticket/contact are controlled, then type
the ticket ID before sending one fixed public smoke-test reply. It does not
create tickets or retry an ambiguous send.
