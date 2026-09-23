# FAILURE_MODES.md — Real Failures Encountered

This is not a hypothetical list. Only add an entry once you've actually hit
the failure while building. This file is your answer, ready-made, when an
interviewer asks "tell me about a failure you ran into building this."

Format for each entry:

```
## FM-### — Short title

**Observed behavior:** what actually happened, concretely
**Root cause:** why it happened
**Fix:** what you changed
**Before → After:** the measurable difference (a number if you have one —
pull from PROGRESS.md's metrics tracker where relevant)
**Regression test:** where the test guarding against this lives (tests/)
```

Likely candidates to watch for, based on this project's architecture — delete
any you never actually hit, and don't pre-write ones you haven't:
- A tool timing out and leaving the graph in an inconsistent state
- The critic/supervisor accepting a response not actually backed by tool evidence
- A prompt-injection attempt (via a tool's mock data) changing agent behavior
- The retry loop hitting its cap in a case that should have succeeded sooner
- Async tool calls racing and returning results in an unexpected order

---

## FM-001 — [title]

**Observed behavior:**
**Root cause:**
**Fix:**
**Before → After:**
**Regression test:**
