# Changed Files Log & Traceability Matrix

**Document Version:** 1.0.0  
**Status:** Canonical Audit Log  
**Scope:** Signal Atlas Reliability Closure Task

---

## 1. Traceability Matrix: Code & Test Files Modified

| File Path | Type | Rationale / Defect Addressed | Verification Test(s) |
|---|---|---|---|
| `src/signal_atlas/universe/provenance.py` | Source Fix | Reverted global file caching (`data/.raw_manifest_cache.json`) in `compute_raw_data_manifest()`. Provenance manifests now hash live database table rows, ensuring mutations in underlying tables are detected deterministically. | `tests/unit/test_exact_provenance.py` (all 15 parameterized table tests pass) |
| `src/signal_atlas/universe/service.py` | Source Fix | Removed public `raw_manifest` argument from `build_universe()`. Prevents caller injection of forged manifest payloads and enforces strict internal generation. | `tests/unit/test_exact_provenance.py::test_public_build_rejects_an_injected_manifest` |
| `src/signal_atlas/research/service.py` | Source Fix | Resolved `UnboundLocalError: active_inst_ids` in `screen_candidates` by properly binding `active_inst_ids` query execution under `if symbols:` and `elif scan_all:`. | `tests/integration/test_mcp_flow.py::test_end_to_end_mcp_research_flow` |
| `src/signal_atlas/backtest/robustness.py` | Source Enhancement | Added `run_matched_random_control()` implementing the Stage 3 apples-to-apples matched random entry benchmark (shared calendar dates, PIT universe, 1.5 ATR / 2.0 R:R geometry, sizing, costs, deterministic seed). | `tests/unit/test_random_benchmark_matched.py` |
| `tests/unit/test_accounting_definitions.py` | New Test | Added 4 deterministic unit tests verifying: unweighted mean R vs portfolio payoff ratio divergence, near-zero risk denominator protection, explicit equity-at-entry denominators, and unrounded R precision. | `tests/unit/test_accounting_definitions.py` (4/4 pass) |
| `tests/unit/test_random_benchmark_matched.py` | New Test | Added unit tests verifying deterministic seed repeatability and controlled mock dataset execution for the matched random benchmark. | `tests/unit/test_random_benchmark_matched.py` (2/2 pass) |
| `tests/fixtures/sample_trades_ohlcv.json` | New Fixture | Offline read-only sample of trade bars from `reports/v2_baseline_trades.csv` validating: ordinary exit (ZOMATO), target hit (ADANIPOWER), stop loss (DRREDDY), and gap-through-stop (ONGC). | Manual audit & schema assertion |
| `scripts/run_attribution_steps.py` | Script Fix | Corrected v1 win rate transcription typo from 52.45% to canonical 46.51% (matching `dev_report.md` Section 1.1 and `registry.csv` Trial 1). | `scripts/run_attribution_steps.py` |
| `reports/dev_report_v2.md` | Report Fix | Corrected Step 0 win rate (46.51%), Fold 4 trade count (23 trades), Fold 1 count (17 trades), added fold reset semantics note, corrected Candidate 3 and 5 rejection reasons, and corrected cost stress wording (2.5x slippage). | Markdown integrity review |
| Repository Files (15 files) | Whitespace Hygiene | Stripped trailing whitespaces and normalized newline formatting across all modified files. | `git diff --check` (exits 0 with no warnings) |

---

## 2. Reliability Closure Deliverables Generated

The following 10 comprehensive reports and matrices were generated under `reports/reliability_closure/`:

1. `reliability_closure_inventory.md` — Baseline repository state, pre-existing changes, and task plan.
2. `run_provenance_matrix.csv` — Full run provenance matrix with explicit confidence levels and unknowns.
3. `report_integrity_audit.md` — Resolution of 84/117/283/387 contradictions, registry row count, and fold trade counts.
4. `accounting_and_risk_spec.md` — Mathematical definitions and formulas for R, P&L, risk denominators, and portfolio equity.
5. `benchmark_spec.md` — Specification of the matched random-entry control benchmark and resampling methodology.
6. `walkforward_and_killswitch_spec.md` — Formalization of fold reset semantics, killswitch state transitions, and root-cause analysis of post-Jan 2023 silence.
7. `pit_data_provenance_audit.md` — Cryptographic provenance audit, offline OHLCV execution checks, and universe coverage boundaries.
8. `test_results.md` — Test suite execution record, isolated test DB configuration, and failure resolutions.
9. `changed_files.md` — Traceability log of all modified and generated files.
10. `known_gaps_and_no_go_decision.md` — Comprehensive summary of remaining technical gaps and definitive **NO-GO** decision.
