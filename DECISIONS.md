# DECISIONS.md — Architecture Decision Log

Every non-trivial choice gets one entry here, the moment it's made — not
retroactively. This is what stops a coding agent (or you) from re-deciding the
same thing differently in session 8 than it was decided in session 2.

Format for each entry:

```
## [YYYY-MM-DD] Short title of the decision
**Decision:** what was chosen
**Alternatives considered:** what else was on the table
**Reasoning:** why this one
**Status:** active / superseded by [link to later entry]
```

---

## [example — delete once you have real entries] Retry cap for supervisor loop
**Decision:** cap retries at 3 attempts before failing loudly
**Alternatives considered:** unlimited retries with exponential backoff; single
retry only
**Reasoning:** 3 attempts caught ~90% of recoverable failures in early manual
testing; beyond that, cost per run rose faster than completion rate improved
**Status:** active
