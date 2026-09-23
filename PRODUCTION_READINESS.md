# Production-readiness follow-ups

This file tracks improvements to revisit as the project approaches its final
production-style portfolio state. These notes do not expand the acceptance
criteria of the current TASKS.md item. Implement them only when they fit the
active task and the PRD; otherwise keep them deferred until the relevant later
phase.

## Deferred follow-ups

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

**Current state:** The graph has `classify` and `respond` nodes as the TASK-05
vertical slice. It does not yet gather verified facts or review/route drafts.

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

**Status:** Deferred; evolve the graph in the relevant TASKS.md phases.

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

**Status:** Deferred; evaluate with TASK-18/TASK-19.

### Protect tool logs and evaluate order-detail extraction strategies

**Current state:** Mock tool events are written to JSONL with their inputs and
outputs. `gather_facts` makes a separate LLM call to extract order details
before starting concurrent tool calls. Current fixture data is synthetic.

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

**Current state:** Order and policy tools use synthetic local fixtures, FAQ
search uses a small in-code dataset, and long-term facts persist in local
Chroma. These are development implementations, not production integrations.
An opt-in Zoho Desk outbound email adapter is implemented using OAuth refresh
tokens; it is disabled by default and has not been live-tested. Zoho Desk is
selected only for ticket reply delivery, not as the source of order facts.

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

**Status:** Partially addressed: Zoho Desk outbound delivery is implemented.
Selecting the authoritative commerce API and a production database remains
deferred until before deployment.

### Validate Zoho Desk delivery in a controlled environment

**Current state:** Public replies are sent only when explicitly enabled and
all three supervisor checklist items pass. Ambiguous request outcomes are not
retried; the escalation asks a reviewer to check the ticket before sending to
avoid a duplicate. Automated tests mock the sender, and no live send has been
performed.

**Follow-up:** Before enabling delivery for real customers, test against a
Zoho Desk sandbox or internal test ticket, confirm the OAuth app has only the
required ticket-read and ticket-update scopes, define operator approval and
audit requirements, and establish a safe reconciliation procedure for timed-
out replies. Keep `ZOHO_DESK_SEND_ENABLED=false` until those checks and the
labeled reviewer evaluation are complete.

**Verification:** Exercise successful public updates, rejected credentials,
invalid ticket IDs, timeouts, and duplicate/reconciliation procedures in a
non-production Zoho Desk account. Confirm the human escalation contains enough
context to review without exposing credentials in logs.

**Status:** Deferred; live validation requires a controlled Zoho Desk account.

## Recording future follow-ups

For each implementation step, record production-readiness considerations here
when the step reveals a relevant improvement. State whether each item is
implemented now or deferred, and link it to its related TASKS.md phase where
possible. If no relevant follow-up exists, do not add filler.
