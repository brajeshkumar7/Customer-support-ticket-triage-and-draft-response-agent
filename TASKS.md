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
- [ ] TASK-04: Pick memory backend (self-hosted Redis + Chroma — free), record choice in `DECISIONS.md`, update `AGENTS.md` tech stack
- [ ] TASK-04b: Add 429/rate-limit handling to the retry logic before real eval runs, to protect free-tier quota

## Phase 1 — Core Agent Loop
- [ ] TASK-05: Basic LangGraph state machine, single tool, no retries yet
- [ ] TASK-06: Add persistent short-term state across steps
- [ ] TASK-07: Convert tool dispatch to async (`asyncio`) for independent calls
- [ ] TASK-08: Add long-term memory store, wire read/write into graph

## Phase 2 — Safety & Recovery
- [ ] TASK-09: Supervisor/critic node with checklist-based evaluation
- [ ] TASK-10: Retry-with-feedback loop, capped at N (define N, log why in `DECISIONS.md`)
- [ ] TASK-11: Loud failure path when retry cap is hit (no silent failures)

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

-
