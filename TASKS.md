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
      approved replies or escalates. `run_zoho` keeps graph delivery disabled;
      TASK-34 added a separate manually reviewed controlled email mode.

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
      historical 25-case run matched 25/25 dispositions; p95 was 48374.99450001633 ms.
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

Historical category overrides below were superseded by TASK-36 Jev triage.
Priority metadata/floors remain active; the no-model FAQ path requires RAG off.

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
- [x] Record current Jev category accuracy from TASK-41 (45/50 = 0.9).
- [ ] Validate urgency labels independently; current disposition acceptance
      and calibration remain open and do not authorize live replies.
- [ ] Decide separately whether a multi-ticket queue or SLA routing is needed;
      current priority metadata ranks one ticket but does not create a queue.

### TASK-33 — Run controlled Zoho tickets through the local agent
- [x] Keep the fixed-message `zoho_smoke` command separate from the agent run.
- [x] Let `run_zoho --draft-only` analyze controlled tickets with usable text
      across Zoho channels, print its local run ID, and never post or assign a
      Zoho reply. The controlled worker's Email-only send boundary is unchanged.

### TASK-34 — Send one manually reviewed agent draft to a controlled Zoho contact

Original draft-only send condition below was extended by TASK-35 acknowledgement fallback.

- [x] Add `run_zoho --send-reviewed`: run the graph without automatic delivery,
      display the exact draft and safety findings, and require supervisor PASS
      plus explicit recipient and ticket confirmation before one public email.
- [x] Recheck ticket text and recipient before the send, reject changed or
      unavailable tickets, and never automatically retry an uncertain outcome.
- [x] Keep unattended graph and real-customer auto-send disabled; cover the
      controlled path with network-free command and Zoho adapter tests.

### TASK-35 — Acknowledge controlled tickets when the draft fails review
- [x] Keep failed or unverified agent prose out of public email. In the
      reviewed-send command, show a fixed human-review acknowledgement instead.
- [x] Require the same exact recipient and send confirmation, recheck the
      ticket, and preserve one-attempt delivery with no automatic retry.
- [x] Keep graph and unattended customer delivery gates unchanged.

### TASK-36 — Use Jev typed Decisions for triage
- [x] Review OpenRouter/TypeSafe contracts and replace generative category/
      urgency classification with one Jev request; all RAG-enabled tickets use it (the FAQ shortcut is
      retained only with RAG disabled).
- [x] Configure the triage model separately, validate typed Choice answers and
      preserve probabilities/model provenance; unclear decisions escalate.
- [x] Share client pacing, timeout, bounded API retries, and provider-cost
      logging; retain explicit safety priority floors and remove current-path
      category regex overrides.
- [x] Verify the API contract and graph/evaluator behavior offline; one live
      Jev request succeeded using the configured OpenRouter key.
- [x] Document configured-model 50-case Jev/RAG attempts: TASK-41 measured
      45/50 correct categories; three workflow failures prevent clean acceptance.
- [ ] Calibrate urgency and establish comparative accuracy/speed; historical
      generative measurements do not prove an improvement.

### TASK-37 - Incremental PDF ingestion and bounded hybrid RAG
- [x] Store seven actual local simulation PDFs and hash-pinned provenance in
      `knowledgebase/`; retain review-required and real-delivery boundaries.
- [x] Add one CLI for paragraph-aware chunking, dense MiniLM vectors in Chroma,
      sparse BM25 vectors and ledger in SQLite, and RRF retrieval.
  - [x] Filename + first-150-word hashes identify immutable PDFs; skip completed documents,
      exclude deleted/failed versions, and query only committed generations.
- [x] Wire bounded allowlisted search, evidence review and cited drafts after
      Jev triage; require retrieved PDF evidence for exact FAQ simulations.
- [x] Run offline regressions, index/reindex the seven PDFs, and verify one
      configured-model fake-delivery case; document the observed review failure.
- [x] Document all 50 TASK-41 attempts, including latency/cost and failures.
- [ ] Obtain a fully scored current-stack 50-case report and validate all 200
      cases; citation validity alone does not establish answer correctness.
- [ ] Measure larger-corpus retrieval; no 1,000-document performance claim yet.


### TASK-38 - Jev supervisor Decisions
- [x] Replace generated checklist review with typed Jev choices and fixed feedback.
- [x] Preserve exact FAQ validation, safety gates, logging and bounded retries.
- [x] Verify offline regressions and measure nine labeled development reviews;
      three false rejections remain open (FM-022).
- [x] Complete all 50 attempted cases and document the saved report, including
      seven false escalations and two unscored workflow failures. The harness
      refused publication to the accepted tracker; accuracy issues remain open.


### TASK-39 - Reviewed simulation reference provenance and CLI review details
- [x] Review and repin the expanded PDFs without overwriting user documents;
      use a distinct reference version and preserve send restrictions.
- [x] Reindex seven documents, confirm subsequent ingestion skips them, and
      inspect populated metadata in a real local hybrid query.
- [x] Display structured supervisor reasons, decisions/probabilities, checklist
      score and workflow errors in both single-ticket commands.

### TASK-40 - Shared evidence-bound safety decisions
- [x] Collect simultaneous findings and ticket-specific required evidence.
- [x] Require explicit simulation approval scope and validate final exact text.
- [x] Add separate hash-pinned simulation reply PDFs; preserve references.
- [x] Run network-free safety, graph, worker and RAG regressions.
- [x] Complete and assess all 50 attempted cases; report one unscored workflow failure and three false escalations (FM-026/027).
- [ ] Meet local acceptance: zero critical false approvals and supported informational controls remain eligible.

### TASK-41 - Shared versioned business policy
- [x] Validate one simulation policy source; remove duplicated checker windows/prose.
- [x] Return policy provenance and independent mandatory human-review status.
- [x] Export immutable reference PDFs, merge manifests, propagate indexed provenance.
- [x] Block mismatched/missing policy evidence; exclude obsolete drafting references.
- [x] Record business policy in reports and checkpoint compatibility.
- [x] Finish offline verification (317 tests) and all 50 fake-only benchmark attempts; three operational failures remain open.
- [x] Accept the tested consistency contract; document two false escalations and three unscored failures without claiming overall accuracy acceptance.
- [ ] Resolve workflow/retrieval failures and meet broader accuracy and latency gates.


### TASK-42 - Align documentation and consolidate run commands
- [x] Read all 19 project-owned Markdown files and compare current claims with
      implementation, configuration, command parsers and saved measurements.
- [x] Consolidate setup, knowledge, graph/evaluation, Zoho, dashboard and optional
      worker commands in README; preserve historical records and delivery gates.
- [x] Correct policy/corpus counts, exporter behavior, measurement provenance,
      encoding and duplicate failure identifiers; check links and final diff.
- [x] Documentation only; no new live evaluation, deployment or email send.
