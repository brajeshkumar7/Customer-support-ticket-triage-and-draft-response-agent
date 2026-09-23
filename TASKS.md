# TASKS.md — Working Task List

Keep this file up to date as you go — it's what lets a coding agent (or you,
after a week away) know exactly where the project stands. Check items off in
place; don't delete completed items, so the history stays visible.

## Phase 0 — Setup
- [ ] TASK-01: Pick and write the concrete task in `PRD.md` Section 2
- [ ] TASK-02: Repo scaffold (folders, dependency manager, `.env.example`)
- [ ] TASK-02b: Sign up for a free OpenRouter API key (openrouter.ai, no
      credit card needed) and check openrouter.ai/models?max_price=0 for
      currently-live `:free` models to put in OPENROUTER_MODELS; if going
      fully local instead, install Ollama and pull a small model (e.g.
      `llama3.1:8b` or a quantized variant that fits your hardware)
- [ ] TASK-03: Docker sandbox base image for tool execution (Docker Personal — free)
- [x] TASK-04: Pick memory backend (in-memory short-term + local Chroma long-term), record choice in `DECISIONS.md`, update `AGENTS.md` tech stack
- [x] TASK-04b: Add API-level OpenRouter model fallbacks and bounded, logged 429 retries

## Phase 1 — Core Agent Loop
- [x] TASK-05: Basic LangGraph state machine, no tools or retries yet
- [x] TASK-06: Add persistent short-term state across steps
- [x] TASK-07: Convert tool dispatch to async (`asyncio`) for independent calls
      (automated tests pass; manual run pending external network access)
      (automated tests pass; live manual run pending external network access)
- [x] TASK-08: Add long-term memory store, wire read/write into graph

## Phase 2 — Safety & Recovery
- [x] TASK-09: Supervisor/critic node with checklist-based evaluation
- [x] TASK-10: Retry-with-feedback loop, capped at 3 retries after the initial
      draft
- [x] TASK-11: Explicit terminal outcome: send approved replies through an
      opt-in Zoho Desk adapter or create a complete human escalation; automated
      tests pass without live Zoho Desk requests

## Phase 3 — Observability
- [ ] TASK-12: Structured logging: tool call, input/output, latency, token cost
- [ ] TASK-13: Minimal dashboard reading the JSON log
- [ ] TASK-14: Streaming output of intermediate steps to the caller

## Phase 4 — Security
- [ ] TASK-15: Build a small prompt-injection test set (5–10 attempts)
- [ ] TASK-16: Run tests, document what got through in `PRD.md` Section 5
- [ ] TASK-17: Patch any successful injections, re-test, log the fix

## Phase 5 — Evaluation & Metrics
- [ ] TASK-18: Build a fixed test set of 20–30 synthetic support tickets covering
      all categories (order status, returns, damage, billing, general) plus
      deliberate edge cases that SHOULD trigger escalation (ambiguous intent,
      policy conflict, angry/high-stakes customer) — the escalation-accuracy
      cases matter as much as the resolvable ones
- [ ] TASK-19: Run full eval, record: auto-resolution rate, escalation accuracy
      (did it escalate exactly the tickets that needed a human, no more/less),
      retries, latency, cost in `PROGRESS.md`
- [ ] TASK-20: Run sequential vs. async latency comparison, record the delta

## Phase 6 — Ship
- [ ] TASK-21: Architecture diagram
- [ ] TASK-22: README with metrics table + 2–3 documented failure modes
- [ ] TASK-23: Fill in `PRD.md` Section 7 (Explicit Trade-off) with a real one

## Parking Lot (ideas NOT in current scope — do not build yet)
*(Move an item here instead of building it mid-task if it's outside PRD scope.
Revisit only after Phase 6 is done.)*

- Production-readiness follow-ups are tracked in `PRODUCTION_READINESS.md`,
  including per-ticket memory lifecycle and workflow-driven graph expansion.
