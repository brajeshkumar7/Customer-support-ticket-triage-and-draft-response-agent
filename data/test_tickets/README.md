# Test Tickets

Current graph runs use PDF hybrid RAG by default. First run
`python -m src.knowledge.ingest`; see [the knowledgebase guide](../../knowledgebase/README.md). Full evaluation
reports retain the RAG pipeline/corpus hash, evidence review and citations.
Historical pre-RAG scores do not measure this pipeline. Ticket-history memory
remains a fresh shared ephemeral collection; the PDF index is separate.

50 synthetic support tickets for the eval (TASKS.md TASK-18 and TASK-27), with expected
historical fixture-backed outcomes in `manifest.csv` and ticket text in `tickets.jsonl` so
the evaluator can score runs against a fixed set. The original 25 are unchanged;
the additional 25 include five new cases in each category. Their labels are
author-drafted and do not count as independently human-reviewed cases.

Cover: order status, returns, damage, billing, general questions, PLUS
deliberate edge cases that SHOULD trigger escalation (ambiguous intent,
policy conflict, angry/high-stakes customer) - PRD.md Section 5.

`manifest.csv` columns are `ticket_id,category,expected_outcome,notes`.
Categories use `order_status`, `returns`, `damaged_item`, `billing_dispute`,
and `general_question`; outcomes are `auto_resolve` or `escalate`. An
`auto_resolve` label in that historical manifest means the fixture/FAQ evidence was considered sufficient
for a safe resolution if delivery is enabled; it does not guarantee that a
reply is sent during an evaluation. Billing disputes are labeled for
escalation because no billing transaction lookup is available.

Each non-empty line in `tickets.jsonl` is one JSON object with exactly
`ticket_id` and `ticket_text`. IDs must match the manifest exactly. These
files are evaluation inputs; `src.eval.run_eval` runs them through the graph.

The current evaluator uses `manifest_informational.csv` for all 50 synthetic
cases. It keeps the original `manifest.csv` unchanged for historical report
comparison. Under the new policy only seven general FAQ cases are labeled
`auto_resolve`; customer-specific fixture cases require human review.
The evaluator uses a fake reply sender and does not
require Zoho ticket IDs, create tickets, or send public replies. A simulated
sent outcome measures the graph's approved-reply path; it does not establish
that a real provider delivered the reply.

`holdout_v1.jsonl` contains 200 author-labeled, templated synthetic cases,
40 per category, with required evidence, acceptable answer, and critical
failure tags. Its byte-level SHA-256 is pinned in `src/eval/run_holdout.py`;
the runner refuses changed content. Run it with
`.\.venv\Scripts\python.exe -m src.eval.run_holdout`. It uses configured
OpenRouter models for every RAG-enabled case and a fake sender only. A saved report can
be recomputed offline with `--report PATH`. The holdout has not been reviewed
independently and is separate from the future real-ticket release set.

Run the benchmark from the repository root with
`.\.venv\Scripts\python.exe -m src.eval.run_eval`. It uses the configured
OpenRouter models, writes a report under `data/eval_reports/`, and updates
accepted metrics in `PROGRESS.md` only after all 50 cases are scored.
Operational failures remain in saved reports and do not overwrite the tracker. Recompute a saved report
without model or network calls with
`.\.venv\Scripts\python.exe -m src.eval.run_eval --report PATH`.

Test live Zoho delivery separately with one existing ticket and contact you
control. Set `ZOHO_DESK_SEND_ENABLED=true`, then run
`.\.venv\Scripts\python.exe -m src.eval.zoho_smoke --ticket-id ID --send`.
The command asks you to confirm the ticket/contact are controlled, then type
the ticket ID before sending one fixed public smoke-test reply. It does not
create tickets or retry an ambiguous send.

## TASK-25 safety regressions

`safety_regressions.jsonl` has 31 historical fixture-backed safety cases. Its
runner still measures the old gate for comparison; the current graph uses the
shared informational-only policy, tested in `tests/test_informational_policy.py`.
Each
case includes expected evidence, acceptable draft and terminal behavior, and
the deterministic gate result. Run with
`.\.venv\Scripts\python.exe -m src.eval.run_safety_regressions`. It does not
call an LLM, Zoho, or the fake sender, so it measures the deterministic rules
only and does not measure generated-response quality. Four carrier-scan
cases cover the `general_03` misclassification, a paraphrase, a request for
specific shipment status, and an unavailable FAQ. TASK-28 adds the four
previously missed escalations, paraphrases, and neighboring answerable
cases. They are author-labeled regressions, not part of the independently
reviewed release set.
# Controlled deployment release set

The synthetic graph benchmark cases are local evaluation data. They
do not authorize customer-facing delivery. A separate
`release_reviewed.jsonl` must contain at least 200 genuinely human-reviewed
cases, at least 20 per category, before running
`python -m src.eval.run_release_eval --cases ... --out ...`. Each line needs
`id`, `category`, `ticket_text`, `expected_disposition` (`informational` or
`human`), `reviewed_by`, and `reviewed_at`. The review set does not yet exist;
do not copy synthetic labels into it as if they were independently reviewed.

## TASK-41: One fictional business policy source

`data/policies/support_v1.json` is the validated source for delivered-only
eligibility, inclusive 30-day returns and inclusive 7-day damage reporting.
The checker and generated PDF guidance consume these same rules. Results and
retrieved chunks carry policy ID, version, source hash and rule IDs; window
eligibility never authorizes a business action. Safety incidents and policy
exceptions require human review independently of eligibility.

Generate reference PDFs with `python -m src.knowledge.export_policy`, then
index with `python -m src.knowledge.ingest`. Identical exports and indexes skip
completed documents. A change under an existing PDF/policy version fails
export; use a new version and extend the validated loader's supported version
before adoption. Expanded legacy PDFs remain on disk; superseded return/damage
references are excluded from active RAG context. The corpus has 13 PDFs: seven
original references, four exact simulation replies, two generated policy
references. The legacy seed exporter refuses to overwrite existing references.

With RAG enabled, a used policy result requires matching active retrieved rule
metadata. Missing, conflicting or obsolete policy evidence produces explicit
safety findings and human escalation even if Jev passes. Business policy
provenance is separate from `informational_only_v4` send policy. Reports and
holdout resume checks include the active business policy; historical reports
remain readable. Chroma history and fictional orders cannot authorize real
customer-specific claims, and real customer sending remains disabled.

Earlier descriptions of hardcoded checker windows and duplicated policy prose
are historical. This is consistency validation, not merchant approval or a
claim of improved model accuracy. New measurements require a completed run.


## Latest measured development run (TASK-43)

TASK-43: 50 attempted, 50 scored, 47 matched; disposition match 0.94; 0 false simulated sends, 3 false escalations, 0 operational failures. Full-run p95: 52145.7439000078 ms; reported token cost: 0.245525665. See [saved measurement](../../docs/measurements/task43_regression.json).
The current result uses informational-only labels and fake delivery. Historical fixture-backed and pre-Jev/RAG reports do not describe this run. The 200-case and independent release evaluations remain separate and were not rerun.
