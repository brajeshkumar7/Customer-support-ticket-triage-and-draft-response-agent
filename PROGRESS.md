# PROGRESS.md — Session Log

One entry per coding session. This is the fastest way for a coding agent to get
back up to speed cold — read the last 2–3 entries before starting new work.

Also the home for real measured numbers as you get them (Section 5 of `PRD.md`
says *what* to measure; the actual results go here).

Format:

```
## [YYYY-MM-DD] Session N
**Worked on:** which TASK-## items
**Completed:** what actually got finished
**Blocked/open questions:** anything unresolved
**Metrics measured this session:** any new numbers for PRD Section 5
**Next session should start with:** the single most useful thing to say to
pick this back up cold
```

---

## Metrics tracker (update as you measure — mirrors PRD.md Section 5)

| Metric | Value | Date measured |
|---|---|---|
| Task completion rate | — | — |
| Mean retries-to-success | — | — |
| Failure rate after cap | — | — |
| p95 latency (sequential) | — | — |
| p95 latency (async) | — | — |
| Cost per successful run | — | — |
| Prompt-injection attempts / successes | — | — |

---

## Session log

## [2026-09-28] TASK-12 structured JSONL logging
**Worked on:** TASK-12
**Completed:** Added append-only JSONL events for each graph node, tool call,
LLM API attempt, and OpenRouter 429 response. Events include run IDs, bounded
inputs/outputs, latency, and provider-reported LLM cost when available;
credential-shaped fields are redacted. Added graph event-count coverage and
updated the 429 logging test.
**Blocked/open questions:** No live OpenRouter run was performed. The broader
suite has unrelated existing failures in Zoho sender/configuration tests;
task-focused graph and OpenRouter tests pass.
**Metrics measured this session:** 30 focused graph/OpenRouter tests passed;
full suite excluding one known configuration test: 52 passed, 6 failed on
Zoho sender URL/request expectations. No performance or cost metrics measured.
**Next session should start with:** TASK-13, while tracking/fixing the existing
Zoho test failures separately.

## [2026-09-28] TASK-13 local run-history dashboard
**Worked on:** TASK-13
**Completed:** Replaced the static placeholder with a read-only Next.js App
Router dashboard. It reads direct `.jsonl` files server-side, supports file
selection and case-insensitive run-ID filtering, skips invalid lines, and
shows event details and available status evidence. Added the Node stack and
trade-off to project docs.
**Verification:** `npm install`, `npm run lint`, and `npm run build` passed.
Started the local page and confirmed both actual log files render newest
first, legacy missing fields display as em dashes, input/output details expand,
run-ID filtering works, and unsafe filenames return 404. A temporary fixture
confirmed malformed and structurally invalid lines are counted; the fixture
was removed afterward.
**Metrics measured this session:** No agent evaluation metrics measured.
**Next session should start with:** TASK-14.

## [fill in date] Session 1
**Worked on:**
**Completed:**
**Blocked/open questions:**
**Metrics measured this session:**
**Next session should start with:**
