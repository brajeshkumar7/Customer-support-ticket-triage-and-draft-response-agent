# Production-readiness follow-ups

## Local PDF RAG (TASK-37)

The graph now uses actual simulation PDFs, dense Chroma + sparse BM25 retrieval
and bounded evidence review. The worker remains on its independently approved
templates. Before broadening automatic replies, review document ownership,
authority, conflicting policies, freshness, access control and citation
entailment. Measure retrieval on a larger labeled corpus; RRF similarity is
not confidence. Add OCR/table-aware extraction only with its own measured
acceptance checks. The seven reference PDFs and four simulation reply PDFs are fictional, not merchant approval.
PDFs are assumed immutable. The skip ledger uses relative filename + first 150
words, so later edits are not detected; revisions must use new filenames.
Re-ingestion invalidates prefix-changed/removed sources; schedule that explicitly in
any future deployment. No RAG benchmark or new real-send release is claimed.

## Controlled deployment status (reviewed 2026-10-06)

Code now defines a paid Render worker and PostgreSQL ledger for controlled
Zoho polling, exact ticket/contact allowlisting, a database kill switch,
versioned informational templates, and uncertain-send reconciliation. It has
not been deployed or tested against a live Zoho thread schema in this change.
`off` is the default, `shadow` cannot write to Zoho, and `live` fails startup.
The knowledge file is still marked `review_required`; no test send can start
until its owner approves it and configures the matching hash. Earlier
follow-ups below describe the historical graph path. See
`docs/controlled_render.md` for current deployment steps and limits.

**Real-customer blockers:** Select authoritative order, shipment, billing,
and policy providers; verify requester identity and data freshness; collect
200 attributed reviewed release cases and 100 real shadow decisions; test
controlled intake, restart, privacy, and reconciliation; record a separate
live-send decision. A finite zero-failure sample is a release gate, not proof
of perfect accuracy. The current poller uses one worker and must be observed
for API paging/cursor gaps and Zoho credit consumption.

This file tracks improvements to revisit as the project approaches its final
production-style portfolio state. These notes do not expand the acceptance
criteria of the current TASKS.md item. Implement them only when they fit the
active task and the PRD; otherwise keep them deferred until the relevant later
phase.

## Deferred follow-ups

Some "Current state" and "Status" paragraphs below are dated snapshots from
their original tasks. The current graph has recall, classify, conditional fact
gathering, informational safety review, respond, supervisor, simulated send or
explicit escalation, and remember on simulated success. The latest completed
50-case run matched 50/50 author-drafted dispositions with 7 simulated sends;
it predates the final TASK-32 triage edit. The 200-case author-labeled holdout
matched 189/200, below its 95% target. Neither validates real customer sending.

### Validate deterministic decision gate and improve model review quality

**Current state:** TASK-25 adds a deterministic gate for billing disputes with
no transaction source, missing/unknown/unavailable order data, unavailable
policy data, customer injury/product danger, explicit manager requests, policy
exceptions, and ambiguous intent. The Jev supervisor remains an independent
review signal. The Zoho agent runner passes `allow_delivery=False`, so it is
draft-only inside the graph even if `.env` enables sending. TASK-34 added a
separate operator-reviewed controlled email mode. The standalone controlled
`zoho_smoke` command remains separate. Fourteen new offline rule regressions
specify evidence and acceptable drafts/dispositions.

**Historical follow-up:** Re-run the 25-ticket graph evaluation with simulated delivery,
include the additional safety scenarios in future labeled graph evaluations,
and review per-category false sends, missed escalations, unsupported-claim
review flags, and false escalations. Keep live agent delivery blocked until a
separate decision after zero false sends across a reviewed safety suite and
validation against authoritative business sources. A passing deterministic
unit set does not prove generated drafts are safe.

**Verification:** Run the safety regression module offline and graph tests with
fake model/tool/sender dependencies. Confirm the Zoho agent command cannot
invoke any sender when the environment flag is true. Inspect the later saved
benchmark report; do not overwrite baseline numbers without a completed run.

**Status:** The quoted 14-case gate result and connection failure describe an
earlier TASK-25 snapshot. Later complete 25- and 50-case fake-sender graph
benchmarks are recorded in `PROGRESS.md`. The current informational-only
policy still needs independent review and a fresh post-TASK-32 run.

### Reuse the compiled graph while keeping memory per ticket

**Current state:** `build_graph` receives a `ShortTermMemory` instance and
closes over it. The caller therefore creates a graph and a memory instance for
each ticket run.

**Follow-up:** Consider compiling the graph once and supplying a distinct,
ticket-scoped memory object through each invocation's runtime context or an
equivalent LangGraph-supported mechanism. Keep ticket data isolated, make the
memory queryable for the lifetime needed by observability/debugging, and define
when per-run memory is released.

**Verification:** Exercise simultaneous runs for different ticket IDs and
confirm neither run can read or overwrite the other's state. Confirm a caller
can inspect a run's stored values after completion.

**Status:** Deferred; revisit during production-readiness review.

### Grow graph topology from workflow responsibilities

**Historical state:** TASK-05 initially had only `classify` and `respond`.
The current graph has the review, fact-gathering, routing, and memory nodes
described in `docs/architecture.md`.

**Follow-up:** Add clearly named nodes only as needed to implement the PRD
workflow: ticket intake/validation, classification, fact gathering using the
specified tools, grounded response drafting, and review/decision routing for
resolution versus human escalation. Integrate the existing roadmap work for
async tool dispatch and the supervisor/retry/failure path rather than
duplicating it.

Do not use a numeric environment variable to set the number of graph nodes.
Node count follows explicit workflow responsibilities; nodes may be
deterministic steps, tool dispatch, or focused LLM roles. Keep the graph within
the support-ticket scope in the PRD.

**Verification:** Tests should cover the actual routing paths, grounded drafts,
escalation, and bounded failure behavior as those capabilities are added.

**Status:** The planned graph topology was implemented in later tasks. The
numeric-node environment setting remains intentionally absent.

### Calibrate supervisor decisions against labeled scenarios

**Current state:** TASK-09 asks an LLM critic to assess grounding, unsupported
claims, and urgency-aligned tone. Its structured checklist output is validated
and the PASS/FAIL decision is derived from the individual check results, but
the critic has not been calibrated against a labeled evaluation set.

**Follow-up:** During TASK-18 and TASK-19, measure false passes and false
failures for each checklist item against human-labeled drafts. Track critic
latency, retry count, escalation rate, and token usage alongside task outcomes,
and refine check definitions or prompts based on observed misses. Keep
deterministic policy and tool facts authoritative; a critic verdict is a review
signal, not proof that every claim is correct. Feedback retries provide bounded
recovery but do not correct a critic that repeatedly misjudges evidence.

**Verification:** Report per-check precision/recall or equivalent confusion
counts, representative failure examples, retry/escalation counts, and
latency/token usage from actual evaluation runs. Confirm a deliberately
unsupported claim is rejected and valid grounded drafts are not rejected at an
unacceptable rate.

**Status:** Checklist behavior has been exercised, but per-check human-labeled
calibration remains open. Synthetic disposition scores do not supply it.

### Protect tool logs and evaluate order-detail extraction strategies

**Current state:** Mock tool events are written to JSONL with their inputs and
outputs. For non-FAQ human-review cases, `gather_facts` makes a separate LLM
call to extract order details before concurrent fixture tools. A single
covered FAQ intent skips extraction and business tools. Fixture data is synthetic.

**Follow-up:** Before using real customer data, define field redaction and log
retention rules. During the full evaluation (TASK-19), compare the current
separate LLM extraction call with lower-call alternatives: deterministic
extraction of an explicit order ID while retaining the ticket's stated reason,
and extracting order details as part of classification. Measure order-ID and
reason extraction accuracy, tool-match/task-completion accuracy, end-to-end and
extraction latency, and request/token usage. Keep the current separate call
until the comparison provides evidence for a change. Any alternative must
validate that an order ID was explicitly present and preserve concurrent
dispatch of the three tools.

**Verification:** Confirm logs exclude configured sensitive fields and expire
according to the chosen retention policy. Record the extraction-strategy
comparison and its measured accuracy, latency, and request/token usage with the
TASK-19 evaluation results.

**Status:** Deferred; revisit during observability and evaluation work.

### Define long-term memory retention and stale-fact handling

**Current state:** The graph recalls local Chroma facts across ticket runs and
stores compact summaries with ticket and order identifiers. Recalled facts are
treated as historical context; current tool results remain authoritative.

**Follow-up:** Before using real customer data, define retention and deletion
rules for persisted facts, how facts are scoped to a customer or tenant, and
how outdated or conflicting facts are expired or superseded. Keep raw ticket
text and draft replies out of long-term memory unless a documented need and
privacy policy justify storing them.

**Verification:** Test that facts can be deleted according to the retention
policy, that one customer or tenant cannot retrieve another's facts, and that
stale facts do not override current verified tool results.

**Status:** Deferred; revisit before using real customer data and during
production-readiness review.

### Replace mock data sources and local persistence for deployment

**TASK-29 local boundary:** The graph and controlled worker now share an
informational-only approval rule. Seven of the original 50 tickets are labeled
eligible for simulated FAQ replies under that rule. All customer-specific
fixture cases are human review even when the mock order lookup succeeds.
`data/approved_knowledge/v1.json` remains `review_required`; no local
simulation result approves real customer sending. A hypothetical provider
evidence contract checks requester match, freshness, and contradictions, but
no actual order, shipment, billing, or identity provider is configured.
The frozen 200-case author-labeled holdout measures local behavior only and
cannot replace independently reviewed real-ticket cases or shadow validation.
The 2026-10-05 v3 run matched 189/200 cases (94.5%), below the 95% local
target, with 11 false escalations in general questions, zero false simulated
sends, and zero unsupported public claims. The false-escalation target is
still open; see `FAILURE_MODES.md` FM-015 and `PROGRESS.md`. Do not enable
customer sending from this result.

**Current state:** Order and policy tools use synthetic local fixtures, FAQ
search uses a small in-code dataset, and long-term facts persist in local
Chroma. These are development implementations, not production integrations.
An opt-in Zoho Desk outbound email adapter uses OAuth refresh tokens. A prior
manual controlled-ticket send was confirmed, but the current local graph
does not authorize real delivery. Zoho Desk is selected only for ticket
reply delivery, not as the source of order facts.

**Follow-up:** Before deployment, select and integrate the authorized commerce
or support API as the source of current order and customer facts, and select a
production-approved database for durable application data and/or semantic
memory. Keep current order status and policy decisions grounded in the
authoritative API; use long-term memory only for historical context. Choose
providers after defining data ownership, access control, privacy, retention,
availability, and budget requirements. Keep credentials in secret management
and define timeouts, rate limits, and bounded failure behavior for API calls.

**Verification:** Use API contract tests and sandbox/test credentials to cover
successful lookups, missing records, authorization failures, timeouts, and
rate limits. Verify database persistence, access isolation, backup/recovery,
and that failures still produce the intended safe escalation or fallback.

**Status:** Partially addressed: Zoho outbound code and a PostgreSQL worker
ledger are implemented, but no Render deployment or real business provider
contract tests have occurred. Selecting the authoritative commerce and
billing APIs remains required before real customer release.

### Validate Zoho Desk delivery in a controlled environment

**Current state:** Agent-initiated public replies are blocked by TASK-25's
`allow_delivery=False` override in the Zoho runner, even if the environment
flag is true. The separate `--send-reviewed` CLI path requires explicit human
approval of the draft and recipient on a controlled test ticket. The 50-case
informational benchmark and frozen 200-case holdout
use a fake sender and never send live replies. The standalone Zoho smoke command
targets one existing ticket and contact controlled by the operator; it sends
one fixed public message only after explicit CLI and interactive confirmation.
Ambiguous request outcomes are not retried; the operator must check the ticket
before any manual replay.

**Follow-up:** Before re-enabling graph delivery, first satisfy the TASK-25
zero-false-send gate on a reviewed suite, validate real order/policy providers,
and make a separate decision. Before enabling delivery for real customers,
use the standalone
smoke command against one Zoho Desk internal test ticket and controlled
contact, confirm the OAuth app has only the
required ticket-read and ticket-update scopes, define operator approval and
audit requirements, and establish a safe reconciliation procedure for timed-
out replies. Keep `ZOHO_DESK_SEND_ENABLED=false` until those checks and the
labeled reviewer evaluation are complete.

**Verification:** Exercise successful public updates, rejected credentials,
invalid ticket IDs, and timeouts in a non-production Zoho Desk account. Confirm
the smoke command requires explicit confirmation, sends no more than one reply,
and does not retry an ambiguous outcome. Confirm the human escalation contains
enough context to review without exposing credentials in logs.

**Status:** The operator previously confirmed one controlled Zoho send. The
new polling, allowlist, note, restart, and reconciliation paths remain
unvalidated against the live Zoho API; test-mode delivery stays gated.

`run_zoho --send-reviewed` now permits one human-approved email to a
controlled ticket/contact after showing the agent draft and safety findings. It
rechecks the requester and status before posting and makes no automatic retry
after an uncertain result. This is an operator test path, not automatic
customer delivery or evidence that local mock order data is authoritative.
After a failed draft review, this command proposes only a fixed neutral
acknowledgement; the failed draft is never used as public email content.

## Recording future follow-ups

Jev triage (TASK-36) now uses typed decisions and records option probabilities
and distribution confidence. Before choosing a confidence cutoff or claiming
an accuracy/speed improvement, evaluate the versioned category/urgency rubric
against labeled tickets and review uncertain, multi-intent, and adversarial
cases. The single verified API call proves connectivity and contract support;
it does not measure full-suite performance. Prior generative-classifier
reports remain historical. Holdout checkpoints from the old triage model
cannot be resumed into the new model/rubric run.

For each implementation step, record production-readiness considerations here
when the step reveals a relevant improvement. State whether each item is
implemented now or deferred, and link it to its related TASKS.md phase where
possible. If no relevant follow-up exists, do not add filler.


## TASK-38: Jev supervisor review

Generated human-review drafts use one OpenRouter Decisions request with three
Choice questions (pass, fail, insufficient_evidence). Configure
`OPENROUTER_SUPERVISOR_MODEL` independently from triage and drafting; its default
is `typesafe/jev-1.13`. Each check must select pass with probability >= 0.90.
This initial threshold is provisional, not calibrated. Fixed checklist guidance
supplies retry feedback; it does not identify individual unsupported sentences.
Malformed or unavailable reviews escalate. Exact approved FAQ templates retain
local validation without a supervisor model call. Checklist completion score is
not Jev probability. Current tools remain fictional; cited PDF guidance and
historical summaries do not verify customer identity. Safety gates and live-send
restrictions remain in force. Earlier generative-supervisor descriptions are
historical; accuracy and speed changes require new measured reports.


### TASK-39 current provenance and review output

The expanded Northstar PDFs are pinned and indexed as northstar_reference_v2
simulation references with nonempty knowledge IDs. Their approval_scope is
reference_only: this repairs stale provenance but does not promote them to
v1 exact FAQ approval or real business authority. New unpinned PDFs remain
unreviewed. Both single-ticket commands display supervisor_reason and raw Jev
supervisor_decision alongside the checklist score and workflow errors; the
synthetic command also displays safety_review. A blocked order still escalates.

## TASK-40: Evidence-bound safety assessment

The graph and controlled worker share `production_policy.decide_public_reply`
under `informational_only_v4`. The assessment records all detected blockers,
specific missing evidence, knowledge IDs/version and policy version. Separate
questions must be covered by the same approved reply; unsupported actions,
safety incidents, billing disputes and customer-specific facts remain human work.
This is a bounded informational policy, not a general proof of intent coverage.

RAG approval additionally requires an explicitly scoped
`automatic_reply_simulation` PDF containing the exact v1 reply, with trusted
hash-pinned provenance and a cited, sufficient coverage review. The corpus now
has seven unchanged reference-only PDFs and four separate fictional reply PDFs.
Neither historical Chroma summaries nor reference-only PDFs authorize sending.
The final graph delivery step rechecks evidence and exact outgoing text; the
worker also checks exact template text. Jev PASS cannot override any blocker.

Reindex with `python -m src.knowledge.ingest`. Run the fake-only benchmark with
`python -m src.eval.run_eval`; reproduce saved metrics with
`python -m src.eval.run_eval --report PATH`. Real customer sending stays disabled.
Approved simulation content is not merchant approval or production evidence.

### TASK-40 measured outcome (2026-10-06)

The configured-model fake-only report
`data/eval_reports/task29_20261006T165804Z_49001dc4.json` attempted all 50 cases:
46/49 scored disposition matches (0.9387755102040817), one unscored workflow
failure, three false escalations, zero false simulated sends and four simulated
replies. Full-run p95 was 53658.00060000038 ms; provider-reported total cost was
0.237483676. The accepted tracker was not overwritten. Safety enforcement held
in these cases, but clean workflow acceptance remains open (FM-026/027).
These numbers supersede no historical report and authorize no live sending.
