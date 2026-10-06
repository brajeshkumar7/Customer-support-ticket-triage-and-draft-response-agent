# TASKS.md — Working Task List

Keep this file up to date as you go — it's what lets a coding agent (or you,
after a week away) know exactly where the project stands. Check items off in
place; don't delete completed items, so the history stays visible.

## Phase 0 — Setup
- [x] TASK-01: Pick and write the concrete support-ticket task in `PRD.md` Section 2
- [x] TASK-02: Repo scaffold (folders, requirements, `.env.example`)
- [x] TASK-02b: Configure OpenRouter credentials and model IDs; the owner later
      selected paid models through `.env`. Ollama was proposed but is not wired.
- [ ] TASK-03: Docker image exists, but the runner is a stub and fixed host-side
      tools are not sandboxed by it. This original sandbox goal remains unmet.
- [x] TASK-04: Pick memory backend (in-memory short-term + local Chroma long-term), record choice in `DECISIONS.md`, update `AGENTS.md` tech stack
- [x] TASK-04b: Add API-level OpenRouter model fallbacks and bounded, logged 429 retries

## Phase 1 — Core Agent Loop
- [x] TASK-05: Basic LangGraph state machine, no tools or retries yet
- [x] TASK-06: Add persistent short-term state across steps
- [x] TASK-07: Convert tool dispatch to async (`asyncio`) for independent calls
      (automated tests and historical manual runs recorded)
- [x] TASK-08: Add long-term memory store, wire read/write into graph

## Phase 2 — Safety & Recovery
- [x] TASK-09: Supervisor/critic node with checklist-based evaluation
- [x] TASK-10: Retry-with-feedback loop, capped at 3 retries after the initial
      draft
- [x] TASK-11: Explicit terminal outcome and Zoho adapter were implemented.
      Direct graph sending was later disabled; the current graph simulates
      approved replies or escalates, and `run_zoho` is draft-only.

## Phase 3 — Observability
- [x] TASK-12: Structured JSONL logging for graph nodes, tool calls, LLM
      attempts, and rate-limit events (automated and historical provider runs)
- [x] TASK-13: Read-only local run-history dashboard in Next.js + TypeScript
- [x] TASK-14: Stream graph node updates to the caller (fake-client graph
      tests pass; node updates, not model tokens)

## Phase 4 — Security
- [x] TASK-15: Build a small prompt-injection test set (5–10 attempts)
- [x] TASK-16: Run tests, document what got through in `PRD.md` Section 5
- [x] TASK-17: Patch the successful injection, re-test, log the fix (10/10
      scored cases safe post-fix)

## Phase 5 — Evaluation & Metrics
- [x] TASK-18: Build a fixed set of 25 synthetic support tickets, five per
      category, including documented escalation edge cases; billing disputes
      escalate because no billing transaction lookup exists.
- [x] TASK-19: Run all 25 synthetic tickets through the real graph and
      configured model with an injected fake reply sender; measure simulated
      disposition, retries, latency, and logged cost in `PROGRESS.md`. Never
      send benchmark replies to Zoho. Keep live validation to the explicit
      one-ticket smoke test for a ticket/contact the operator controls.
- [ ] TASK-20: Run sequential vs. async latency comparison, record the delta

## Phase 6 — Ship
- [x] TASK-21: Architecture diagrams for the local graph and controlled worker
- [x] TASK-22: README with report-backed metrics and documented failure modes
- [x] TASK-23: `PRD.md` Section 7 records the measured approval-coverage trade-off

### TASK-24 — Single-ticket synthetic and Zoho commands
- [x] Add `python -m src.agent.run_synthetic --case-id CASE_ID` using an
      isolated Chroma client and simulated sender, with no Zoho requests.
- [x] Add `python -m src.agent.run_zoho --ticket-id ID --draft-only`: confirm a
      controlled existing ticket, fetch its Email subject/description, and run
      the graph. TASK-25 now forces delivery off for this command.
- [x] Add network-free command/client tests and document both flows in
      `README.md` and `flow.md`; keep `zoho_smoke` as a delivery-only test.

### TASK-25 — Improve decision safety and accuracy
- [x] Block live delivery from `run_zoho`; retain the confirmed delivery-only
      smoke test separately.
- [x] Audit the 25 benchmark labels and recorded false sends/false escalation;
      document clarification-versus-human-review criteria.
- [x] Add deterministic safety decisions and provider-neutral order, policy,
      and FAQ interfaces with typed unavailable outcomes.
- [x] Expand offline safety regression cases and report false sends, missed
      escalations, unsupported-claim review flags, and false escalations by
      category. The 18-case offline gate suite matches all expected
      decisions; this does not count as a generated-draft benchmark or an
      independently human-reviewed release set.
- [x] Rerun the 25-ticket graph benchmark with simulated delivery only; update
      measured metrics from the fully scored 2026-10-04 saved report. The
      latest run matched 25/25 dispositions; p95 was 48374.99450001633 ms.
- [x] Keep real commerce, billing, authoritative policy, automatic Zoho
      intake/deduplication, durable runs, protected logs, and human routing as
      separate deployment work until providers and requirements are selected.

## Parking Lot (ideas NOT in current scope — do not build yet)
*(Move an item here instead of building it mid-task if it's outside PRD scope.
Revisit only after Phase 6 is done.)*

- Production-readiness follow-ups are tracked in `PRODUCTION_READINESS.md`,
  including per-ticket memory lifecycle and workflow-driven graph expansion.

## Phase 7 — Controlled deployment

### TASK-26 — Controlled automatic-reply deployment (2026-10-04)
- [x] Add a fail-closed `off`/`shadow`/`test` worker with Zoho polling,
      PostgreSQL job identity, test allowlist, kill switch, bounded reply
      templates, and no direct graph auto-send. `live` refuses startup.
- [x] Remove raw ticket/draft content from deployment JSONL events; disable
      unscoped Chroma in the outbound path; set explicit OpenRouter timeout
      and disable SDK-internal retries.
- [x] Add no-network safety, identity, duplicate, and uncertain-send tests.
- [x] Compare one structured classify/extract call with the saved two-call
      graph on the 25 fixed synthetic labels. Combined was faster and 23/25
      category-correct, below the 95% gate; keep the existing graph path.
      The controlled FAQ worker uses no LLM. Broader reviewed comparison
      remains part of the release evaluation.
- [ ] Deploy paid Render resources in shadow mode and validate Zoho thread
      schema, paging, intake, restart recovery, private notes, and unknown-send
      reconciliation on controlled tickets. No Render account is connected.
- [ ] Configure real operator alerts for source failures, unknown sends,
      backlog, and rate limits from worker warning/error events.
- [ ] Owner-review the versioned FAQ/policy file and allowlist controlled
      ticket IDs and requester addresses before `test` sends.
- [ ] Collect and review at least 200 labeled release cases across all five
      categories; run `src.eval.run_release_eval` and record actual results.
- [ ] Select and contract-test authoritative order, shipment, billing, and
      policy providers; verify requester identity, freshness, and failures.
- [ ] Review 100 representative real shadow decisions, measure arrival-to-reply
      p95, and record a separate live-send decision. `live` remains blocked.

### TASK-27 — Expand the synthetic benchmark to 50 cases
- [x] Preserve the original 25 and add 25 author-labeled tickets, five per
      category, with matching manifest and JSONL IDs.
- [x] Require 50 cases for new simulated-delivery runs and metric publication;
      preserve offline reading of historical 25-case reports.
- [x] Validate data and evaluator behavior with network-free tests. New labels
      are not the independent human-reviewed release set.
- [x] Run all 50 tickets with the configured model and fake sender; publish
      measured accuracy, latency, retries, and cost only from a complete run.
      The 2026-10-04 report is 46/50 with four false simulated sends, so the
      zero-false-send release gate remained open at that point.

### TASK-28 — Resolve four missed escalations in the synthetic benchmark
- [x] Trace `order_08`, `damage_09`, `general_09`, and `general_10` from the
      saved report through tool evidence, safety gate, supervisor, and sender.
- [x] Block delivered/nonreceipt conflicts, safety hazards, unsupported FAQ
      requests, and requested account actions in the deterministic gate while
      preserving routine answerable cases.
- [x] Add offline and network-free graph regressions; the expanded gate set
      matches 31/31 expected decisions.
- [x] Rerun all 50 tickets with the configured model and fake sender. The
      2026-10-04 post-fix report matched 50/50, with 0/28 false simulated
      sends and 0/22 false escalations. Real customer sending remains blocked
      pending the separate release prerequisites in TASK-26.

### TASK-29 — Shared informational approval and frozen local holdout
- [x] Align the graph and controlled worker on a versioned, evidence-linked
      informational-only decision; preserve the old 50/50 report as historical.
- [x] Preserve original ticket labels and add a separate 50-case manifest for
      the new policy. Freeze 200 author-labeled, templated synthetic holdout
      cases with a SHA-256 check; these are not independently reviewed.
- [x] Add network-free checks for FAQ template delivery, blocked customer
      facts, duplicate polling, changed identity, source failures, and handoff.
- [x] Complete the configured-model 50-case regression and 200-case holdout
      with fake sending only; record exact disposition, evidence, latency,
      model-call, cost, and failure metrics. Do not enable real customer sends.
- [ ] Reach the local holdout targets: at least 95% disposition accuracy,
      zero critical false sends/unsupported public claims, and FAQ p95 below
      30 seconds. Current holdout is 189/200 (94.5%) with 11 false
      escalations; accuracy target remains open. This is not live-release
      authorization.

### TASK-30 — Improve FAQ paraphrase precision
- [ ] Preserve TASK-29 v1's 189/200 score as the immutable baseline; create a
      separately versioned paraphrase regression set before changing rules.
- [ ] Fix the false `multi_intent_uncovered` detections on harmless framing
      and add supported “cards at checkout” FAQ phrasing without allowing
      unrelated second intents to pass.
- [ ] Validate positive and adversarial neighboring cases offline, then run
      a fresh configured-model fake-sender measurement. Record false sends,
      false escalations, evidence coverage, latency, and cost; keep real Zoho
      sending disabled.

### TASK-31 — Measure shared Chroma recall in synthetic evaluations
- [x] Configure 50- and 200-case evaluators to use one fresh ephemeral Chroma
      collection per evaluation, shared sequentially across tickets; keep the
      configured persistent Chroma store untouched.
- [x] Record recalled summary IDs/counts and the memory mode in case results
      and reports; preserve previous reports as historical with unrecorded
      effective memory mode.
- [ ] Compare complete 50- and 200-case fake-delivery runs using the same
      shared-memory mode. The 50-case run is saved as
      `task29_20261005T183529Z_2979caa5.json`; a comparable complete
      200-case rerun is still pending.

### TASK-32 — Complete per-ticket category and priority triage
- [x] Return category, urgency, priority band, numeric sort rank, and the basis
      for classification/urgency in graph state and the synthetic/Zoho draft
      command output.
- [x] Preserve the no-model path for a single approved FAQ intent while
      deriving urgency from explicit high-priority and impact wording.
- [x] Capture predicted category, urgency, and priority in new evaluation
      rows; calculate category accuracy and urgency/priority distributions.
- [x] Correct clear model category conflicts using high-precision billing,
      return, damage, and order-status intent signals; keep each correction's
      basis visible. Do not treat a bare "today" mention as P1 urgency.
- [x] Require a named item/product or explicit damage/defect wording before a
      deterministic malfunction category override; preserve vague complaints.
- [ ] Run a fresh configured-model classification evaluation and review its
      category accuracy and urgency labels; these measures do not authorize
      live replies.
- [ ] Decide separately whether a multi-ticket queue or SLA routing is needed;
      current priority metadata ranks one ticket but does not create a queue.
