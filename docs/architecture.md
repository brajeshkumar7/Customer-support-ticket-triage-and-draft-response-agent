# Implemented architecture

The local LangGraph workflow and the controlled Zoho worker are separate paths.
The graph can record a **simulated** reply through a fake sender; it cannot send
customer email. The worker is implemented but has not been deployed or checked
against live Zoho polling. Its `live` mode refuses startup.

## Local ticket graph

```mermaid
flowchart TD
    A[Ticket text and per-run ID] --> B[Recall historical Chroma summaries]
    B --> C[Classify category, urgency, and P1/P2/P3 priority]
    C --> D{Single supported informational FAQ intent?}
    D -->|Yes| E[Skip model extraction and fixture tools]
    D -->|No| F[Extract explicit order ID and stated reason]
    F --> G[Gather order, policy, and FAQ fixture results concurrently]
    E --> H[Deterministic informational approval decision]
    G --> H
    H --> I[Draft response: exact FAQ template or model draft for human review]
    I --> J[Supervisor: exact-text check or model checklist]
    J -->|FAIL with approval and retries remaining| K[Add feedback; at most three retries]
    K --> I
    J -->|Approved FAQ, PASS| L[Simulation-only sender]
    L -->|Confirmed simulated result| M[Remember compact summary in Chroma]
    M --> N[End: simulated sent]
    J -->|Blocked, failed, or cap reached| O[Explicit human escalation]
    L -->|Disabled or uncertain| O
    B -->|Node error| O
    C -->|Node error| O
    G -->|Node error| O
    O --> P[End: no public reply]
```

The short-term store records node outputs for one ticket run. Historical Chroma
summaries are untrusted context and never approval evidence. A covered FAQ
takes a fast path with an exact versioned template; other tickets use the
configured OpenRouter model and local fixture tools for a human-review draft.
The local graph does not execute model-generated code or dispatch tools into
Docker. Node, tool, and model events are written to JSONL; provider-reported
cost is recorded when available. `astream(..., stream_mode="updates")` exposes
completed node updates, not token-by-token output.

New complete 50- and 200-case evaluations use one fresh shared ephemeral
Chroma collection per batch and a fake sender. Older saved reports may have
unknown effective recall exposure. The single-ticket Zoho command fetches
an existing Email ticket but always runs the graph in draft-only mode.

## Controlled Zoho worker

```mermaid
flowchart TD
    A[Zoho modified Email tickets] --> B[Poll pages; inspect newest inbound thread]
    B --> C[PostgreSQL unique job: organization, ticket, inbound thread]
    C --> D{Deployment mode}
    D -->|off| X[No polling]
    D -->|shadow| E[Record decision; no Zoho write]
    D -->|test| F[Check exact ticket and requester allowlist, expiry, and kill switch]
    D -->|live| Y[Startup rejected]
    F --> G[Recheck ticket, channel, requester, status, and latest thread]
    G --> H{Owner-approved knowledge and one supported FAQ intent?}
    H -->|No| I[Human job; private note on allowed test ticket]
    H -->|Yes| J[Persist sending state and reply digest]
    J --> K[Zoho public reply using exact approved template]
    K -->|Confirmed thread ID| L[Persist sent thread ID]
    K -->|Uncertain outcome| M[Mark unknown; reconcile against Zoho]
    M -->|Unresolved| I
```

The worker does not call the graph, use Chroma as reply evidence, or send model
prose. The repository knowledge file is still `review_required`, so controlled
test sending requires an owner's review and matching hash before it can start.
Real customer release also requires authoritative business sources, reviewed
cases, shadow validation, and a separate decision.
