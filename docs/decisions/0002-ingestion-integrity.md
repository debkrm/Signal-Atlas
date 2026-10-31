# Decision Record 0002: Ingestion Data Integrity & Identity Audit

- **Status:** Completed / Ready for Review
- **Date:** 2026-10-31
- **Authors:** Signal Atlas Core Agent
- **Target Audience:** Project Maintainer
- **Context:** Phase 1A.1 Data Integrity Review

---

## 1. Executive Summary

A comprehensive forensic audit of the `2024-10-25` CM-UDiFF ingestion pipeline was conducted to verify bit-level file provenance, instrument identity modeling, constraint safety, and source-to-database row reconciliation.

**Key Findings:**
1. **Archive Hash & Content Integrity**:
   - The Phase 0 and Phase 1A downloaded ZIP archives are **100% byte-for-byte identical** (`170,963` bytes, SHA-256 `1bffc104f8ab173eac972d0ef4a14dd609eb3e54138dac547817d8a6659b7e6c`).
   - The extracted CSV content matches byte-for-byte (`503,392` bytes, SHA-256 `fed0742836df91b672c987d3310f81997daef865d1ac831546b0415ef5654866`).
   - The discrepancy observed earlier was an isolated documentation transcription error in the summary table of `0001-data-sources.md` (which recorded `171,940` bytes from an earlier draft), whereas the underlying downloaded file and the machine-generated `bhavcopy_summary.json` were always identical.
2. **Instrument Identity & Constraint Safety**:
   - Every single row in the Bhavcopy has a **unique ISIN** (2,902 rows, 2,902 unique ISINs, 0 duplicate ISINs).
   - An ISIN *never* occurs across multiple series on the same trading day (0 multi-series ISINs on the same date).
   - `UNIQUE(instrument_id, trade_date)` is strictly safe because instrument identity maps 1-to-1 with the tradable financial security (ISIN).
   - Series transitions (e.g., `EQ` to `BE` or `BZ`) retain the continuous `instrument_id` because the ISIN is invariant, while preserving the exact series on the price record and creating a new effective-dated `InstrumentSymbolHistory` row.
3. **Source Row Coverage Reconciliation**:
   - Source CSV Rows: **2,902**
   - Database Persisted Rows: **2,902** (100% match, 0 rows dropped, merged, or lost).
   - Total Volume: **3,810,070,183** shares (exact match).
   - Total Traded Value: **Rs. 1,147,257,385,080.38** (exact match down to the paisa).
   - Identified and resolved a subtle financial parsing gotcha: Pandas `read_csv` by default treats exchange Series `"NA"` (Non-Convertible Debentures) as missing `NaN`. Fixed by enforcing `keep_default_na=False`.
4. **PostgreSQL Integration Verification**:
   - Added 5 automated integration tests against live PostgreSQL (`tests/integration/test_postgres_integration.py`). All 28 test suite items pass cleanly.

---

## 2. Archive Hash & Content Discrepancy Investigation

### 2.1 File Comparison Matrix (2024-10-25)

| Metric | Phase 0 Download (`spikes/m0/downloads/`) | Phase 1A Download (`data/raw/2024/`) | Verification Match |
|---|---|---|---|
| **ZIP File Size** | 170,963 bytes | 170,963 bytes | **MATCH (Exact)** |
| **ZIP SHA-256** | `1bffc104f8ab173eac972d0ef4a14dd609eb3e54138dac547817d8a6659b7e6c` | `1bffc104f8ab173eac972d0ef4a14dd609eb3e54138dac547817d8a6659b7e6c` | **MATCH (Exact)** |
| **Internal CSV Name** | `BhavCopy_NSE_CM_0_0_0_20241025_F_0000.csv` | `BhavCopy_NSE_CM_0_0_0_20241025_F_0000.csv` | **MATCH (Exact)** |
| **CSV File Size** | 503,392 bytes | 503,392 bytes | **MATCH (Exact)** |
| **CSV SHA-256** | `fed0742836df91b672c987d3310f81997daef865d1ac831546b0415ef5654866` | `fed0742836df91b672c987d3310f81997daef865d1ac831546b0415ef5654866` | **MATCH (Exact)** |
| **Total Lines** | 2,903 lines (1 header + 2,902 data) | 2,903 lines (1 header + 2,902 data) | **MATCH (Exact)** |

### 2.2 Conclusion
There is **no difference in market data or ZIP compression**. The downloaded archives from both phases are identical bit-for-bit.

---

## 3. Instrument Identity & Uniqueness Audit

### 3.1 Uniqueness Metrics in 2024-10-25 CM-UDiFF

- **Total Data Rows**: 2,902
- **Unique ISINs**: 2,902
- **Duplicate ISINs**: 0
- **Unique Symbols**: 2,898
- **Duplicate Symbols**: 2
  - `IMC1`: Appears 4 times under series `N0`, `N1`, `N2`, `N3` with 4 distinct ISINs (`INE00QS24019`, `INE00QS24043`, `INE00QS24027`, `INE00QS24035`) representing 4 separate STRIPs/bonds of Indian Railway Finance / IMC.
  - `RADIOCITY`: Appears 2 times under series `EQ` (Equity, ISIN `INE919I01024`) and series `P1` (Preference Shares, ISIN `INE919I04010`).
- **Multi-Series ISINs on Same Date**: **0**. An ISIN never trades under multiple series simultaneously on the same date.

### 3.2 Evaluation of `UNIQUE(instrument_id, trade_date)`
- Because each tradable security has a distinct ISIN, resolving instrument identity primarily by ISIN guarantees that each security gets a unique `instrument_id`.
- On any single trading date `t`, a security can have at most one official EOD OHLC bar.
- Therefore, `UNIQUE(instrument_id, trade_date)` is **strictly correct and safe**.

### 3.3 Series Transition Modeling (`EQ` to `BE` / `BZ`)
- When a stock shifts surveillance or settlement series (e.g. `EQ` -> `BE` or `BZ`):
  - The security's **ISIN remains unchanged**.
  - `isin_to_instrument_id[rec.isin]` resolves to the existing `instrument_id`, preserving continuous history.
  - A new entry is appended to `instrument_symbol_history` with `series="BE"` and `valid_from=trade_date`.
  - The raw price record in `daily_prices_raw` stores the exact `series` attribute for that trading session.
  - Verified by integration test `test_postgres_series_transition_preserves_instrument`.

---

## 4. Source-to-Database Reconciliation

Reconciliation between the raw source CSV and PostgreSQL records (`reconcile_coverage.py`):

| Reconciliation Item | Source CSV | Database (`daily_prices_raw`) | Discrepancy |
|---|---|---|---|
| **Total Rows** | 2,902 | 2,902 | **0 (100% Match)** |
| **Quarantined / Rejected** | 0 | 0 | **0** |
| **Lost / Merged Rows** | 0 | 0 | **0** |
| **Total Traded Volume** | 3,810,070,183 shares | 3,810,070,183 shares | **0 (Exact Match)** |
| **Total Traded Value** | Rs. 1,147,257,385,080.38 | Rs. 1,147,257,385,080.38 | **Rs. 0.00 (Exact Match)** |

### 4.1 Series Distribution Breakdown (Top 12)

| Series | Description | Source CSV Rows | PostgreSQL Persisted Rows | Status |
|---|---|---|---|---|
| `EQ` | Normal Equity Shares | 1,904 | 1,904 | Match |
| `BE` | Book Entry / Trade-for-Trade | 312 | 312 | Match |
| `SM` | SME Equity | 264 | 264 | Match |
| `ST` | SME Trade-for-Trade | 104 | 104 | Match |
| `GB` | Government Bonds | 51 | 51 | Match |
| `GS` | Government Securities | 47 | 47 | Match |
| `BZ` | Trade-for-Trade Surveillance | 26 | 26 | Match |
| `TB` | Treasury Bills | 22 | 22 | Match |
| `N7` | Non-Convertible Debentures (Sr 7) | 12 | 12 | Match |
| `N6` | Non-Convertible Debentures (Sr 6) | 12 | 12 | Match |
| `NA` | Non-Convertible Debentures (Sr A) | 8 | 8 | Match |
| Other | Debt & Preference series (47 series) | 140 | 140 | Match |

*Resolution of Pandas `Series NA` bug:*
In standard Pandas `read_csv`, the string `"NA"` is by default interpreted as missing value `NaN`. This caused the 8 Non-Convertible Debenture rows in series `NA` to be parsed as string `"NAN"`. Enforcing `keep_default_na=False` in `udiff_parser.py` resolved this issue completely.

---

## 5. PostgreSQL Integration Test Suite

Added automated PostgreSQL integration tests in `tests/integration/test_postgres_integration.py` targeting a dedicated test database (`signal_atlas_test`):
1. `test_postgres_unique_constraint_enforcement`: Verifies PostgreSQL raises `IntegrityError` on duplicate `(instrument_id, trade_date)`.
2. `test_postgres_exact_decimal_precision`: Verifies `NUMERIC` types preserve exact decimal representation without binary float drift.
3. `test_postgres_transaction_rollback_on_failure`: Verifies that a fatal validation error rolls back the entire database transaction, leaving zero partial records.
4. `test_postgres_idempotent_ingestion`: Verifies that re-running ingestion skips duplicate processing and preserves row counts, while `--force` cleans and replaces data idempotently.
5. `test_postgres_series_transition_preserves_instrument`: Verifies that an instrument moving from `EQ` to `BE` retains the identical `instrument_id` in PostgreSQL.

**Test Run Summary:**
- Fast unit tests: 20 passed
- In-memory SQLite tests: 3 passed
- PostgreSQL integration tests: 5 passed
- **Total: 28 passed in 7.23s**

---

## 6. Recommendations & Next Steps

1. **Phase 1A.1 Acceptance**: All data integrity, uniqueness, decimal precision, and reconciliation criteria are verified with zero data loss.
2. **Proceed to Phase 1B-i**: The production pipeline foundation is sound. We recommend proceeding to **Phase 1B-i (Historical Raw Price Import)**.
