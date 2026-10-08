# Support agent engineering evidence

This project demonstrates a stateful support workflow with explicit limits on
model authority. Its latest fully scored standalone run matched 47 of 50
author-labeled synthetic reply or escalation decisions. Four tickets received
simulated informational replies; 46 went to human review. Real customer
automation remains disabled.

The engineering claim is inspectable failure handling and measured decision
quality. Customer time savings, production reliability, and broad automatic
resolution have not been established.

## Results with a meaningful denominator

Source: [TASK-43 saved measurement](measurements/task43_regression.json),
measured October 7, 2026. The [offline audit](measurements/proof_audit.json)
recomputes these results and checks the owner's raw report against its recorded
hash, the original metric calculator, and correlated execution logs.

| Expected decision | Simulated reply | Human escalation |
| --- | ---: | ---: |
| Informational reply eligible | 4 | 3 |
| Human review required | 0 | 43 |

| Question | Evidence |
| --- | --- |
| Did the agent choose the labeled disposition? | 47/50, or 94% |
| What would always escalating achieve? | 43/50, or 86%; analytical baseline on the same labels |
| What did the agent add over that baseline? | Four correct simulated replies; eight percentage points in disposition match |
| How much was automated? | 4/50, or 8% simulated coverage |
| How many eligible replies were captured? | 4/7, or approximately 57.1% |
| Were required escalations missed? | 0/43 in this sample |
| Was category classification correct? | 46/50, or 92%; separate from disposition |
| How long did runs take? | Full-run p95 approximately 52.15 seconds |
| What model cost was recorded? | Total provider-reported token cost 0.245525665; all 277 calls had costs |

The baseline is calculated from existing labels, not a separate model run.
Zero false simulated sends in this small development set is not an estimate of
zero production risk. Correct escalation counts as a correct disposition;
94% is not an automatic-resolution rate. The current 95% disposition target
was missed.

## Three saved executions to inspect

These are replayable records from the same evaluation, not invented examples
or a newly recorded live demo. The audit exports only case IDs, decisions and
node names; it excludes ticket bodies, generated drafts and customer addresses.
Their complete run IDs and observed node sequences are in `selected_traces`
inside [the audit JSON](measurements/proof_audit.json).

| Case | Recorded behavior | What it demonstrates |
| --- | --- | --- |
| `general_01` | `supported_faq`, safety allowed, supervisor PASS, simulated send, then remember | An eligible exact informational reply reaches the simulated sender and memory write path |
| `billing_01` | Supervisor PASS, safety blocked, escalation; no send node | Model approval does not override application authorization |
| `general_03` | Expected informational reply; `rag_approval_evidence_missing`; escalation | A real false rejection remains visible, rather than being relabeled as success |

The third trace establishes a missing qualifying evidence result at the gate;
it does not prove the reply PDF was absent from disk. See
[the recorded retrieval failures](../FAILURE_MODES.md#fm-027---eligible-simulation-replies-rejected-during-task-40-rag-evaluation).

## How to reproduce the checks

From the repository root, public verification needs only Python's standard
library. It reads the committed case summary, derives the confusion matrix,
checks recorded match flags, and recomputes disposition, cost and latency:

```powershell
python docs/verify_evidence.py
```

Owner verification additionally requires the existing local `.venv`, ignored
raw TASK-43 report and `data/logs/events.jsonl`. It checks the raw report hash,
every exported case field, harness metrics, per-run model-call counts and
costs, and each run's terminal node. It makes no model or Zoho requests:

```powershell
.\.venv\Scripts\python.exe docs/verify_evidence.py --private
```

Fresh implementation verification uses the existing suite and a new writable
temporary directory. Model and Zoho transports are test doubles; Chroma tests
need their local embedding dependency available. JUnit files can contain
machine paths or failure details, so retain them locally:

On October 9, 2026 (Asia/Calcutta), the unchanged suite passed **328 tests**.
The first restricted attempt hit a Windows temporary-directory access error;
the successful rerun used normal filesystem access. Both attempts are recorded
in [FM-030](../FAILURE_MODES.md#fm-030--evidence-audit-test-run-could-not-access-temporary-directories).

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --basetemp=.tmp/evidence-rerun --junitxml=.tmp/evidence-rerun.xml
.\.venv\Scripts\python.exe docs/verify_evidence.py --private --junit .tmp/evidence-rerun.xml --output .tmp/evidence-rerun.json
```

Use a new output filename for each audit; the utility refuses to overwrite
existing evidence. The committed [audit](measurements/proof_audit.json)
includes the fresh test counts and hashes of the implementation, tests,
datasets and knowledge files present at verification. Hashes establish byte
consistency, not independent authenticity or a signed release. Public readers
can reproduce the public arithmetic; verifying the private log provenance
requires access to the owner's local records.

## What the tests and measurements establish

| Claim | Where to inspect it | Boundary of the evidence |
| --- | --- | --- |
| Customer facts cannot be authorized by fixture data | [Authorization tests](../tests/test_safety_authorization.py), [graph tests](../tests/test_agent_graph.py) | Fixed tested cases, not proof against every phrasing |
| Retrieved text must have valid provenance and citations | [PDF tests](../tests/test_pdf_rag.py), [business policy tests](../tests/test_business_policy.py) | Citation validity does not prove semantic correctness |
| Supervisor decisions and retries have explicit contracts | [Supervisor tests](../tests/test_supervisor.py), [Jev tests](../tests/test_jev_triage.py) | Passing parser tests does not calibrate model probabilities |
| Controlled worker handles duplicate and uncertain sends | [Worker tests](../tests/test_production_worker.py) | Fake services; worker remains undeployed |
| Manual Zoho integration has been exercised | [Owner observation record](zoho_manual_validation.md) | Controlled manual observations, excluded from synthetic metrics |
| Latency comparison failures are retained | [TASK-20 diagnostic](task20_comparison.md) | Later experiment had operational failures; no accepted async speedup |

The historical injection retest and older 200-case result remain separate
measurements of earlier configurations. Neither becomes current-stack
validation through this audit. Fresh offline tests strengthen regression
evidence without adding new model-accuracy observations.

## Interview walkthrough

1. Open the confusion matrix and explain why escalation can be correct.
   State both the 94% match rate and 8% simulated automation coverage.
2. Show `billing_01`: the supervisor passed, but the deterministic gate kept
   the run out of `send_response`. Connect this to the
   [historical unsafe-send failure](../FAILURE_MODES.md#fm-020---supervisor-pass-authorized-unsafe-simulated-deliveries).
3. Show `general_01`: exact approved content, qualifying PDF evidence and
   final validation permit a simulated reply. Explain why this does not
   authorize real customer sending.
4. Show `general_03` and the later failed latency comparison. Explain what
   remains unresolved and avoid claiming the clean standalone run fixed it.
5. Run the public verifier. Show the fresh test result and source hashes in
   the audit, then distinguish mocked integration checks from live operation.

## Resume wording supported by this evidence

- Built a LangGraph support-ticket agent with hybrid PDF retrieval, structured
  model review and deterministic reply gates; measured 94% reply/escalation
  agreement on 50 author-labeled synthetic cases, with zero false simulated
  sends and 8% simulated reply coverage.
- Implemented bounded retries, evidence provenance checks and structured
  execution logging; verified a saved evaluation against 856 correlated
  events and 277 model calls using a reproducible offline audit.

Do not present this as production deployment, 94% automatic resolution,
independently validated safety, measured customer savings, or proven async
speedup. Docker execution isolation is not implemented.

## Evidence still needed

The next acceptance work is already tracked in [TASKS.md](../TASKS.md):
current-stack 200-case regression, independent case review, urgency and
supervisor calibration, complete latency comparison, and controlled worker
intake/restart/reconciliation validation. Authoritative business providers,
requester verification and a separate release decision remain prerequisites
for real customer automation.
