# PRD — Support Ticket Triage Agent with Runtime Safety

## 1. Problem Statement
Most portfolio "agent" projects are a single LLM call wrapped in a loop with no
memory, no recovery from failure, and no sandboxing. The goal here is to build a
**multi-step, stateful agent** that can fail safely and recover — the behavior
companies actually need before putting an agent into production.

## 2. Goal
Build an agent that completes a real multi-step task (e.g., "research a topic
across 3 sources, reconcile conflicting facts, and produce a cited summary" or
"triage and resolve a batch of support tickets using 2–3 tools") with:
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
   agent-initiated Zoho delivery is blocked; the separate controlled delivery
   smoke test remains available.

For the TASK-29 local benchmark, the graph and controlled worker share an
informational-only approval rule. An exact versioned FAQ reply may be simulated
without LLM drafting or mock business tools. Other tickets are drafts or
escalations for human review; mock order data does not authorize delivery.

## 3. Non-Goals
- Not building a general-purpose agent framework — pick one real, narrow task
- Not optimizing for maximum autonomy — optimize for *predictable* failure

## 4. Architecture
- **Orchestration:** LangGraph (or an equivalent graph/state-machine framework) —
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
  delivery even when the LLM supervisor passes. An LLM verdict alone is not a
  send authorization.
- **Ticket triage:** each run exposes category, urgency, a priority band and
  sort rank, plus the basis used. Explicit safety/high-stakes/time-critical
  wording can raise priority deterministically. The single-ticket graph does
  not implement multi-ticket queue ordering or SLA routing.
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
