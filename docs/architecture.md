# Implemented architecture

The local graph, interactive Zoho runner and controlled worker are separate
paths. Real customer auto-send is disabled. The worker is implemented but
undeployed; its `live` mode refuses startup.

## Local graph

```mermaid
flowchart TD
    START([START: ticket text and internal run ID]) --> recall["recall: Chroma history when enabled"]
    recall -->|No workflow error| classify["classify: Jev category and urgency; derive priority"]
    recall -->|Workflow error| escalate["escalate: complete human-review payload"]
    classify -->|Clear category; no workflow error| gather_facts["gather_facts: optional hybrid RAG; conditional extraction and fixture tools"]
    classify -->|Unclear category or workflow error| escalate
    gather_facts -->|No workflow error| safety_review["safety_review: deterministic approval and policy-evidence checks"]
    gather_facts -->|Workflow error| escalate
    safety_review -->|No workflow error; allowed or blocked| respond["respond: exact approved reply or human-review draft"]
    safety_review -->|Workflow error| escalate
    respond -->|No workflow error| supervisor["supervisor: local template validation or Jev checklist"]
    respond -->|Workflow error| escalate
    supervisor -->|PASS and safety allowed| send_response["send_response: final validation; simulation-only delivery"]
    supervisor -->|Non-PASS; safety allowed; fewer than 3 retries| prepare_retry["prepare_retry: increment count and inject feedback"]
    supervisor -->|Safety blocked, workflow error or retry cap reached| escalate
    prepare_retry -->|No workflow error| respond
    prepare_retry -->|Workflow error| escalate
    send_response -->|Confirmed simulation; no workflow error| remember["remember: write compact summary when enabled"]
    send_response -->|Disabled, failed, unconfirmed or workflow error| escalate
    remember --> END([END])
    escalate --> END
```

Node names and routing above match `build_graph` in
[`src/agent/graph.py`](../src/agent/graph.py), reviewed 2026-10-08.
Each retry repeats only `respond` and `supervisor`, with at most three retries
after the initial draft. A blocked safety decision still proceeds through
drafting and review, then escalates even if the supervisor passes.

`gather_facts` first runs bounded hybrid PDF retrieval/evidence review when RAG
is enabled. Supported informational intents then skip order extraction and
the three fixture tools. Other intents extract an explicit order ID/reason
and dispatch order lookup, shared-policy checks and FAQ search concurrently
by default. TASK-20's comparison runner alone selects sequential dispatch;
both modes retain individual tool failures as unavailable results. These are
operations inside `gather_facts`, not additional graph nodes.

Guarded processing errors follow the shown escalation routes. Chroma query/
write failures are caught inside the memory nodes and reported in state;
they do not normally abort the workflow. `remember` and `escalate` have direct
edges to END. Successful simulated delivery has already set terminal status
`sent` before remembering; escalation sets `escalated`. Sending disabled,
missing configuration, invalid final text or unconfirmed delivery routes to
escalation. No real Zoho sender can deliver from this local graph.

Escalation includes ticket, tool results,
failed drafts with feedback and a human-readable reason; it does not assign a
Zoho human by itself.

### Models, tools and evidence

With RAG enabled every ticket uses Jev category/urgency Choices through
OpenRouter Decisions. Generative chat calls perform evidence review, explicit
ticket-detail extraction when needed, and cited human drafts. Generated drafts
receive one Jev Decisions request with three checklist questions. Each must
select `pass` with probability at least 0.90; uncertainty/malformed responses
are non-approval. This provisional threshold is not calibrated. Fixed reasons
provide feedback, not sentence-level unsupported-claim identification.
Exact approved FAQ templates are checked locally without a supervisor API call.
The checklist completion score is separate from Jev probabilities.

Only fixed application-owned tools run; no model-generated code or shell
commands execute. Docker is an unused placeholder, not a security boundary.
The order fixture is fictional. The validated
[shared business policy](../data/policies/support_v1.json) supplies eligibility
rules and generated PDF text. Policy results require matching active retrieved
ID/version/hash/rule metadata; obsolete policy references are filtered.
Business-policy provenance is separate from send policy `informational_only_v4`.

[The 13-PDF corpus](../knowledgebase/README.md) uses dense MiniLM Chroma and
sparse BM25 SQLite, fused by RRF. The search agent may use at most three
allowlisted searches per gather step. Citation validity is not proof of
entailment, requester identity or authority. Informational simulation approval
requires scoped, hash-pinned evidence and exact versioned reply text.
Unreviewed/reference-only PDFs cannot authorize sending.

Short-term state is per run. Ordinary sample and Zoho runs use persistent
Chroma; single synthetic runs use fresh ephemeral memory. Complete 50/200-case
batches share fresh ephemeral historical memory; persistent history is untouched.
Only confirmed successful simulations are remembered. Recall never verifies
current business facts and is excluded from approval/supervisor factual evidence.

Node/tool/model events go to JSONL. Local logs may contain bodies/drafts;
worker logs omit them. LangGraph async update streaming emits completed node
updates, not token streams. See [commands](../README.md).

## Interactive Zoho runner

`run_zoho` fetches an existing ticket's subject/description, runs the graph with
delivery disabled, and prints the draft and findings. Usable ticket text can
be analyzed across channels. `--send-reviewed` is a separate, controlled human
send: review exact text and confirm requester/ticket; PASS proposes the draft,
otherwise a fixed acknowledgement is proposed. Ticket changes block sending;
an uncertain send is never automatically repeated. This path is not polling,
latest-thread ingestion or unattended customer support.

## Separate controlled worker

```mermaid
flowchart TD
    A{Startup mode} -->|off| O[Wait; no polling]
    A -->|live| L[Reject startup]
    A -->|shadow or test| B[Poll Zoho changed Email tickets and latest inbound thread]
    B --> C[PostgreSQL unique organization-ticket-thread job]
    C --> D[Informational decision with approved local knowledge]
    D -->|shadow| SH[Record only; no Zoho write]
    D -->|test| E[Exact allowlist, expiry, owner-approved hash and kill switch]
    E --> F[Refetch ticket and check requester, channel, status and latest thread]
    F -->|Blocked| H[Human job; private note for allowed test ticket]
    F -->|Eligible| G[Persist sending state and digest; one public template reply]
    G -->|Confirmed thread ID| S[Persist sent record]
    G -->|Uncertain or restart during send| U[Unknown; reconcile without resending]
    U -->|Unresolved| H
```

The worker does not call the graph, draft model prose or use Chroma approval
evidence. Repository knowledge is still `review_required`; owner approval is
an additional requirement. Paid Render/PostgreSQL are selected but not deployed.
Polling/restart/reconciliation need controlled integration validation. Real
release additionally requires authoritative sources, identity verification,
independently reviewed tickets and a separate live decision. See
[deployment prerequisites](controlled_render.md).
