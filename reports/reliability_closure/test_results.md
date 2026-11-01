# Test Results & Verification Record

**Document Version:** 1.0.0  
**Status:** Verification Record  
**Target Environment:** Isolated Test Environment (`signal_atlas_test`)

---

## 1. Environment & Configuration

| Parameter | Value | Audit Verification |
|---|---|---|
| **Operating System** | Windows 11 | Confirmed |
| **Python Version** | Python 3.13.5 | Confirmed |
| **Test Framework** | pytest 8.3.4 / pluggy 1.6.0 | Confirmed |
| **Active Git Branch** | `backtest-and-tuning` | Confirmed |
| **Commit Baseline** | `6e7ffac` | Confirmed |
| **Test Database Target** | `postgresql+psycopg2://postgres:***@localhost:5433/signal_atlas_test` | Redacted; ends in `_test` |
| **Production DB Access** | None | Verified zero connections / zero mutations to `signal_atlas` |
| **Holdout Dataset State**| Strictly Sealed | `HOLDOUT_UNLOCK` absent; holdout dates untouched |

---

## 2. Test Execution Summary

### 2.1 Unit Test Suite
- **Command:** `$env:DATABASE_URL="postgresql+psycopg2://postgres:***@localhost:5433/signal_atlas_test"; $env:TEST_DATABASE_URL="postgresql+psycopg2://postgres:***@localhost:5433/signal_atlas_test"; pytest tests\unit -v`
- **Result:** **146 PASSED / 146 TOTAL (100% GREEN)**
- **Duration:** 20.14 seconds

#### Key Unit Test Modules:
| Test Module | Tests | Status | Scope |
|---|---|---|---|
| `tests/unit/test_exact_provenance.py` | 15 | **PASSED (15/15)** | Full manifest determinism, table mutation detection across all 6 universe tables, and rejection of public manifest forgery |
| `tests/unit/test_accounting_definitions.py` | 4 | **PASSED (4/4)** | Divergence of unweighted R vs payoff ratio, micro-lot denominator protection, unrounded R precision, explicit denominators |
| `tests/unit/test_random_benchmark_matched.py` | 2 | **PASSED (2/2)** | Deterministic random seed, matched geometry control, error handling |
| `tests/unit/test_metrics_corrected.py` | 1 | **PASSED (1/1)** | Hand-verified 6-trade metrics, net profit factor, R profit factor, STCG tax |
| `tests/unit/test_drawdown_killswitch.py` | 2 | **PASSED (2/2)** | Synthetic 15% drawdown, cooldown decrement, true peak tracking |
| `tests/unit/test_engine_equivalence.py` | 1 | **PASSED (1/1)** | 500-pair engine equivalence |
| `tests/unit/test_database_safety.py` | 7 | **PASSED (7/7)** | Strict test DB URL isolation guards |
| Other Unit Tests (backtest, parser, etc.) | 114 | **PASSED (114/114)** | Ingestion, technical features, rules, sizing, downloaders |

---

### 2.2 Integration Test Suite Highlights
- **MCP Flow:** `tests/integration/test_mcp_flow.py::test_end_to_end_mcp_research_flow` $\to$ **PASSED** (Resolved `active_inst_ids` UnboundLocalError).
- **Point-in-Time Universe:** `tests/integration/test_point_in_time_universe.py` $\to$ Verified against PostgreSQL test instance on port 5433.
- **Repository Hygiene:** `git diff --check` $\to$ **0 warnings / 0 whitespace errors (Clean)**.

---

## 3. Resolution Table: 10 Review Bundle Failures

Every failure recorded in the review bundle's full-suite log has been systematically addressed:

| Item | Previous Failure | Cause | Current Status |
|---|---|---|---|
| 1 | `test_public_build_rejects_an_injected_manifest` | Public `build_universe` accepted `raw_manifest` | **PASSED** (Signature reverted to private computation) |
| 2 | `test_manifest_is_deterministic_and_hashes_raw_row_content` | Disk caching masked raw row mutations | **PASSED** (Caching removed; live DB hashing active) |
| 3 | `test_manifest_hashes_every_universe_input_table[Instrument]` | Disk caching masked mutation | **PASSED** |
| 4 | `test_manifest_hashes_every_universe_input_table[InstrumentSymbolHistory]` | Disk caching masked mutation | **PASSED** |
| 5 | `test_manifest_hashes_every_universe_input_table[TradingCalendar]` | Disk caching masked mutation | **PASSED** |
| 6 | `test_manifest_hashes_every_universe_input_table[DailyPriceQuarantine]` | Disk caching masked mutation | **PASSED** |
| 7 | `test_manifest_hashes_every_universe_input_table[IngestionRun]` | Disk caching masked mutation | **PASSED** |
| 8 | `test_manifest_hashes_every_universe_input_table[CorporateAction]` | Disk caching masked mutation | **PASSED** |
| 9 | `test_21_raw_data_manifest_and_code_revision_provenance` | Cached manifest prevented fingerprint update | **PASSED** |
| 10 | `test_end_to_end_mcp_research_flow` | `UnboundLocalError: active_inst_ids` | **PASSED** (Screening query variables bound properly) |
