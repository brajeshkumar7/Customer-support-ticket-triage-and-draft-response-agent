# Production-readiness follow-ups

This file tracks improvements to revisit as the project approaches its final
production-style portfolio state. These notes do not expand the acceptance
criteria of the current TASKS.md item. Implement them only when they fit the
active task and the PRD; otherwise keep them deferred until the relevant later
phase.

## Deferred follow-ups

### Reuse the compiled graph while keeping memory per ticket

**Current state:** `build_graph` receives a `ShortTermMemory` instance and
closes over it. The caller therefore creates a graph and a memory instance for
each ticket run.

**Follow-up:** Consider compiling the graph once and supplying a distinct,
ticket-scoped memory object through each invocation's runtime context or an
equivalent LangGraph-supported mechanism. Keep ticket data isolated, make the
memory queryable for the lifetime needed by observability/debugging, and define
when per-run memory is released.

**Verification:** Exercise simultaneous runs for different ticket IDs and
confirm neither run can read or overwrite the other's state. Confirm a caller
can inspect a run's stored values after completion.

**Status:** Deferred; revisit during production-readiness review.

### Grow graph topology from workflow responsibilities

**Current state:** The graph has `classify` and `respond` nodes as the TASK-05
vertical slice. It does not yet gather verified facts or review/route drafts.

**Follow-up:** Add clearly named nodes only as needed to implement the PRD
workflow: ticket intake/validation, classification, fact gathering using the
specified tools, grounded response drafting, and review/decision routing for
resolution versus human escalation. Integrate the existing roadmap work for
async tool dispatch and the supervisor/retry/failure path rather than
duplicating it.

Do not use a numeric environment variable to set the number of graph nodes.
Node count follows explicit workflow responsibilities; nodes may be
deterministic steps, tool dispatch, or focused LLM roles. Keep the graph within
the support-ticket scope in the PRD.

**Verification:** Tests should cover the actual routing paths, grounded drafts,
escalation, and bounded failure behavior as those capabilities are added.

**Status:** Deferred; evolve the graph in the relevant TASKS.md phases.

## Recording future follow-ups

For each implementation step, record production-readiness considerations here
when the step reveals a relevant improvement. State whether each item is
implemented now or deferred, and link it to its related TASKS.md phase where
possible. If no relevant follow-up exists, do not add filler.
