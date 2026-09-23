# PRD — Multi-Agent System with Runtime Safety

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
- Tool use sandboxed so a bad model output can't touch the real filesystem/network
- A supervisor/critic step that catches failures and retries with a cap

**Chosen task:** Customer support ticket triage and draft-response agent for an
e-commerce context. Given an incoming support ticket (order status, return
request, damaged item, billing dispute, general question), the agent:
1. Classifies category and urgency
2. Uses 2–3 tools to gather facts: order-lookup (mock API), return/refund policy
   checker, FAQ/docs search
3. Drafts a resolution response grounded in what the tools returned
4. Auto-sends only above a defined confidence threshold; otherwise escalates to
   a human with its reasoning attached — this escalation behavior is the core
   "predictable failure" mechanic from Section 1, made concrete

## 3. Non-Goals
- Not building a general-purpose agent framework — pick one real, narrow task
- Not optimizing for maximum autonomy — optimize for *predictable* failure

## 4. Architecture
- **Orchestration:** LangGraph (or an equivalent graph/state-machine framework) —
  chosen specifically because it models cycles and state explicitly, unlike a
  simple prompt-chaining script
- **Tool execution:** sandboxed in Docker containers, no direct host
  filesystem/network access; independent tool calls run concurrently via async
  Python (`asyncio`) rather than sequentially — this is a real latency win, not
  just a style choice, and worth measuring (Section 5)
- **Memory:** short-term (working state per run) + long-term (a simple vector or
  key-value store for facts learned across runs)
- **Supervisor loop:** a critic step evaluates the worker's output against a
  checklist; on failure, retries with feedback injected into the next attempt,
  capped at N retries before failing loudly (not silently)
- **Streaming:** stream the agent's intermediate steps/tokens to the caller
  rather than returning only a final blob
- **Adversarial input handling:** treat any tool output (web results, file
  contents, user-provided text) as untrusted; test the agent against a small set
  of prompt-injection attempts (e.g., a scraped webpage containing "ignore
  previous instructions...") and document what got through vs. what the
  sandboxing/system-prompt boundaries caught

## 5. Success Metrics (write these down, they're your resume bullets)
- [ ] Task completion rate across a fixed test set of ~20–30 scenarios
- [ ] Mean retries-to-success and failure rate after cap
- [ ] p95 latency per full run — sequential vs. async tool calls
- [ ] Cost per successful run (token cost from logs)
- [ ] Prompt-injection test results: attempts, successes, fixes applied

*(Fill each in with a real number in `PROGRESS.md` as you measure it — this
section states what to measure, `PROGRESS.md` holds the actual results.)*

## 6. Observability Requirements
- Log every tool call, its input/output, latency, and token cost
- A simple dashboard (even a static HTML page reading a JSON log) showing run history

## 7. Explicit Trade-off to Document
[Fill this in once you hit a real one. Likely candidate: more retries improves
completion rate but increases cost/latency — state the number where you drew
the line and why.]

## 8. Deliverables
- [ ] Public repo with architecture diagram in the README
- [ ] README documenting 2–3 real failure modes encountered and how they were fixed
- [ ] Metrics table (from Section 5) in the README, not just claimed in prose
