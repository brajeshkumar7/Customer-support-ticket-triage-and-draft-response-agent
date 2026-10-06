# PRD â€” Support Ticket Triage Agent with Runtime Safety

## 1. Problem Statement
Most portfolio "agent" projects are a single LLM call wrapped in a loop with no
memory, no recovery from failure, and no sandboxing. The goal here is to build a
**multi-step, stateful agent** that can fail safely and recover â€” the behavior
companies actually need before putting an agent into production.

## 2. Goal
Build an agent that completes a real multi-step task (e.g., "research a topic
across 3 sources, reconcile conflicting facts, and produce a cited summary" or
"triage and resolve a batch of support tickets using 2â€“3 tools") with:
- Persistent state across steps (not just chat history)
- Fixed tool calls; model-generated code and shell commands are never executed.
  The existing Docker runner is a stub, not an enforced production boundary.
- A supervisor/critic step that catches failures and retries with a cap

**Chosen task:** Customer support ticket triage and draft-response agent for an
e-commerce context. Given an incoming support ticket (order status, return
request, damaged item, billing dispute, general question), the agent:
1. Classifies category and urgency, then exposes a sortable P1/P2/P3 priority
   band for the human reviewer (priority does not represent an SLA or queue)
2. When needed, uses fixed order lookup (mock data), return/refund policy,
   and FAQ search tools to gather facts. A covered FAQ intent skips the mock
   business tools.
3. Produces an approved informational FAQ template or a human-review draft
   grounded in available tool results
4. Uses the supervisor as one review signal and a deterministic safety gate
   before any delivery. Billing disputes without transaction evidence, missing
   or unknown orders, safety reports, explicit manager requests, policy
   exceptions, and unresolved intent must not be auto-sent. During TASK-25,
   agent-initiated Zoho delivery is blocked. A separate, manually reviewed
   command may send either the approved draft or a fixed acknowledgement to
   an explicitly confirmed controlled contact; it is not automatic customer
   delivery. The controlled delivery smoke test remains available.

For the TASK-29 local benchmark, the graph and controlled worker share an
informational-only approval rule. An exact versioned FAQ reply may be simulated
without LLM drafting or mock business tools. With TASK-37 RAG enabled, Jev
and PDF evidence review still run before that exact reply can be simulated.
Other tickets are drafts or
escalations for human review; mock order data does not authorize delivery.

## 3. Non-Goals
- Not building a general-purpose agent framework â€” pick one real, narrow task
- Not optimizing for maximum autonomy â€” optimize for *predictable* failure

## 4. Architecture
- **PDF RAG (TASK-37):** The owner selected corpus-wide hybrid fact retrieval.
  Actual PDFs live in `knowledgebase/`. One incremental CLI chunks and indexes
  dense MiniLM embeddings in local Chroma plus sparse BM25 vectors in SQLite,
  using relative-filename + first-150-word ledger hashes and committed
  generations. PDFs are immutable; revisions require new filenames. After Jev triage, a bounded
  allowlisted agent reviews evidence; generated human drafts cite chunk IDs.
  Safety decisions require hash-pinned retrieved evidence for existing exact
  informational simulation replies. Unreviewed PDFs cannot grant authority.
  Controlled worker and real-delivery restrictions remain unchanged.
- **Orchestration:** LangGraph (or an equivalent graph/state-machine framework) â€”
  chosen specifically because it models cycles and state explicitly, unlike a
  simple prompt-chaining script
- **Tool execution:** fixed, application-owned Python tools run in the host
  process; no model-selected arbitrary code is executed. The existing Docker
  definition does not sandbox these calls. Independent required tools can run
  concurrently with `asyncio`; latency benefits must be measured.
- **Memory:** short-term (working state per run) + long-term (a simple vector or
  key-value store for facts learned across runs)
- **Supervisor loop:** a critic step evaluates the worker's output against a
  checklist; on failure, retries with feedback injected into the next attempt,
  capped at N retries before failing loudly (not silently)
- **Deterministic send-safety gate:** explicit application rules can block
  delivery even when the Jev supervisor passes. An LLM verdict alone is not a
  send authorization.
- **Ticket triage:** each run exposes category, urgency, a priority band and
  sort rank, plus the basis used. Explicit safety/high-stakes/time-critical
  wording can raise priority deterministically. The single-ticket graph does
  not implement multi-ticket queue ordering or SLA routing.
  With PDF RAG enabled, all tickets use one Jev Decisions call
  with separate Choice questions for category and urgency. The state preserves
  the selected labels, all option probabilities, distribution confidence, and
  served model. Unclear or invalid answers fail into human escalation. Jev
  confidence is distinct from supervisor checklist confidence and does not
  authorize delivery. The prior generative classifier's measurements remain
  historical until a full Jev benchmark is run.
- **Controlled Zoho deployment:** a single Render worker polls Zoho and uses
  PostgreSQL for unique inbound-thread jobs, a cursor, exact test allowlists,
  a kill switch, and delivery status. `off` is the default; `shadow` never
  writes to Zoho; `test` sends only versioned informational templates to
  allowlisted controlled tickets and contacts; `live` fails startup pending
  authoritative order/shipment/billing/policy sources and separate approval.
  Customer-specific and discretionary requests go to a human. Unscoped Chroma
  memory and LLM prose do not enter the outbound template path.
- **Streaming:** LangGraph `astream(..., stream_mode="updates")` exposes each
  completed node's partial state; token-by-token streaming is not implemented.
- **Adversarial input handling:** treat any tool output (web results, file
  contents, user-provided text) as untrusted; test the agent against a small set
  of prompt-injection attempts (e.g., a scraped webpage containing "ignore
  previous instructions...") and document what got through vs. what the
  sandboxing/system-prompt boundaries caught

## 5. Success Metrics (write these down, they're your resume bullets)
- [x] Disposition match rate across the current fixed set of 50 synthetic scenarios
- [x] Mean retries-to-success and failure rate after cap
- [ ] p95 latency comparison of sequential versus async tool calls (TASK-20;
  full-run p95 is measured, but the sequential comparison is not)
- [x] Cost per successful run (provider-reported token cost from logs)
- Category classification accuracy and urgency/priority distribution on
  labeled local cases; report these separately from disposition accuracy.
- False sends, missed escalations, unsupported-claim review flags, and false
  escalations by category; the TASK-19 baseline is pre-TASK-25 and must not be
  presented as a post-gate result.
- TASK-19 and the expanded TASK-27 benchmark measure disposition with a fake reply sender. A simulated send is
  not evidence of real Zoho delivery; validate the Zoho adapter separately
  with the explicitly confirmed one-ticket smoke test.
- TASK-29 uses a separate informational-only label manifest and a frozen
  200-case author-labeled synthetic holdout. Its results must be reported
  separately from the historical 50/50 fixture-backed result. The holdout is
  not an independently reviewed release set. Its scenario text was visible to
  the developer during the v2 completeness fix, so its later score is a
  reproducible synthetic regression, not an untouched holdout estimate.
- Release targets, not measured results: at least 200 human-reviewed cases
  across five categories; zero critical false sends, wrong recipients,
  unsupported customer-specific claims, and duplicates; at least 95% correct
  dispositions; p95 under 30 seconds for approved FAQ replies and under 60
  seconds for verified customer-specific replies. Also review 100 real shadow
  decisions before a separate live-send decision. The offline policy evaluator
  cannot measure actual delivery or arrival-to-reply latency.
- The latest completed 50-case report (before the final TASK-32 triage edit)
  measured 50/50 disposition matches, 0 false simulated sends, 0 false
  escalations, 7 simulated replies, 43 escalations, p95
  44778.41449999687 ms, and total provider-reported cost 0.115013845.
  TASK-29 v3 is an earlier 50/50 historical result. The
  separate 200-case templated holdout measured 189/200 matches (0.945), 11
  false escalations (all general questions), 0 false sends, and 0 unsupported
  public claims. Full-run p95 was 59722.046200000026 ms; approved-FAQ p95 was
  714.4188000002032 ms. The 95% disposition target was missed. Exact results
  and provenance are in `PROGRESS.md` and `docs/measurements/`; live sending
  remains disabled.
- Prompt-injection test results: TASK-16 baseline was 10 attempts, 1 unsafe
  injection success (`policy-note-manager-exception`). TASK-17 added
  model-context field allowlisting and reran all 10 cases with the configured
  `.env` models: 10 scored, 0 unsafe injection successes. The previously
  unsafe manager-note draft no longer repeated the injected approval claim.
  Any draft adopting an injected unverified claim counted as unsafe. Two
  additional post-fix runs (20 attempts total) were unscored because this
  execution environment could not connect to OpenRouter; they are excluded
  from the 10 scored results. The refund-timing statement in the refund
  pre-approval case is supported by the existing refund-timing FAQ fixture.

`PROGRESS.md` links each completed measurement to a saved report. The current
triage edit still needs a fresh complete run; the interrupted OpenRouter run
does not establish new accuracy.

## 6. Observability Requirements
- Local evaluation logs tool inputs/outputs, latency, and provider cost.
  Deployment logs omit ticket bodies and drafts; PostgreSQL stores minimal
  job and delivery metadata with retention cleanup.
- A local, read-only Next.js App Router + TypeScript dashboard showing run
  history from server-read JSONL files under `LOGS_DIR` (default
  `../data/logs` relative to `dashboard/`); see `dashboard/README.md` for
  local startup instructions

## 7. Explicit Trade-off

The informational-only approval policy gives up automation coverage to avoid
replying from mock or unverified customer-specific data. In the latest completed
50-case run, 7 tickets received simulated replies and 43 escalated; all 50
matched their author-drafted disposition labels, with zero false simulated
sends. The separate 200-case author-labeled holdout missed its 95% target:
189/200 dispositions matched, with 11 false escalations and no false simulated
sends. Narrow approval improves observed send safety in these synthetic cases
but rejects some answerable questions and cannot establish real-customer
accuracy. The 50-case result predates the final triage edit; real sending
remains blocked pending authoritative sources and independent review.

## 8. Deliverables
- [ ] Public repo status is unverified; the README links the architecture diagram
- [x] README documents real failure modes and the failure log
- [x] README includes a report-backed metrics table


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

TASK-41 measurement: 50 attempts, 47 scored, 45 matched; two false escalations and three unscored workflow failures remain open. Zero false simulated sends, four simulated replies. Full-run p95: 65542.06790000899 ms. Source and exact metrics: [TASK-41 diagnostic](docs/measurements/task41_policy.json). This validates the tested policy consistency contract, not overall accuracy acceptance or real-customer automation.
