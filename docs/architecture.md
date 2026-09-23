# Architecture Diagram

TASK-21 in TASKS.md. Update this as the real graph evolves — this is the
intended shape going in, not a promise it won't change (if it changes, log
why in DECISIONS.md).

```
                  Support Ticket
                        │
                        ▼
                ┌───────────────┐
                │ Classification │  category, urgency
                └───────┬────────┘
                        ▼
                ┌───────────────┐
                │  Tool Dispatch │  async, concurrent (PRD Section 4)
                └───────┬────────┘
             ┌──────────┼──────────┐
             ▼          ▼          ▼
        Order Tool  Policy Tool  FAQ Tool
             │          │          │
             └──────────┼──────────┘
                        ▼
                ┌───────────────┐
                │  Draft Response│
                └───────┬────────┘
                        ▼
                ┌───────────────┐
                │ Supervisor/    │
                │ Critic         │
                └───────┬────────┘
                        │
                ┌───────┴────────┐
              PASS              FAIL (retry, capped at N)
                │                │
                ▼                └──> back to Draft Response w/ feedback
        Confidence Gate
         /            \
        /              \
  AUTO-SEND         ESCALATE
                     to human, with reasoning attached
```

Every box logs its call, input/output, latency, and cost (PRD Section 6).
Tool execution happens inside the Docker sandbox boundary — no direct host
filesystem/network access from tool code.
