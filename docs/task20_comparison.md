# TASK-20 dispatch comparison attempt

Started 2026-10-07 and finished 2026-10-08 (Asia/Calcutta). Both modes attempted all 50 development cases, sequential first, with configured models, separate shared ephemeral Chroma and fake delivery only. No Zoho call or email.

**Status: diagnostic; TASK-20 remains open.** The two batches did not each produce 50 scored results. No accepted async reduction is computed, and the previous accepted tracker remains unchanged.

[Shareable measurement](measurements/task20_dispatch_20261008.json) contains exact report-derived figures and body-free case outcomes. Raw local report: `data\eval_reports\task20_20261007T182019Z_3d6bdad5.json`.

| Metric | Sequential | Concurrent |
| --- | --- | --- |
| Attempted | 50 | 50 |
| Scored | 32 | 49 |
| Matched | 31 | 47 |
| Operational failures | 18 | 1 |
| False simulated sends | 0 | 0 |
| False escalations (scored cases) | 1 | 2 |
| Simulated replies | 2 | 4 |
| Full-run p95: scored subset only (ms) | 51568.66219999938 | 52613.4406000001 |
| Observed dispatch p95 (ms) | 7.951 | 5.919 |
| Observed gather_facts p95 (ms) | 35909.156 | 33790.803 |
| Dispatch count | 29 | 43 |
| Successful gather_facts bypass count | 3 | 6 |
| Model calls | 209 | 276 |
| Provider-reported cost subtotal | 0.170256754 | 0.240768267 |
| Tickets with missing provider cost | 17 | 0 |

## Interpretation

Sequential failures: order_04 gather_facts ValueError; billing_05 gather_facts APITimeoutError; 16 classify APIConnectionError failures. Concurrent failure: general_08 respond ValueError. Missing provider costs remain unknown; the reported subtotal is not a complete bill.

The full-run p95 values apply to different scored subsets (32 versus 49), not two successful 50-case batches. Dispatch and gather_facts samples also differ, and informational tickets bypass fixture dispatch. Do not calculate a speedup from these figures or present them as production performance. Model variation, pacing, cache effects and the observed transport failures confound interpretation.

Scored false escalations: sequential general_08; concurrent general_03 and general_04. The remaining unscored cases are operational failures, not correctly handled gold-label outcomes. No rule, label, provider or artificial delay was changed to improve the measurement.

The original checkpoint defect (FM-029) was fixed offline before this newly authorized attempt. This attempt preserved all 100 completed rows; it was not automatically restarted. Default graph dispatch remains concurrent. The next accepted measurement still requires a separately initiated fully scored pair; accuracy, retrieval and provider reliability findings remain open.

Offline recomputation:

```powershell
python -m src.eval.compare_tool_dispatch --report data/eval_reports/task20_20261007T182019Z_3d6bdad5.json
```

This command makes no external calls and returns a nonzero status for the diagnostic.
