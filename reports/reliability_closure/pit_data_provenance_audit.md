# Point-in-Time Data & Provenance Audit

**Document Version:** 1.0.0  
**Status:** Canonical Reference & Audit Report  
**Scope:** Signal Atlas Raw Data Manifest, Universe Provenance, and OHLCV Market Data Execution Verification

---

## 1. Executive Summary

This audit establishes the integrity, determinism, and limitation boundaries of Signal Atlas point-in-time (PIT) market data and cryptographic provenance architecture.

It documents:
1. Root-cause resolution of all 10 historical test failures reported in the Reliability Review Bundle.
2. Independent verification of execution prices, stop-outs, targets, and gap-downs against an offline OHLCV sample fixture (`tests/fixtures/sample_trades_ohlcv.json`).
3. Precise scoping of universe coverage, survivorship bias bounds, and delisting handling.

---

## 2. Root Cause Analysis & Resolution of Historical Test Failures

The historical test log in the review bundle recorded 10 failures. Each has been investigated, diagnosed, and resolved:

| # | Test Name | Failure Mode in Review Bundle | Root Cause | Resolution & Verification |
|---|---|---|---|---|
| 1 | `test_public_build_rejects_an_injected_manifest` | Failed: `DID NOT RAISE TypeError` | `build_universe()` in `service.py` improperly accepted a public `raw_manifest` argument, allowing callers to inject arbitrary or forged manifests. | Removed public `raw_manifest` argument from `build_universe()`. Manifest computation is strictly internal and private. Test passes. |
| 2 | `test_manifest_is_deterministic_and_hashes_raw_row_content` | Assertion failed: `m1 == m2` after raw price row mutation | `compute_raw_data_manifest()` was caching results to `data/.raw_manifest_cache.json` across calls, masking database row mutations. | Reverted global file caching in `provenance.py`. Raw manifest always computes directly from database state. Test passes. |
| 3 | Parameterized: `test_manifest_hashes_every_universe_input_table[Instrument]` | Fingerprint did not change after row modification | Same global caching artifact masked the mutation. | Reverted caching; SHA-256 updates deterministically on table change. Test passes. |
| 4 | Parameterized: `[InstrumentSymbolHistory]` | Fingerprint did not change | Same global caching artifact. | Reverted caching. Test passes. |
| 5 | Parameterized: `[TradingCalendar]` | Fingerprint did not change | Same global caching artifact. | Reverted caching. Test passes. |
| 6 | Parameterized: `[DailyPriceQuarantine]` | Fingerprint did not change | Same global caching artifact. | Reverted caching. Test passes. |
| 7 | Parameterized: `[IngestionRun]` | Fingerprint did not change | Same global caching artifact. | Reverted caching. Test passes. |
| 8 | Parameterized: `[CorporateAction]` | Fingerprint did not change | Same global caching artifact. | Reverted caching. Test passes. |
| 9 | `test_21_raw_data_manifest_and_code_revision_provenance` | Universe fingerprint did not change after price mutation | Snapshot build utilized cached raw manifest hash rather than detecting database change. | Reverted caching; snapshot binds directly to live manifest fingerprint. Test passes. |
| 10 | `test_end_to_end_mcp_research_flow` | `UnboundLocalError: local variable 'active_inst_ids' referenced before assignment` | In `src/signal_atlas/research/service.py`, `screen_candidates` failed to assign `active_inst_ids` inside the `if symbols:` branch. | Added `active_inst_ids = db.execute(subq).scalars().all()`. Research flow executes end-to-end cleanly. Test passes. |

---

## 3. OHLCV Execution & Price Adjustment Verification

To independently verify execution prices, slippage, and exit rules without requiring unsafe production database queries during test runs, an offline market-data fixture is committed at `tests/fixtures/sample_trades_ohlcv.json`.

### 3.1 Sample Trade Traceability Matrix

| Trade ID | Symbol | Dates | Type | Model Execution | Underlying Market Action | Reconciled? |
|---|---|---|---|---|---|---|
| `TRD-0003` | ADANIPOWER | 2022-03-23 to 2022-03-25 | Profit Target | Filled at Target ₹141.75 (+1.66 R) | On 2022-03-25, session high reached ₹141.75. Target reached intraday. | **YES** |
| `TRD-0001` | ONGC | 2022-03-23 to 2022-03-30 | Gap-Down Stop | Filled at Open ₹163.00 (-1.13 R) | Planned stop was ₹163.85. Session opened at ₹163.00 (gap-down). Engine correctly executed at ₹163.00 rather than assuming stop price. | **YES** |
| `TRD-0017` | DRREDDY | 2022-07-11 to 2022-07-26 | Intraday Stop | Filled at Stop ₹850.75 (-1.15 R) | Session low touched ₹849.20, crossing stop price ₹850.75. Filled at ₹850.75. | **YES** |
| `TRD-0035` | ZOMATO | 2022-09-05 to 2022-10-17 | Max Holding | Filled at Close ₹62.65 (+0.30 R) | Position held for exactly 30 market sessions. Liquidated at day 30 close. | **YES** |

### 3.2 Price Adjustment Conventions
- All historical simulation prices are backward-adjusted for corporate actions (splits, bonus shares, reverse splits) using candidate dataset v1.4 conventions.
- Only corporate actions with `ex_date <= as_of_date` are factored into features on day $t$, preventing future split lookahead.

---

## 4. Universe Coverage & Survivorship Bias Limitations

### 4.1 Strict Boundaries & Disclaimers
In accordance with professional quantitative reporting standards, the project does **not** claim "zero survivorship bias" or "completely survivorship-free data":

1. **Top 100 Scope:** The Point-in-Time universe reconstructs membership on the 1st trading session of every month based on 20-day trailing ADTV across all traded equities on that date.
2. **Delisting Tracking:** The `instruments` table maintains explicit `delisting_date` fields. Equities delisted during the simulation window (e.g. following insolvency or mergers) were eligible prior to delisting and excluded subsequent to delisting.
3. **Data Availability Bounds:** Historical bhavcopy archives span 2022-01-03 to 2024-12-31. Any security delisted prior to 2022 is excluded from historical ingestion.
4. **Conclusion:** Survivorship bias is strictly controlled within the liquid NSE Top 100 universe over the 2022–2024 study period, but results cannot be extrapolated to small-cap or illiquid market segments.
