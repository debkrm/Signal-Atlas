# ADR 0004: Phase 1B-i.2 Full Historical Coverage & Multi-Year Ingestion Reconciliation

## Status
Approved / Implemented (Awaiting Human Review for Phase 1B-ii Authorization)

## Context
Following the review of Phase 1B-i, technical implementation of the Legacy and CM-UDiFF parsers was accepted, but the actual historical dataset (104,230 records across 39 dates) was deemed insufficient for quantitative indicator calculations and corporate action adjustments.

Before proceeding to Phase 1B-ii (Corporate Actions & Adjusted Prices), Phase 1B-i.2 was authorized to achieve complete continuous daily coverage of NSE Cash Market Equities across the three-year window:
- **Start Date**: 2022-01-01
- **End Date**: 2024-12-31

Three targeted architectural directives were established:
1. **Authoritative Calendar Integration**: Weekday HTTP 404 responses must not automatically become holidays. Holidays must be confirmed against authoritative exchange circulars. Unverified 404s must be classified as `EXPECTED_DATA_MISSING` and kept eligible for retry.
2. **Gap-Aware Catch-Up Engine**: `--since-last` must discover and retry internal missing dates between earlier and later successfully ingested dates (e.g., missing Wednesday between Tuesday and Thursday).
3. **Overlapping Series History Support**: `instrument_symbol_history` must support concurrent overlapping validity when an instrument trades in multiple series (e.g. `EQ` and `BL`/`BO`) on the same date.

---

## 1. Architectural Enhancements

### 1.1 Authoritative Trading Calendar (`src/signal_atlas/providers/nse/calendar.py`)
Official NSE Capital Market holiday circulars and government notifications were codified into an authoritative calendar:
- **Circulars**: `NSE/CMTR/50560` (2022), `NSE/CMTR/54759` & `NSE/CMTR/57324` (2023), `NSE/CMTR/59648` (2024).
- **Special Live Weekend Sessions**:
  - `2023-11-12`: Sunday Muhurat Trading session.
  - `2024-01-20`: Saturday Full-day Live session (compensatory session prior to Jan 22 Ram Mandir holiday).
  - `2024-03-02`: Saturday Disaster Recovery (DR) Live switchover session.
  - `2024-05-18`: Saturday Disaster Recovery (DR) Live switchover session.
- **Special Declared Holidays**:
  - `2024-01-22`: Ayodhya Ram Mandir consecration ceremony.
  - `2024-05-20`: General Parliamentary Elections (Mumbai constituency).
  - `2024-11-20`: Maharashtra State Legislative Assembly Elections.
- **Shifted Holidays**:
  - In 2023, Bakri Id was shifted from June 28 to June 29 via NSE circular `NSE/CMTR/57324`. June 28 was a regular live trading session (2,425 records), and June 29 was the actual closed holiday.
- **Muhurat Trading Clarification**:
  - Diwali Laxmi Pujan sessions (`2022-10-24`, `2023-11-12`, `2024-11-01`) are live evening trading sessions with published Bhavcopy archives. They are categorized as live trading sessions, NOT closed holidays.

### 1.2 Categorization of Ingestion States
Weekday 404 responses no longer default to exchange holidays. Every session is explicitly categorized:
- `SUCCESS`: Complete Bhavcopy downloaded, parsed, validated, and persisted.
- `QUARANTINED`: Ingestion succeeded with isolated out-of-range exchange glitches quarantined and logged (e.g., SBIN:T0 same-day settlement glitch).
- `CONFIRMED_HOLIDAY`: Verified against authoritative NSE circulars and recorded in `trading_calendar`.
- `EXPECTED_DATA_MISSING`: Weekday 404 on an unverified date; recorded in `ingestion_runs` and flagged for catch-up retry.
- `NON_TRADING_DAY`: Regular weekends without live exchange sessions.
- `ALREADY_INGESTED`: Idempotent skip for previously persisted sessions.

### 1.3 Gap-Aware Catch-Up Engine
`IngestionPipeline.ingest_since_last()` was enhanced to calculate:
$$\text{Missing Sessions} = \text{Expected Calendar Sessions}_{[t_{\min}, t_{\text{target}}]} \setminus \text{Completed Sessions}_{\text{DB}}$$
This guarantees that internal missing dates (gaps between already-ingested dates) are automatically detected and ingested, rather than only scanning forward from the latest date.

---

## 2. Ingestion Execution & Overall Scale

Historical ingestion was executed quarterly with persistent checkpoints (`data/checkpoints/checkpoint_*.json`).

### 2.1 Dataset Scale
| Metric | Count | Verification Query |
| :--- | :--- | :--- |
| **Total Price Rows** | **1,838,125** | `SELECT COUNT(id) FROM daily_prices_raw;` |
| **Distinct Trading Dates** | **743** | `SELECT COUNT(DISTINCT trade_date) FROM daily_prices_raw;` |
| **Earliest Session** | **2022-01-03** | `SELECT MIN(trade_date) FROM daily_prices_raw;` |
| **Latest Session** | **2024-12-31** | `SELECT MAX(trade_date) FROM daily_prices_raw;` |
| **Total Ingestion Runs** | **743** (726 Clean + 17 Quarantined) | `SELECT status, count(*) FROM ingestion_runs GROUP BY status;` |
| **Confirmed Holidays** | **43** | Sourced from official NSE circulars |
| **Missing or Unresolved Dates** | **0** | `0` dates in `EXPECTED_DATA_MISSING` or `FAILED` |
| **Distinct Instruments** | **4,631** | `SELECT COUNT(instrument_id) FROM instruments;` |
| **Symbol History Records** | **7,600** | `SELECT COUNT(id) FROM instrument_symbol_history;` |
| **Duplicate Price Rows** | **0** | Enforced by `uq_daily_price_inst_date_series` |

### 2.2 Results by Year and Format Era
| Year | Era / Format | Expected Sessions | Ingested Sessions | Holidays | Persisted Rows | Traded Volume (Shares) | Traded Value (INR) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2024** | Legacy (H1) + UDiFF (H2) | 249 | 249 (100.0%) | 16 | 675,866 | 1,072,402,683,975 | 227,152,593,656,358.33 |
| **2023** | Legacy (`cm<DD><MMM><YYYY>bhav`) | 246 | 246 (100.0%) | 15 | 605,228 | 694,765,839,152 | 142,398,591,895,310.22 |
| **2022** | Legacy (`cm<DD><MMM><YYYY>bhav`) | 248 | 248 (100.0%) | 12 | 557,031 | 582,316,984,728 | 128,495,392,108,129.50 |
| **Total** | **Full 3-Year Coverage** | **743** | **743 (100.0%)** | **43** | **1,838,125** | **2,349,485,507,855** | **498,046,577,659,798.05** |

- **Format Era Distribution**:
  - `NSE_LEGACY`: 622 trading sessions (2022-01-03 through 2024-07-05).
  - `NSE_CM_UDIFF`: 121 trading sessions (2024-07-08 through 2024-12-31).

---

## 3. Representative Reconciliation (26 Sample Dates)

To verify end-to-end data integrity across both format eras, 26 representative trading dates were independently audited using `spikes/m0/reconcile_20_dates.py`.
The audit extracts raw exchange ZIP files from `data/raw/`, reparses the original CSVs, re-normalizes, and compares raw exchange rows, volume, and turnover against PostgreSQL:

| Date | Era | Status | Source Raw | Source Valid | Quarantined | DB Rows | Row Match | DB Volume == Source Volume | Traded Value (INR) Match |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2022-01-03** | Legacy | SUCCESS | 2,227 | 2,227 | 0 | 2,227 | 100% | 3,744,201,869 == 3,744,201,869 | 471,152,733,931.34 |
| **2022-03-22** | Legacy | SUCCESS | 2,190 | 2,190 | 0 | 2,190 | 100% | 2,309,576,451 == 2,309,576,451 | 618,212,954,016.48 |
| **2022-06-15** | Legacy | SUCCESS | 2,211 | 2,211 | 0 | 2,211 | 100% | 1,453,551,332 == 1,453,551,332 | 365,710,214,215.04 |
| **2022-09-08** | Legacy | SUCCESS | 2,287 | 2,287 | 0 | 2,287 | 100% | 3,024,289,664 == 3,024,289,664 | 590,303,681,912.72 |
| **2022-10-24** | Legacy | SUCCESS | 2,241 | 2,241 | 0 | 2,241 | 100% | 689,770,535 == 689,770,535 | 104,645,590,703.60 |
| **2022-12-30** | Legacy | SUCCESS | 2,335 | 2,335 | 0 | 2,335 | 100% | 2,980,107,163 == 2,980,107,163 | 440,234,995,448.69 |
| **2023-01-02** | Legacy | SUCCESS | 2,383 | 2,383 | 0 | 2,383 | 100% | 2,947,475,273 == 2,947,475,273 | 396,939,681,930.73 |
| **2023-04-20** | Legacy | SUCCESS | 2,358 | 2,358 | 0 | 2,358 | 100% | 1,698,263,326 == 1,698,263,326 | 452,079,231,431.82 |
| **2023-06-15** | Legacy | SUCCESS | 2,436 | 2,436 | 0 | 2,436 | 100% | 3,020,679,144 == 3,020,679,144 | 669,753,904,639.79 |
| **2023-06-28** | Legacy | SUCCESS | 2,425 | 2,425 | 0 | 2,425 | 100% | 2,944,657,531 == 2,944,657,531 | 820,212,831,608.36 |
| **2023-09-28** | Legacy | SUCCESS | 2,517 | 2,517 | 0 | 2,517 | 100% | 4,261,052,199 == 4,261,052,199 | 863,940,304,363.84 |
| **2023-11-03** | Legacy | SUCCESS | 2,588 | 2,588 | 0 | 2,588 | 100% | 4,313,006,958 == 4,313,006,958 | 623,782,518,314.12 |
| **2023-11-12** | Legacy | SUCCESS | 2,463 | 2,463 | 0 | 2,463 | 100% | 1,009,059,938 == 1,009,059,938 | 140,912,970,415.93 |
| **2023-12-29** | Legacy | SUCCESS | 2,647 | 2,647 | 0 | 2,647 | 100% | 5,985,606,632 == 5,985,606,632 | 960,887,026,383.73 |
| **2024-01-01** | Legacy | SUCCESS | 2,683 | 2,683 | 0 | 2,683 | 100% | 6,086,499,412 == 6,086,499,412 | 772,721,322,332.82 |
| **2024-01-20** | Legacy | SUCCESS | 2,590 | 2,590 | 0 | 2,590 | 100% | 4,643,845,204 == 4,643,845,204 | 804,474,886,102.64 |
| **2024-03-02** | Legacy | SUCCESS | 2,440 | 2,440 | 0 | 2,440 | 100% | 701,679,449 == 701,679,449 | 104,272,320,136.44 |
| **2024-05-18** | Legacy | SUCCESS | 2,512 | 2,512 | 0 | 2,512 | 100% | 763,672,830 == 763,672,830 | 154,379,724,292.72 |
| **2024-06-03** | Legacy | SUCCESS | 2,805 | 2,805 | 0 | 2,805 | 100% | 6,671,447,058 == 6,671,447,058 | 1,725,398,790,588.87 |
| **2024-07-05** | Legacy | SUCCESS | 2,775 | 2,775 | 0 | 2,775 | 100% | 5,890,634,246 == 5,890,634,246 | 1,556,742,443,788.69 |
| **2024-07-08** | UDiFF | SUCCESS | 2,815 | 2,815 | 0 | 2,815 | 100% | 5,905,374,490 == 5,905,374,490 | 1,447,565,634,169.24 |
| **2024-07-15** | UDiFF | SUCCESS | 2,839 | 2,839 | 0 | 2,839 | 100% | 5,306,239,533 == 5,306,239,533 | 1,317,493,712,061.93 |
| **2024-08-19** | UDiFF | QUARANTINED | 2,842 | 2,841 | 1 | 2,841 | 100% | 4,127,487,102 == 4,127,487,102 | 1,084,030,283,905.28 |
| **2024-10-25** | UDiFF | SUCCESS | 2,902 | 2,902 | 0 | 2,902 | 100% | 3,810,070,183 == 3,810,070,183 | 1,147,257,385,080.38 |
| **2024-11-01** | UDiFF | SUCCESS | 2,746 | 2,746 | 0 | 2,746 | 100% | 1,006,932,162 == 1,006,932,162 | 182,249,765,537.46 |
| **2024-12-31** | UDiFF | SUCCESS | 2,916 | 2,916 | 0 | 2,916 | 100% | 3,155,260,088 == 3,155,260,088 | 832,527,801,115.57 |

**Result**: **26/26 dates passed reconciliation (100.0%)**.
Every persisted row, traded share count, and traded rupee value matches the original raw exchange files with 0 discrepancy.

---

## 4. Instrument Identity & Series Concurrency Audit

### 4.1 Concurrent Series Preservation (`EQ`, `BL`, `BO`)
On dates with institutional block deals or share buybacks, the exchange emits price records under multiple series for the identical ISIN.
- **Example 1**: `2024-07-15` Godrej Consumer Products (`INE102D01028`): both `EQ` (Close 1436.70, Vol 521,240) and `BL` (Close 1443.90, Vol 11,392,858) were concurrently persisted without overwriting.
- **Example 2**: `2022-01-20` Sammaan Capital (`INE8997...`): both `EQ` and `BL` persisted concurrently.
- Enforced constraint: `UNIQUE (instrument_id, trade_date, series)`.

### 4.2 Surveillance Shifts (`EQ` -> `BE` / `BZ` / `SM`)
When an equity moves to trade-to-trade settlement (`BE`) or Z-category surveillance (`BZ`), its underlying ISIN is identical.
- **Example**: `SECUR CREDENTIALS LIMITED` (`INE195Y01010`) moved across `SM` -> `EQ` -> `BE` -> `BZ` over the period. All series transitions mapped to the same `instrument_id`.
- The symbol history table maintains each series as a distinct validity interval starting from `valid_from`.

### 4.3 Multi-ISIN Instruments (Corporate Action Stock Splits)
An audit across the complete 3-year history identified **152 instruments** mapped to more than one ISIN:
- **Root Cause**: In India, when a company conducts a stock split or capital reduction, NSDL/CDSL revokes the old ISIN and issues a new ISIN corresponding to the new face value (e.g. `INE...01018` -> `INE...01026`).
- **Examples**:
  - `EASEMYTRIP`: `INE07O001018` (Rs 2 face value) -> Stock Split -> `INE07O001026` (Rs 1 face value).
  - `JBMA`: `INE927D01028` (Rs 5 face value) -> Stock Split -> `INE927D01044` (Rs 2 face value).
  - `PCBL`: `INE602A01023` -> Stock Split -> `INE602A01031`.
  - `SAPPHIRE`: `INE806T01012` -> Stock Split (Sept 2024) -> `INE806T01020`.
- **Finding**: In all 152 instances, the issuer prefix (`INE...`) is identical, and the continuous ticker symbol mapped the pre-split and post-split trading records to the same company `instrument_id`.
- This ensures uninterrupted instrument continuity for corporate actions. There are **zero cross-company ISIN collisions** in the database.

---

## 5. Catch-Up & Recovery Test Verification

Comprehensive automated recovery tests were added in `tests/integration/test_catchup_recovery.py`:
1. `test_catchup_discovers_internal_gap`: Ingests Mon, Tue, Thu, Fri (omitting Wed). Verifies `--since-last` discovers and ingests Wed.
2. `test_recovery_after_download_failure`: Simulates network timeout on download, verifies failure status, and asserts clean recovery on retry.
3. `test_recovery_after_parser_error`: Injects corrupted ZIP bytes, asserts `FAILED` ingestion run record, and recovers on retry with valid payload.
4. `test_recovery_after_database_failure`: Simulates DB connection loss during flush; verifies transaction atomicity (no orphaned price records remain) and clean retry.
5. `test_interrupted_batch_recovery`: Simulates batch interruption mid-sequence; verifies subsequent resumption skips already-ingested sessions and completes remaining days with zero duplicates.
6. `test_archive_conflict_preservation`: Asserts raw archiver creates `.conflict_<timestamp>_<sha>` versions when content differs for identical filename.
7. `test_overlapping_series_symbol_history`: Verifies concurrent multi-series symbol histories with identical `valid_from` timestamps.

Full test suite: **48/48 passed in 2.66s**.

---

## 6. Acceptance Criteria Verification

| Criteria | Status | Evidence |
| :--- | :---: | :--- |
| **1. 2022–2024 trading calendar documented** | **MET** | Codified in `src/signal_atlas/providers/nse/calendar.py` with circular references. |
| **2. Every expected session imported or listed** | **MET** | 743 of 743 expected sessions successfully ingested. 0 missing dates. |
| **3. No weekday 404 automatically classified as holiday** | **MET** | Weekday 404 raises `ExpectedDataMissingError`; verified in downloader unit tests. |
| **4. Catch-up discovers internal missing gaps** | **MET** | Verified in `test_catchup_discovers_internal_gap`. |
| **5. Import can resume after interruption** | **MET** | Verified in `test_interrupted_batch_recovery`. |
| **6. No duplicate daily records created** | **MET** | Verified across all 1,838,125 rows (`spikes/m0/verify_uniqueness.py`). |
| **7. Source-to-database reconciliation passes** | **MET** | 26/26 dates passed with 100% row, volume, and value match. |
| **8. Original source files & hashes preserved** | **MET** | All 743 ZIP archives saved in `data/raw/` with verified SHA-256 hashes. |
| **9. Both parsers remain fully tested** | **MET** | Unit and integration suites for Legacy and UDiFF pass cleanly. |
| **10. Full coverage report generated** | **MET** | Documented in `docs/decisions/0004-historical-coverage.md`. |

---

## 7. Next Steps
Phase 1B-i.2 is complete and verified. Stop for human review and authorization before initiating **Phase 1B-ii: Corporate Actions & Adjusted Prices**.
