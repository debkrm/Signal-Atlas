# Decision Record 0003: Phase 1B-i Historical Raw Price Import & Multi-Era Ingestion

- **Status:** Completed / Ready for Review
- **Date:** 2026-10-31
- **Authors:** Signal Atlas Core Agent
- **Target Audience:** Quantitative Strategy Developer / Project Maintainer
- **Context:** Phase 1B-i (Historical Raw Price Import)

---

## 1. Executive Summary

Phase 1B-i has been implemented, validated, and verified against empirical historical NSE market data. The system now supports continuous, multi-year historical EOD Bhavcopy ingestion across both historical eras:
1. **Legacy Bhavcopy Era (< 2024-07-08)**: 14-column format (`cm<DD><MMM><YYYY>bhav.csv.zip`) with trailing commas and `TIMESTAMP` format `DD-MMM-YYYY`.
2. **CM-UDiFF Common Bhavcopy Era (>= 2024-07-08)**: 34-column format (`BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip`) with `TradDt` format `YYYY-MM-DD`.

Across 39 trading days ingested in the database:
- **104,230** raw daily price records persisted.
- **3,771** unique reference instruments resolved.
- **5,148** symbol-series history records tracked.
- **41/41** automated tests passing (100% pass rate).
- **12/12** multi-date audit dates reconciled with 100% exact match between source archives and database.

---

## 2. Key Forensic Discoveries & Safeguards

### 2.1 Multi-Date Historical Identity Discovery: Block Deals (`BL`) and Buybacks (`BO`)
During the multi-date identity audit across 15 historical files, we verified the user's safeguard hypothesis:
> *"Validate identity across multiple historical dates. Don't assume the constraint is safe for every historical date solely because it passed one date."*

On 2024-10-25, there happened to be 0 duplicate ISINs. However, multi-date historical audit revealed that on multiple dates across both Legacy and UDiFF eras:
- `2024-07-15`: `GODREJCP` (ISIN `INE102D01028`) appeared with series `EQ` and series `BL` (Block Deal window).
- `2024-08-05`: `JUBLPHARMA` (ISIN `INE700A01033`) appeared with series `EQ` and series `BL`.
- `2024-09-06`: `SHRIPISTON`, `HGS`, and `METROBRAND` appeared with series `EQ` and `BL`.
- `2023-11-03`: `CLEDUCATE` (ISIN `INE201M01029`) appeared with series `EQ` and `BO` (Buy Back window).
- `2023-06-15`: `AXISBANK` (ISIN `INE238A01034`) appeared with series `EQ` and `BL`.

**Impact & Fix**:
Under the initial schema, `daily_prices_raw` enforced `UNIQUE(instrument_id, trade_date)`. If an instrument had both `EQ` and `BL` sessions on the same date, PostgreSQL threw a unique constraint violation, forcing either data loss or crash.
Empirical audit proved that **`(ISIN, Series)` is strictly unique across 100% of historical records** in every file tested.
We implemented Alembic migration `0002_daily_prices_unique_series.py`, upgrading the constraint to:
```sql
UNIQUE (instrument_id, trade_date, series)
```
This guarantees that block deals (`BL`) and buyback offers (`BO`) can be safely retained without corrupting equity (`EQ`) series history or losing source records.

### 2.2 Permanent Literal `NA` Series Regression Test
In `tests/unit/test_parser.py` and `tests/unit/test_normalizer.py`, we created permanent regression tests guaranteeing:
1. `SERIES == "NA"` remains the literal string `"NA"` (and is never converted to `NaN`, `float`, or `None`).
2. Empty fields remain distinguishable from `"NA"` (empty strings stay `""`, missing names stay `None`).
3. Invalid numeric fields (e.g. `"NOT_A_PRICE"`, `"nan"`) raise `ValueError` and are **never** silently converted to zero.

### 2.3 Archive Discrepancy & Safe Archiving
`RawArchiver` was updated to guarantee non-destructive archiving:
- If an archive file already exists with an identical SHA-256 hash, it returns the existing path idempotently without redundant disk writes.
- If a subsequent download yields different bytes for the same filename, it **does not silently overwrite**; it saves the new version as `<filename>.conflict_<timestamp>_<sha256[:8]>` and logs an alert for forensic inspection.

### 2.4 Trading Calendar & Non-Trading Day Handling
Exchange holidays and weekends are handled deterministically:
- Saturdays and Sundays are pre-filtered without network requests.
- Weekday 404 responses from NSE are identified as exchange holidays (e.g. `2024-06-17` Bakri Id) and recorded in `trading_calendar` as `is_trading_day=False` (`holiday_name="EXCHANGE_HOLIDAY_OR_UNAVAILABLE"`).
- Parser errors are strictly distinguished from unavailable data.

---

## 3. Incremental Rollout Batches & Verification

The ingestion engine was rolled out in verified incremental batches:

| Batch | Scope | Date Range | Records Persisted | Outcome |
|---|---|---|---|---|
| **Batch 1** | Sample Legacy Dates | 2022-07-27, 2022-07-28, 2023-09-27, 2023-09-28, 2024-01-12 | 12,106 | 100% Pass. Validated Tata Steel 10:1 split date and HAL 2:1 split date. |
| **Batch 2** | Continuous 1-Month Legacy | 2024-06-01 to 2024-06-30 | 52,631 | 100% Pass. Successfully detected Bakri Id holiday on 2024-06-17. |
| **Batch 3** | Legacy-to-UDiFF Transition | 2024-07-01 to 2024-07-15 | 30,803 | 100% Pass. Seamless transition across 2024-07-08 boundary. |
| **Batch 4** | Catch-Up Mode (`--since-last`) | 2024-10-26 to 2024-10-29 | 5,785 | 100% Pass. Correctly caught up from last ingested date (2024-10-25). |

---

## 4. Multi-Date Source-to-Database Reconciliation Evidence

12 representative dates spanning 2022, 2023, and 2024 across both eras were reconciled using `spikes/m0/reconcile_historical_batch.py`:

| Trade Date | Era | CSV Rows | DB Rows | Quarantined | Row Reconciled | Vol Reconciled | `NA` Reconciled | Status |
|---|---|---|---|---|---|---|---|---|
| **2022-07-27** | Legacy | 2,215 | 2,215 | 0 | **True** | **True** | **True** | SUCCESS |
| **2022-07-28** | Legacy | 2,222 | 2,222 | 0 | **True** | **True** | **True** | SUCCESS |
| **2023-09-27** | Legacy | 2,500 | 2,500 | 0 | **True** | **True** | **True** | SUCCESS |
| **2023-09-28** | Legacy | 2,517 | 2,517 | 0 | **True** | **True** | **True** | SUCCESS |
| **2024-01-12** | Legacy | 2,652 | 2,652 | 0 | **True** | **True** | **True** | SUCCESS |
| **2024-06-04** | Legacy | 2,757 | 2,757 | 0 | **True** | **True** | **True** | SUCCESS |
| **2024-06-25** | Legacy | 2,761 | 2,761 | 0 | **True** | **True** | **True** | SUCCESS |
| **2024-07-05** | Legacy | 2,775 | 2,775 | 0 | **True** | **True** | **True** | SUCCESS |
| **2024-07-08** | UDiFF | 2,815 | 2,815 | 0 | **True** | **True** | **True** | SUCCESS |
| **2024-07-15** | UDiFF | 2,839 | 2,839 | 0 | **True** | **True** | **True** | SUCCESS |
| **2024-10-25** | UDiFF | 2,902 | 2,902 | 0 | **True** | **True** | **True** | SUCCESS |
| **2024-10-28** | UDiFF | 2,920 | 2,920 | 0 | **True** | **True** | **True** | SUCCESS |

**Reconciliation Result:** **100% Match across all 12 dates.**
- Total Traded Volume: Reconciled down to the individual share.
- Literal `NA` Series: Preserved and reconciled across both eras.
- Traded Value: Exactly reconciled with Decimal math.

---

## 5. Phase 1B-i Acceptance Criteria Checklist

- [x] **Criterion 1**: Both historical format parsers pass their test suites (`tests/unit/test_parser.py`).
- [x] **Criterion 2**: A continuous historical period can be imported successfully (June 2024 continuous month).
- [x] **Criterion 3**: The Legacy-to-UDiFF transition is handled correctly (`2024-07-01` to `2024-07-15`).
- [x] **Criterion 4**: Re-running imports does not create duplicate records (verified with `ALREADY_INGESTED`).
- [x] **Criterion 5**: Failed dates can be retried independently (`--force` or single-date rerun).
- [x] **Criterion 6**: `--since-last` correctly identifies missing trading sessions and catches up.
- [x] **Criterion 7**: Source-to-database reconciliation passes for sampled historical dates across both eras (12/12 passed).
- [x] **Criterion 8**: Literal `NA` series parsing is protected by permanent regression tests.
- [x] **Criterion 9**: Historical coverage gaps are documented (weekends, exchange holidays like Bakri Id).
- [x] **Criterion 10**: The entire import can be restarted without manual database cleanup.
