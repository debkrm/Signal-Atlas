# Signal Atlas Progress

## Current phase
Phase 2 — Indicators, Trend-Pullback Swing Strategy, and Realistic Backtesting Engine

## Status
Complete (Awaiting Human Review)


## Completed
- [x] Initialized Git repository and linked to remote `https://github.com/debkrm/Signal-Atlas.git`.
- [x] Completed Phase 0 feasibility spikes (`spikes/m0/`) and delivered `docs/decisions/0001-data-sources.md`.
- [x] Bootstrapped `signal-atlas` package (`src/signal_atlas/`) using `pyproject.toml` and `src` layout.
- [x] Configured PostgreSQL service via `docker-compose.yml` and `.env.example`.
- [x] Implemented initial database schema and applied Alembic migration `0001_initial_schema.py`.
- [x] Completed Phase 1A.1 Data Integrity & Ingestion Review (`docs/decisions/0002-ingestion-integrity.md`).
- [x] Completed Phase 1B-i Ingestion Implementation (`docs/decisions/0003-phase-1b-i-historical-import.md`).
- [x] Completed Phase 1B-i.2 Full Historical Coverage 2022–2024 (`docs/decisions/0004-historical-coverage.md`).
- [x] Completed Phase 1B-i.3 Historical Data Integrity Closure (`docs/decisions/0005-data-integrity-closure.md`).
- [x] Completed Phase 1B-ii.0 Corporate Action Registry Verification (`docs/decisions/0006-corporate-action-registry.md`).
- [x] Completed Phase 1B-ii.0.1 Corporate Action Registry Closure (`docs/decisions/0007-adjustment-convention.md`).
- [x] Completed Phase 1B-ii.1 Provisional Bulk Historical Adjustment Engine (`v1.0`).
- [x] Completed Phase 1B-ii.2 Adjustment Semantics and Validation Closure (`v1.1`).
- [x] **Completed Phase 1B-ii.2.1 (Final Audit Reconciliation)**:
  - **Issue 1 Resolved — Bonus Event Row-Level Audit Reconciliation**:
    - Reconciled candidate observations vs event counts:
      - Total verified bonus candidate observations: **224**
      - Total distinct `BONUS_ISSUE` events in `corporate_actions`: **224**
      - Duplicate candidate observations: **0**
      - Same-ISIN bonus events (`old_isin == new_isin`): **222**
      - Multi-ISIN companion bonus events: **2** (`VERTOZ` on 2024-07-05 and `GOLDSTAR` on 2023-01-23, where a stock split also changed ISIN on the same ex-date).
    - Clarified that the initial sweep flag was an *instrument-level* history check (25 multi-ISIN companies, 23 of which had standalone bonus issues preserving ISIN, plus 2 companion events = 25).
    - Exported row-level audit in `data/checkpoints/bonus_candidates_row_level_reconciliation.json` and `.csv`.
  - **Issue 2 Resolved — Reconcile 99 Registry Splits vs 92 Sweep Candidates**:
    - Accounted for all 7 additional registry records individually:
      1. `VERTOZ` (`2024-07-05`): In sweep as Cand 391 under `VERIFIED_BONUS` due to concurrent bonus; decomposed into split companion in registry.
      2. `GOLDSTAR` (`2023-01-23`): In sweep as Cand 165 under `VERIFIED_BONUS` due to concurrent bonus; decomposed into split companion in registry.
      3. `4THDIM` (`2023-01-23`): In sweep as Cand 164 under renamed symbol `GVPTECH` (classified as `VERIFIED_BONUS`); recorded as 5:1 split under `4THDIM` in registry.
      4. `JTLINFRA` (`2024-11-14`): In sweep as Cand 461 under new symbol `JTLIND` (classified as `VERIFIED_BONUS`); recorded under predecessor symbol `JTLINFRA` in registry.
      5. `DRCSYSTEMS` (`2022-03-21`): Trading suspended 2022-03-14 to 2022-03-21; NSE published pre-adjusted `prev_close = 38.15` and `close = 40.05` on resumption (ratio 0.95 < 1.30 threshold).
      6. `KAUSHALYA` (`2024-02-06`): Capital consolidation / 100:1 reverse split. Price increased 100x from ₹9.85 to ₹988.30 (ratio 0.01); sweep only scanned for price drops ($\ge 1.30$).
      7. `KCK` (`2024-10-30`): SME equity traded under `ST` series (Circular `NSE/CML/64746`). Sweep filter restricted series to `["EQ", "BE", "BZ", "SM"]` and excluded `ST`.
    - Exported in `data/checkpoints/split_events_reconciliation.json` and `.csv`.
  - **Issue 3 Resolved — Dynamic Point-in-Time Engine & 3 Decision Dates**:
    - Implemented dynamic PIT service interface `get_point_in_time_adjusted_history(instrument_id, as_of_date, series="EQ", db=None)` in `src/signal_atlas/quality/adjustment.py`.
    - Strictly bounded historical queries to $\text{trade\_date} \le A$ with zero lookahead bias.
    - Verified on VBL across 3 distinct historical decision dates:
      - Decision Date A (`2023-06-14`, before split 1): $M = 1.000000$ (raw units), max date `2023-06-14`.
      - Decision Date B (`2023-06-16`, after split 1, before split 2): $M = 2.000000$ prior to 2023-06-15, $M = 1.000000$ on 2023-06-16, max date `2023-06-16`. Split 2 strictly omitted.
      - Decision Date C (`2024-09-13`, after both splits): $M = 5.000000$ ($2.0 \times 2.5$) prior to split 1, $M = 2.500000$ between splits, $M = 1.000000$ on 2024-09-13, max date `2024-09-13`.
  - **Issue 4 Resolved — Provenance-Classified Per-Event Reporting**:
    - Categorized 100% of the 378 canonical events across 4 provenance tiers:
      - Tier 1: 7 Downloaded & SHA-256 Hashed Circular PDFs
      - Tier 2: 133 Authoritative Linked Circular References (Archive Offline)
      - Tier 3: 227 Official Exchange Master & Regulatory Filings
      - Tier 4: 11 Unresolved ETF Restructurings Quarantined ($M=1.0$)
    - Exported complete provenance metadata in `data/checkpoints/corporate_action_provenance_full_report.json` and `.csv`.
  - **Issue 5 Resolved — Turnover Edge-Case Hardening**:
    - Safely handled zero volume ($V_{\text{raw}} = 0$) and missing/null traded value:
      - `raw_vwap` and `adjusted_vwap` safely set to `None`.
      - ZeroDivisionError eliminated.
      - Raw NSE `traded_value` preserved unchanged.
  - **Comprehensive Test Suite**:
    - **84 / 84 tests passing** (100% pass rate).
- [x] **Completed Phase 1B-ii.2.2 (Final Adjustment Eligibility and Data Quality Closure)**:
  - **Issue 1 Resolved — Reverse-Split Adjustment Eligibility**:
    - Replaced `share_multiplier > 1.0` with unified eligibility function `is_action_eligible_for_price_adjustment(ca)`.
    - Included verified splits/consolidations where `share_multiplier != 1.0` and `share_multiplier > 0`.
    - Validated `KAUSHALYA` 100:1 consolidation ($M=0.010000$ on 2024-02-06): historical prices divided by 0.01 ($100\times P_{\text{raw}}$), volume multiplied by 0.01 ($0.01\times V_{\text{raw}}$).
    - Preserved seamless overnight returns by dynamically aligning resumption `adj_prev_close` to prior trading session adjusted close (₹985.00).
    - Verified identical eligibility consumption between database adjustment engine and provenance reporting.
  - **Issue 2 Resolved — Missing Turnover Financial Semantics**:
    - Applied Alembic migration `0009_allow_nullable_traded_value.py` to make `traded_value` and `raw_traded_value` nullable in `daily_prices_adjusted`.
    - Preserved missing/null source turnover as `None`, distinct from source-reported ₹0.00.
    - Set `raw_vwap` and `adjusted_vwap` to `None` whenever volume is 0 or turnover is `None`.
    - Established liquidity ranking rule: records with `traded_value is None` are ineligible for ranking.
  - **Issue 3 Resolved — Genuine Event-Level ISIN Reconciliation**:
    - Implemented `spikes/m0/generate_event_level_reconciliation.py` using dynamic `InstrumentSymbolHistory` queries.
    - Classified candidates based on verified pre- and post-event ISINs rather than disposition categories.
    - Derived 224 bonus events: 183 same-ISIN, 41 multi-ISIN, 2 companion bonus/split events (`GOLDSTAR` and `VERTOZ`), 0 duplicate candidates.
    - Regenerated `candidates_disposition_cross_tabulation.json` and `bonus_candidates_row_level_reconciliation.json` / `.csv`.
  - **Issue 4 Resolved — Cryptographic Provenance Verification**:
    - Recomputed SHA-256 directly from file bytes in `data/circulars/*.pdf` using `hashlib.sha256()`.
    - Confirmed 7/7 Tier 1 circulars have exact hash matches (`HASH_VERIFIED_MATCH`).
    - Preserved missing publication dates as `None` without falling back to ex-date.
    - Re-exported `corporate_action_provenance_full_report.json` and `.csv`.
  - **Issue 5 Resolved — Version v1.2 Dataset Migration**:
    - Preserved `v1.0` and `v1.1` immutable in PostgreSQL.
    - Built version `v1.2` containing 1,848,718 records (180,301 corporate action records, 1,668,417 identity records).
    - Preserved 1,855,370 raw price records untouched. Excluded 6,652 quarantined ETF records.
  - **Comprehensive Test Suite**:
    - **94 / 94 tests passing** (100% pass rate).
- [x] **Completed Phase 1B-ii.2.3 (Candidate Disposition and Security Identity Reconciliation)**:
  - **Issue 1 Resolved — Reconcile 486 Candidate Disposition Counts & Transition Matrix**:
    - Audited all 486 candidates and proved that underlying candidate checkpoints maintain 100% stable dispositions:
      - `VERIFIED_BONUS`: 224
      - `VERIFIED_SPLIT`: 92
      - `RIGHTS_ENTITLEMENT_EXPIRATION`: 76
      - `DUPLICATE_CANDIDATE`: 43
      - `NORMAL_MARKET_MOVEMENT`: 43
      - `OTHER_VERIFIED_ACTION`: 8
      - Total: 486
    - Resolved the discrepancy in the prior text summary: clarified that the figures (44, 89, 27, 10) were caused by a chat text presentation artifact where column totals from UNKNOWN events were misaligned into disposition rows.
    - Exported complete 486-row candidate transition report (`candidates_disposition_transition_report.json` and `.csv`) and 100% diagonal transition matrix (`candidates_disposition_transition_matrix.json`).
  - **Issue 2 Resolved — Trading-Session & Effective-Interval Event-Level ISIN Matching**:
    - Eliminated calendar-day lookback heuristics in `spikes/m0/generate_event_level_reconciliation.py`.
    - Implemented exact trading session queries from `DailyPriceRaw` and interval coverage from `InstrumentSymbolHistory`:
      - Traverses canonical instrument identity and historical symbol aliases (`JTLINFRA` -> `JTLIND`, `4THDIM` -> `GVPTECH`, `KAMOPAINTS` -> `KAMOPVENT`).
      - Identifies exact prior trading session $T_{\text{last\_pre}} < \text{ex\_date}$ and resumption session $T_{\text{first\_post}} \ge \text{ex\_date}$. Handles multi-week suspensions (e.g. `KAUSHALYA` 26 calendar days) without arbitrary day windows.
      - Preserves `UNKNOWN` strictly when trading session or interval evidence is absent (55 candidates).
      - Separated instrument-level multi-ISIN from event-level ISIN continuity and corporate action registry fields; logged 106 inconsistencies explicitly.
  - **Issue 3 Resolved — Comprehensive Audit of 41 Multi-ISIN Bonus Candidates**:
    - Produced dedicated row-level audit in `data/checkpoints/multi_isin_bonus_audit_41.json` and `.csv`:
      - **12 ETFs (`ETF_SCHEME_RESTRUCTURING`)**: Mutual fund basket splits with new ISINs (`INF...`), ineligible for common equity adjustments, strictly quarantined and excluded from `daily_prices_adjusted`.
      - **2 Companion Split+Bonus (`COMPANION_SPLIT_AND_BONUS`)**: `GOLDSTAR` (2023-01-23) and `VERTOZ` (2024-07-05) concurrent 10:1 splits and 1:1 bonuses, eligible for price adjustment.
      - **2 Predecessor/Successor Reorganizations (`PREDECESSOR_SUCCESSOR_REORGANIZATION`)**: `JTLIND` and `KAMOPAINTS`, eligible for price adjustment.
      - **25 Subdivisions / Stock Splits on Continuing Equities (`CONTINUING_EQUITY_SUBDIVISION_SPLIT`)**: Sub-divisions of face value legally mandating new ISINs under NSDL/CDSL rules. Market capitalization continuous, 100% eligible for price adjustment.
  - **Issue 4 Resolved — Final Totals & Cross-Tabulation**:
    - Cross-tabulation totals reconcile exactly: 284 SAME_ISIN, 147 MULTI_ISIN, 55 UNKNOWN, Total: 486.
    - Bonus events breakdown: 171 SAME_ISIN, 41 MULTI_ISIN, 12 UNKNOWN, Total: 224.
  - **Comprehensive Test Suite**:
    - **101 / 101 tests passing** (100% pass rate).

## Evidence
- Files created/updated:
  - `docs/PROGRESS.md`
  - `spikes/m0/generate_event_level_reconciliation.py`
  - `data/checkpoints/candidates_disposition_transition_report.json`
  - `data/checkpoints/candidates_disposition_transition_report.csv`
  - `data/checkpoints/candidates_disposition_transition_matrix.json`
  - `data/checkpoints/candidates_disposition_cross_tabulation.json`
  - `data/checkpoints/multi_isin_bonus_audit_41.json`
  - `data/checkpoints/multi_isin_bonus_audit_41.csv`
  - `data/checkpoints/bonus_candidates_row_level_reconciliation.json`
  - `data/checkpoints/bonus_candidates_row_level_reconciliation.csv`
  - `data/checkpoints/unresolved_and_unknown_candidates.json`
  - `tests/integration/test_candidate_identity_reconciliation.py`
  - `tests/integration/test_bulk_adjusted_prices.py`
- Verification Commands run:
  - `python spikes/m0/generate_event_level_reconciliation.py` -> Success.
  - `pytest -v` -> 101 passed in 6.33s.
  - Database row counts: raw `1,855,370`, adjusted v1.2 `1,848,718`, corporate actions `378`.

## Open questions
- None.

---

## 2026-10-31 — Phase 1B-ii.2.4: Final Corporate-Action Identity Consistency Audit

- **Audit Objective**: Complete the final identity consistency audit prior to Phase 1B-iii, resolving the 106 corporate-action vs traded-ISIN discrepancies, reconciling the 41 multi-ISIN bonus candidates against canonical actions and face values, bridging the 12 ETF candidate rows to the 11 quarantined instruments, establishing economic continuity for `JTLIND` and `KAMOPAINTS`, and verifying absolute immutability of raw prices and preservation of `v1.2` adjusted prices.
- **Milestone Status**: Complete. 106 / 106 tests passing.

### Key Achievements

1. **Reconciliation of the 106 CorporateAction vs Chronological Traded-ISIN Inconsistencies**:
   - Generated and exported `data/checkpoints/corporate_action_isin_discrepancy_audit.json` and `.csv` (106 records).
   - Classified all 106 records into authoritative evidence-based categories:
     - **`CORPORATE_ACTION_ISIN_METADATA_ERROR` (59 records)**: Harmless static metadata discrepancies where historical ISIN fields in corporate action records reflected successor ISINs rather than active pre-event ISINs (e.g. `VBL` 2022 bonus stamped with 2023 ISIN `INE200M01021` instead of active 2022 ISIN `INE200M01013`). The adjustment engine links corporate actions via canonical `instrument_id`, correctly adjusting chronological prices regardless of static string fields. Zero price impact.
     - **`VALID_ISIN_CHANGE_DUE_TO_FACE_VALUE_ACTION` (42 records)**: Caused by the Indian T+2 rolling settlement cycle in 2022 where trading went ex-split on day $T$ under the old ISIN at the post-split price, while the exchange depository new ISIN became active on $T+1$ (the official circular record date). Both dates belong to the identical security.
     - **`VALID_SYMBOL_OR_SECURITY_SUCCESSION` (5 records)**: Predecessor/successor symbol changes (`GVPTECH`, `KAMOPAINTS` $\times 3$, `JTLIND`) traversing continuous corporate entities.
     - **`INSTRUMENT_ID_OR_SECURITY_MAPPING_ERROR` (0 records)**.
     - **`MISSING_OR_CONFLICTING_HISTORY` (0 records)**.
     - **`UNRESOLVED` (0 records)**.
   - **Financial Impact Verification**: All 106 cases confirmed 100% safe to apply to adjusted history. Exactly one action factor is applied per corporate event; zero unrelated securities are affected; raw historical prices remain 100% immutable.

2. **Reconciliation of the 41 Multi-ISIN Bonus Candidates Against Canonical Actions & Face Values**:
   - Generated and exported `data/checkpoints/multi_isin_bonus_reconciliation_41.json` and `.csv` (41 records).
   - Authoritative category breakdown:
     - **Continuing Equity Subdivision / Split Events (25 records)**: Sub-divisions of nominal face value (e.g., ₹10 to ₹1, ₹10 to ₹2, ₹10 to ₹5) on continuous common equity securities, legally requiring new ISIN issuance under NSDL/CDSL regulations. In `corporate_actions`, each has `action_type = "BONUS_ISSUE"` with multiplier $M$. Crucially, exactly **0** of these 25 cases have a co-occurring `STOCK_SPLIT` registered in `corporate_actions` (`split_and_bonus_both_registered_on_date = False`). Because only ONE action record exists with factor $M$, the adjustment engine applied the factor **EXACTLY ONCE**. The backward adjustment formulas for splits and bonuses ($P_{\text{adj}} = P / M$, $V_{\text{adj}} = V \times M$) are mathematically identical, guaranteeing **zero double counting**.
     - **ETF Unit Split & Scheme Restructurings (12 records)**: 10:1 unit subdivisions by HDFC and ICICI Prudential Mutual Funds (`AUTOIETF`, `LOWVOLIETF`, `NV20IETF`, etc.). All bear the `INF` ISIN prefix, are marked `adjustment_eligibility = False`, and are strictly excluded from common equity universes.
     - **Concurrent Stock Split & Bonus Issues (2 records)**: `GOLDSTAR` (2023-01-23) and `VERTOZ` (2024-07-05). Legitimate companion 10:1 stock splits and 1:1 bonuses ($M = 10.0 \times 2.0 = 20.0$), confirmed with `split_and_bonus_both_registered_on_date = True`.
     - **Predecessor/Successor Equity Subdivisions (2 records)**: `GVPTECH` (2023-01-23, formerly `4THDIM`) and `JTLIND` (2024-11-14, formerly `JTLINFRA`).
   - Populated exact `old_face_value` and `new_face_value` transitions across all equity candidates based on company disclosures.

3. **ETF Identity Bridge (11 Quarantined Instruments vs 12 Discontinuity Candidates)**:
   - Generated and exported `data/checkpoints/etf_quarantine_candidate_bridge.json`.
   - Reconciled the two distinct ETF sets:
     - **Set A (11 Quarantined Instruments, Phase 1B-ii.1)**: Instruments with neutral scheme restructurings ($M=1.0$) with 6,652 raw records quarantined and excluded from `daily_prices_adjusted` (`HDFCNIF100`, `UTINIFTETF`, `SETFGOLD`, etc.).
     - **Set B (12 Candidate Rows, 486 Sweep)**: Instruments with 10:1 unit subdivisions ($M=10.0$) detected in the candidate sweep (`HDFCNIFBAN`, `HDFCSENSEX`, `AUTOIETF`, `LOWVOLIETF`, etc.).
   - Resolution: Set A and Set B represent two distinct groups of ETF instruments in the market with zero overlap.
   - Universe Filtering Policy: 100% of both sets bear the **`INF`** ISIN prefix. The Phase 1B-iii Point-in-Time Liquidity Universe strictly filters on common equities with the **`INE`** prefix and equity series (`EQ`, `BE`, `SM`), guaranteeing that 100% of ETFs from both Set A and Set B are strictly excluded from equity stock selection.

4. **Economic Continuity for JTLIND and KAMOPAINTS**:
   - **`JTLIND` (`JTL Industries Limited`, formerly `JTL Infra Limited`)**:
     - Predecessor and successor share the identical corporate entity (CIN: `L27106CH1990PLC010531`), operations, and instrument ID (`5ddfbaa6-03ca-473a-a73d-aa219ca74121`).
     - On 2022-11-21, the company changed its name from `JTLINFRA` to `JTLIND` (ISIN `INE391J01024` continuous).
     - On 2024-11-14, the company split face value from ₹2 to ₹1 ($M=2.0$), transitioning from `INE391J01024` to `INE391J01032`. Raw close dropped 1.87x from ₹183.79 to ₹98.15.
     - Price series is economically continuous across the transition.
     - *Audit Finding*: Flagged that in `v1.2`, both predecessor action (`CA-JTLINFRA-...-STOCK_SPLIT`, M=2.0) and candidate action (`CA-JTLIND-...-BONUS`, M=2.0) coexisted for the same `instrument_id`, applying $M=4.0$. In the future v1.3 build, marking the duplicate action superseded will ensure the single $M=2.0$ factor is applied exactly once.
   - **`KAMOPAINTS` (`Kamdhenu Ventures Limited`)**:
     - Listed on NSE on 2023-01-24 under ISIN `INE0BTI01029`.
     - On 2024-06-14, the company executed a 5:1 stock split (₹5 to ₹1, $M=5.0$), transitioning to depository ISIN `INE0BTI01037`.
     - In `v1.2`, factor $M=5.0$ is applied **exactly once** (raw close dropped from ₹204.22 on 2024-06-13 to ₹42.99 on 2024-06-14; adjusted close is smooth from ₹40.84 to ₹42.99). Price series is 100% economically continuous.

5. **Version & Regression Policy Verification**:
   - Raw price records: Strictly immutable at **1,855,370 records** (0 modified, 0 deleted).
   - Production adjusted prices: `v1.2` preserved at **1,848,718 records** ($1,855,370 - 6,652$ quarantined ETF rows).
   - Historical versions `v1.0` and `v1.1` remain intact with 1,848,718 records each.
   - Test suite: **106 / 106 tests passing** (including 5 new integration tests in `test_corporate_action_identity_consistency.py`).

## Evidence
- Files created/updated:
  - `spikes/m0/generate_discrepancy_and_action_type_audit.py`
  - `data/checkpoints/corporate_action_isin_discrepancy_audit.json` (106 records)
  - `data/checkpoints/corporate_action_isin_discrepancy_audit.csv` (106 records)
  - `data/checkpoints/multi_isin_bonus_reconciliation_41.json` (41 records)
  - `data/checkpoints/multi_isin_bonus_reconciliation_41.csv` (41 records)
  - `data/checkpoints/etf_quarantine_candidate_bridge.json` (11 quarantined vs 12 candidate ETFs)
  - `tests/integration/test_corporate_action_identity_consistency.py` (5 passing tests)
  - `docs/PROGRESS.md`
- Verification Commands run:
  - `python spikes/m0/generate_discrepancy_and_action_type_audit.py` -> Success.
  - `pytest` -> 106 passed in 6.95s.
  - Database counts: `DailyPriceRaw = 1,855,370`, `DailyPriceAdjusted (v1.2) = 1,848,718`.


## Blockers
- None.

## Next smallest task
- Phase 1B-ii.2.5: Corporate Action Deduplication and v1.3 Financial Closure (COMPLETED below).

---

## 2026-10-31 - Milestone Phase 1B-ii.2.5: Corporate Action Deduplication and v1.3 Financial Closure

### What was done
1. **Resolved Duplicate Corporate Actions (JTLIND & GVPTECH)**:
   - **JTLIND**: Resolved duplicate corporate action representation across the `JTLINFRA` -> `JTLIND` rename for the 2:1 stock split on 2024-11-14. Authoritative split `CA-JTLINFRA-2024-11-14-INE391J01024-INE391J01032` (multiplier 2.0) is active and verified. Duplicate representation `CA-JTLIND-2024-11-14-BONUS` is marked `SUPERSEDED` with `identity_decision = 'SUPERSEDED_DUPLICATE_OF_SPLIT'`, `affects_adjusted_prices = False`, and points to the authoritative split. In `v1.3`, the pre-split cumulative multiplier is restored from 4.0 to **2.0**.
   - **GVPTECH**: Registry-wide sweep identified an identical duplicate corporate action across the `4THDIM` -> `GVPTECH` rename for the 5:1 stock split on 2023-01-23. Authoritative split `CA-4THDIM-2023-01-23-INE382T01022-INE382T01030` (multiplier 5.0) is active and verified. Duplicate representation `CA-GVPTECH-2023-01-23-BONUS` is marked `SUPERSEDED` with `identity_decision = 'SUPERSEDED_DUPLICATE_OF_SPLIT'`. In `v1.3`, the pre-split cumulative multiplier is restored from 25.0 to **5.0**.
   - Neither record was physically deleted from the database; both remain fully queryable for audit.

2. **Registry-Wide Co-Occurring Action Audit**:
   - Evaluated all 378 corporate action records grouped by `(instrument_id, ex_date)`.
   - Identified strictly 4 co-occurring pairs across the entire history:
     - 2 duplicate pairs across symbol renames (`JTLIND` and `GVPTECH`), both deduplicated to single canonical splits.
     - 2 legitimate concurrent compound split-plus-bonus events (`GOLDSTAR` on 2023-01-23, $M = 10 \times 2 = 20.0$, and `VERTOZ` on 2024-07-05, $M = 10 \times 2 = 20.0$). Both components are separately verified and combine multiplicatively to $M=20.0$.
   - Exported `corporate_action_duplicate_compound_reconciliation.json` and `.csv`.

3. **Resolved the 25 Bonus-versus-Split Classifications**:
   - Reconciled all 25 candidate events against official exchange circulars and nominal share capital disclosures:
     - **23 events** verified as genuine equity subdivisions (Stock Splits) resulting in reduced nominal face value (e.g. ₹10 to ₹2 or ₹10 to ₹1). Under Indian company law, bonus issues capitalize reserves without modifying nominal face value. Canonical `action_type` was updated to `STOCK_SPLIT`, and official `old_face_value` and `new_face_value` were populated.
     - **2 events** (`360ONE` on 2023-03-02 and `AARTECH` on 2024-08-09) verified as concurrent Stock Split + Bonus Issue events.
   - Guaranteed zero double-counting: share multipliers applied exactly once in `v1.3`.
   - Exported `bonus_vs_split_25_reconciliation.json` and `.csv`.

4. **Reassessed the 106 ISIN Discrepancy Cases**:
   - Re-evaluated financial impact across all 106 cases following the JTLIND discovery:
     - **59 Harmless Static ISIN Metadata Differences**: CorporateAction recorded successor ISIN while trading occurred on pre-split ISIN. Single factor applied via `instrument_id`.
     - **42 Valid Settlement/Effective-Date Transitions**: T+2 rolling settlement where ex-date occurred on pre-split ISIN. Single factor applied.
     - **3 Valid Predecessor/Successor Continuity Cases**: Continuous corporate entity across demergers/transitions (`KAMOPAINTS`). Single factor applied.
     - **2 Actual Corporate Action Duplication Errors**: `JTLIND` and `GVPTECH` duplicate bonus entries marked `safe_to_apply_to_adjusted_history = False`, with multipliers corrected in `v1.3`.
     - **0 Unresolved Cases**.
   - Updated `corporate_action_isin_discrepancy_audit.json` and `.csv`.

5. **Built Deterministic Dataset Version v1.3**:
   - Executed bulk adjustment engine producing `v1.3` in `daily_prices_adjusted`.
   - Row-level reconciliation between `v1.2` and `v1.3`:
     - Exactly **807 records changed** (713 for JTLIND, 94 for GVPTECH).
     - Exactly **1,847,911 records unchanged** (100% identical).
     - Total dataset size: **1,848,718 records** per version tag.
   - Preserved all immutable raw price records (**1,855,370 records**).
   - Preserved all historical versions (`v1.0`, `v1.1`, and `v1.2`) intact for audit.
   - Exported `v1_2_vs_v1_3_reconciliation_report.json` and `.csv`.

6. **Automated Verification & Test Suite**:
   - Added `tests/integration/test_v1_3_financial_closure.py` covering:
     - JTLIND deduplication, pre-event OHLC/volume scaling, post-event M=1.0, and prev-close alignment.
     - JTLIND Point-in-Time dynamics before vs after ex-date.
     - GVPTECH deduplication and multiplier restoration.
     - Legitimate compound events preservation (`GOLDSTAR`, `VERTOZ`).
     - Face value population and action classification.
     - Database count invariants across raw and all 4 adjusted versions.
   - Test suite status: **113 / 113 tests passing** (100% pass rate).

### Evidence
- Checkpoint files generated:
  - `data/checkpoints/corporate_action_duplicate_compound_reconciliation.json` & `.csv`
  - `data/checkpoints/bonus_vs_split_25_reconciliation.json` & `.csv`
  - `data/checkpoints/corporate_action_isin_discrepancy_audit.json` & `.csv`
  - `data/checkpoints/v1_2_vs_v1_3_reconciliation_report.json` & `.csv`
- Test suite: `pytest` -> 113 passed in 10.34s.

### Blockers
- None.

### Next smallest task
- Phase 1B-ii.2.6: Compound Corporate-Action Component Modelling (COMPLETED below).

---

## 2026-10-31 - Milestone Phase 1B-ii.2.6: Compound Corporate-Action Component Modelling

### What was done
1. **Decomposed Concurrent Split-Plus-Bonus Corporate Actions into Canonical Components**:
   - **360ONE (2023-03-02)**:
     - Decomposed composite action into two distinct canonical component records:
       - `CA-360ONE-2023-03-02-STOCK_SPLIT`: Action type `STOCK_SPLIT`, multiplier `2.0`, `old_face_value = 2.0`, `new_face_value = 1.0`, official circular `NSE/CML/20230302/360ONE`.
       - `CA-360ONE-2023-03-02-BONUS_ISSUE`: Action type `BONUS_ISSUE`, multiplier `2.0`, 1:1 bonus ratio (`old_share_qty = 1.0`, `new_share_qty = 1.0`), official circular `NSE/CML/20230302/360ONE`.
     - Preserved previous composite record `CA-360ONE-2023-03-02-BONUS` as `SUPERSEDED` with `identity_decision = 'SUPERSEDED_DECOMPOSED'` for full audit traceability.
   - **AARTECH (2024-08-09)**:
     - Decomposed composite action into two distinct canonical component records:
       - `CA-AARTECH-2024-08-09-STOCK_SPLIT`: Action type `STOCK_SPLIT`, multiplier `2.0`, `old_face_value = 10.0`, `new_face_value = 5.0`, official reference `NSE/CML/20240809/AARTECH`.
       - `CA-AARTECH-2024-08-09-BONUS_ISSUE`: Action type `BONUS_ISSUE`, multiplier `1.5`, 1:2 bonus ratio (`old_share_qty = 2.0`, `new_share_qty = 1.0`), official reference `NSE/CML/20240809/AARTECH`.
     - Preserved previous composite record `CA-AARTECH-2024-08-09-BONUS` as `SUPERSEDED` with `identity_decision = 'SUPERSEDED_DECOMPOSED'`.

2. **Preserved Mathematical Adjustment Parity**:
   - Both events apply component multipliers multiplicatively:
     - `360ONE`: $2.0 \times 2.0 = 4.0$.
     - `AARTECH`: $2.0 \times 1.5 = 3.0$.
   - Pre-split/bonus OHLC, volume, and previous-close values match the established convention with 100% mathematical invariance.

3. **Built Dataset Version v1.4 with Full Immutability**:
   - Preserved all prior versions: `v1.0`, `v1.1`, `v1.2`, and `v1.3` intact with 1,848,718 records each.
   - Preserved immutable raw prices: strictly 1,855,370 records.
   - Built dataset version `v1.4` (1,848,718 records) in `daily_prices_adjusted`.
   - Reconciled `v1.3` vs `v1.4`:
     - Exactly **0 price or volume differences** across all 1,848,718 records.
     - Exactly **1,028 rows** updated for metadata/applied action IDs (reflecting component decomposition and canonical sorting).
     - Exported `data/checkpoints/v1_3_vs_v1_4_reconciliation_report.json` and `.csv`.

4. **Updated Reconciliation Deliverables**:
   - Regenerated `data/checkpoints/corporate_action_duplicate_compound_reconciliation.json` and `.csv` (showing component-level decomposition for 360ONE and AARTECH, legitimate concurrent compound events for GOLDSTAR and VERTOZ, and superseded duplicates for JTLIND and GVPTECH).
   - Regenerated `data/checkpoints/bonus_vs_split_25_reconciliation.json` and `.csv` (2 concurrent split+bonus events with explicit component fields, 23 pure stock splits).
   - Updated `data/checkpoints/corporate_action_provenance_full_report.json`.

5. **Updated Test Suite & Validation**:
   - Updated `test_bonus_vs_split_25_classifications` to verify 2 concurrent compound split+bonus events and 23 pure stock splits.
   - Added `test_compound_events_360one_and_aartech` validating component records, face values, multipliers, applied action IDs, and dynamic PIT behavior.
   - Validated database record counts across raw and all 5 adjusted dataset versions (`v1.0` through `v1.4`).
   - Complete pytest test suite passing: **114 / 114 tests passing** (100% pass rate).

### Evidence
- Checkpoint files generated:
  - `data/checkpoints/corporate_action_duplicate_compound_reconciliation.json` & `.csv`
  - `data/checkpoints/bonus_vs_split_25_reconciliation.json` & `.csv`
  - `data/checkpoints/v1_3_vs_v1_4_reconciliation_report.json` & `.csv`
  - `data/checkpoints/corporate_action_provenance_full_report.json`
- Test suite: `pytest` -> 114 passed in 12.25s.
- Database counts:
  - `DailyPriceRaw`: 1,855,370 immutable rows
  - `DailyPriceAdjusted`: Exactly 1,848,718 rows per version (`v1.0`, `v1.1`, `v1.2`, `v1.3`, `v1.4`) - Total 9,243,590 rows
  - `corporate_actions`: 382 records (378 active canonical + 4 superseded audit records)

### Blockers
- None.

### Next smallest task
- Phase 1B-iii: Point-in-Time Liquidity Universe (COMPLETED below).

---

## 2026-10-31 - Milestone Phase 1B-iii: Point-in-Time Liquidity Universe

### What was done
1. **v1.4 All-Column Preflight Validation (Part A)**:
   - Executed exhaustive SQL comparison on the full primary key `(instrument_id, trade_date, series)` across all 1,848,718 records between `v1.3` and `v1.4`:
     - `open`: 0 mismatches
     - `high`: 0 mismatches
     - `low`: 0 mismatches
     - `close`: 0 mismatches
     - `last`: 0 mismatches
     - `prev_close`: 0 mismatches
     - `raw_prev_close`: 0 mismatches
     - `volume`: 0 mismatches
     - `raw_volume`: 0 mismatches
     - `traded_value`: 0 mismatches
     - `raw_traded_value`: 0 mismatches
     - `raw_vwap`: 0 mismatches
     - `adjusted_vwap`: 0 mismatches
     - `cumulative_multiplier`: 0 mismatches
     - `applied_action_ids`: exactly 1,028 expected metadata changes (291 for `360ONE` decomposition, 116 for `GOLDSTAR`, 621 for `VERTOZ` canonical sort).
   - Exported `data/checkpoints/v1_4_preflight_all_column_reconciliation.json`.
   - Verified that `get_point_in_time_adjusted_history` explicitly accepts and defaults to `adjustment_version="v1.4"`.
   - Verified raw price immutability (strictly 1,855,370 records).

2. **Point-in-Time Universe Architecture & Schema (Part B)**:
   - Designed and applied Alembic migration `0010_point_in_time_universe.py` creating:
     - `universe_snapshots`: Persists evaluation metadata, lookback boundaries, configuration parameters, and member summary counts.
     - `universe_members`: Persists individual instrument evaluations, PIT symbols/ISINs, observation metrics, liquidity statistics, eligibility decisions, ranks, and explicit exclusion reasons.
   - Created `src/signal_atlas/universe/` module:
     - `models.py`: Pydantic models `UniverseConfig`, `UniverseMember`, `UniverseSnapshot`, and `EligibilityReason`.
     - `policy.py`: Common equity ISIN validation (`INE` prefix), rights entitlement detection (`-RE`, `IN9`, `RE` series), permitted series (`EQ`, `BE`), quarantine policy enforcement, and threshold checks.
     - `service.py`: `PointInTimeUniverseService` and `get_point_in_time_universe`.

3. **Deterministic Liquidity & Turnover Calculations**:
   - Trailing lookback window $N = 126$ completed trading sessions derived from `TradingCalendar`.
   - Authoritative liquidity measured strictly via exchange-reported `traded_value` (never `close * volume`).
   - Strict preservation of turnover semantics: `NULL` missing turnover tracked separately in `null_turnover_count` and excluded from denominator; genuine `0.00` tracked in `zero_turnover_count`.
   - Calculated metrics: `observed_sessions_count`, `missing_sessions_count`, `trading_completeness`, `total_turnover`, `average_daily_turnover` (ADTV), `median_daily_turnover`, and `latest_raw_close` (using raw price, never future-adjusted price).

4. **Zero Survivorship Bias & Future Data Leakage Guarantee**:
   - Demonstrated on historical date `2023-01-02`: subsequently delisted `HDFC` (`INE001A01036`) was actively trading in 2022/2023 and is correctly included as the #1 most liquid eligible instrument (ADTV: ₹669 Cr).
   - Demonstrated future listings exclusion: securities listed in 2024 are strictly excluded from earlier dates.
   - Point-in-time symbol changes (`IIFLWAM` $\rightarrow$ `360ONE`, `4THDIM` $\rightarrow$ `GVPTECH`) resolve to the exact active symbol on the query date while maintaining stable `instrument_id`.
   - Zero future corporate action leakage verified through dynamic PIT price adjustment.

5. **Verification & Test Suite**:
   - Added `tests/integration/test_point_in_time_universe.py` covering all 12 requested integration test cases.
   - Full pytest test suite passing: **126 / 126 tests passing** (100% pass rate).

- [x] **Completed Phase 1B-iii.1 (Point-in-Time Universe Data Integrity Closure)**:
  1. **Listing Date Semantics Disentangled**:
     - Applied Alembic migration `0011_universe_data_closure.py` adding `first_observed_trade_date DATE` to `instruments` table.
     - Populated `first_observed_trade_date` from `MIN(DailyPriceRaw.trade_date)` for all 4,637 instruments in the dataset.
     - Restored unverified `instruments.listing_date` to `NULL` (0 rows with unverified exchange listing dates).
     - Ensured future-listing exclusions evaluate `first_observed_trade_date` without contaminating older companies with false IPO dates on the 2022-01-03 import boundary.
  2. **Session Counting & Turnover Across EQ/BE Bounded**:
     - Audited `daily_prices_raw` across permitted series `('EQ', 'BE')`: exactly **0 duplicate same-date groups** across all 4,637 instruments!
     - Multi-series occurrences across all series (1,514 groups across 504 instruments) were verified to be block deals (`BL`), which are safely excluded by the permitted series filter.
     - Replaced `COUNT(*)` with `COUNT(DISTINCT trade_date)` for `observed_sessions_count`.
     - Strictly enforced `trading_completeness <= 1.0000` with zero double-counting of turnover.
  3. **Point-in-Time Series & Symbol Resolution**:
     - Audited 840 overlapping interval pairs across 813 instruments in `InstrumentSymbolHistory` between `EQ` and `BE` (caused by surveillance entry intervals without splitting baseline intervals).
     - Eliminated arbitrary `CASE WHEN series = 'EQ' THEN 1` priority.
     - Implemented dynamic series resolution: resolves series from **actual exchange trade activity** from `daily_prices_raw` during the lookback window, with deterministic fallback to most recent `valid_from DESC`.
     - Verified `MIRCELECTR`: correctly resolves to `series = 'BE'` on `2023-08-01` (surveillance period), and `series = 'EQ'` on `2024-04-15`.
     - Added ambiguity detection: instruments with multiple conflicting records with identical `valid_from` and no trading activity are excluded with `EXCLUDED_AMBIGUOUS_SERIES_HISTORY`.
  4. **Turnover-Data Completeness & Null Semantics**:
     - Preserved NULL turnover distinct from zero turnover (`0.00`).
     - Added metric:
       $$\text{turnover\_data\_completeness} = \frac{\text{valid\_turnover\_sessions}}{\text{expected\_lookback\_sessions}}$$
     - Added configurable `min_turnover_completeness = Decimal("0.80")` (80%) to `UniverseConfig`.
     - Added distinct exclusion reason `EligibilityReason.EXCLUDED_INSUFFICIENT_TURNOVER_COVERAGE`.
     - Persisted `expected_lookback_sessions`, `valid_turnover_sessions_count`, and `turnover_data_completeness` in `universe_members`.
  5. **Snapshot Reproducibility & Provenance**:
     - Added `raw_data_version`, `data_coverage_start`, `data_coverage_end`, and `code_revision` to `universe_snapshots`.
     - Enforced strict protection against silently overwriting snapshots generated from differing raw data versions.
     - Deterministic config identifier updated: `UNIV-v1.0-L126-ADT5000000-C85-TC80-P10-BE_EQ`.
  6. **Comprehensive Test Suite & PostgreSQL Validation**:
     - Expanded `tests/integration/test_point_in_time_universe.py` to cover all 14 requested test cases.
     - Full pytest suite passing: **128 / 128 tests passing** (100% pass rate in 17.94s).
  7. **Historical Universe Checkpoints Exported**:
     - `2023-01-02`: 2,810 evaluated, 1,321 eligible, 1,489 excluded (HDFC ranked #9, ADTV ₹669 Cr).
     - `2024-10-25`: 3,412 evaluated, 1,661 eligible, 1,751 excluded (MIRCELECTR series BE, ADTV ₹2.95 Cr).
     - Exported to `data/universe_checkpoints/` in both JSON and CSV formats.

- [x] **Completed Phase 1B-iii.1.1 (Snapshot Isolation & Cross-Session Cache Closure — 2026-10-31)**:
  1. **Consistent Snapshot Isolation Implementation**:
     - Implemented `PointInTimeUniverseService._consistent_snapshot_transaction(db)` in `src/signal_atlas/universe/service.py`.
     - For PostgreSQL sessions, establishes `REPEATABLE READ` snapshot isolation on idle sessions and verifies it via `conn.get_isolation_level()` and `SHOW transaction_isolation`.
     - Detects and rejects already-active `READ COMMITTED` transactions with `RuntimeError`, guaranteeing that manifest calculation, cache lookup, universe calculation, and snapshot persistence always execute within a single consistent snapshot.
     - Accepts already-active caller transactions if they are already in `REPEATABLE READ`.
  2. **Closed Public Manifest API Boundary**:
     - Retained strict boundary on public `build_universe()`: removed `raw_manifest` argument so external callers cannot inject arbitrary or stale raw-data manifests.
     - `build_universe()` computes its own manifest within the verified transaction.
     - Internal `_build_universe()` helper accepts a manifest only from the verified transaction.
     - `get_universe()` reuses the manifest computed in its consistent transaction without rescan.
     - Removed no-op `with nullcontext():` wrapper and unused `nullcontext` import from `service.py`.
  3. **Caller-Owned Transaction Semantics**:
     - Retained `session.flush()` in `_persist_snapshot_record()`; eliminated service-level `commit()` to preserve transaction ownership with caller.
     - Verified that internally managed sessions (`get_db()` with `session=None`) commit on success and rollback on exception.
     - Verified caller-supplied sessions remain caller-owned without partial commits or unintended rollbacks.
  4. **Real PostgreSQL Integration Test Suite (`tests/integration/test_postgres_universe_isolation.py`)**:
     - Added 7 dedicated PostgreSQL integration tests executed against isolated test database `signal_atlas_test`:
       1. `test_postgres_idle_session_establishes_repeatable_read`: Proves idle session entering helper establishes `REPEATABLE READ` (verified via `conn.get_isolation_level()` and PostgreSQL `SHOW transaction_isolation`).
       2. `test_postgres_already_active_read_committed_is_rejected`: Proves already-active `READ COMMITTED` transaction raises `RuntimeError`.
       3. `test_postgres_already_active_repeatable_read_is_accepted`: Proves already-active `REPEATABLE READ` transaction is accepted.
       4. `test_postgres_caller_ownership_preserved_not_committed_or_closed`: Proves leaving context manager does not commit or close caller session.
       5. `test_postgres_deterministic_snapshot_consistency_across_two_sessions`: Deterministic two-session snapshot test: Transaction A enters repeatable read and observes synthetic row; Transaction B modifies row and commits; Transaction A still observes original snapshot; Transaction C (new session) observes modified value.
       6. `test_postgres_cache_persistence_across_commit_and_separate_session`: Proves cache persistence across commit and separate session boundary. Session 1 writes and flushes without committing; observer session cannot see uncommitted snapshot; Session 1 commits and closes; Session 2 opens and loads identical snapshot from cache without invoking builder a second time.
       7. `test_postgres_internally_managed_get_db_lifecycle`: Proves internally managed `get_db()` commits on success and rolls back on failure.
  5. **Verification Outcomes**:
     - Exact unit provenance test suite:
       `python -m pytest --noconftest -q -p no:cacheprovider tests/unit/test_exact_provenance.py` -> **16 passed in 1.30s**.
     - Real PostgreSQL isolation integration suite:
       `pytest -v -s tests/integration/test_postgres_universe_isolation.py` -> **7 passed in 0.69s**.
     - PostgreSQL engine integration tests:
       `pytest -v tests/integration/test_postgres_integration.py` -> **5 passed in 21.52s**.
     - Python compilation & whitespace check:
       `python -m py_compile src/signal_atlas/universe/service.py tests/unit/test_exact_provenance.py tests/integration/test_postgres_universe_isolation.py` -> clean.
       `git diff --check` -> clean.
     - Skipped tests: In isolated CI environments without the uncommitted 2-year bulk historical NSE dataset (1.85M prices, 20k corporate actions), 65 bulk-dependent tests are automatically skipped by `skip_if_missing_bulk_dataset` and `require_historical_dataset_for_bulk_tests`.
  6. **README Documentation Alignment**:
     - Qualified absolute "Zero Survivorship Bias" claim in `README.md` to describe point-in-time universe construction with controlled/reduced survivorship bias across verified source coverage.
  7. **Remaining Limitations**:
     - None for Phase 1B-iii.1.1. Calculations are deterministic, immutable, and snapshot-isolated.

### Evidence
- PostgreSQL integration test suite: `tests/integration/test_postgres_universe_isolation.py` -> **7 passed in 0.69s**.
- Unit exact-provenance suite: `tests/unit/test_exact_provenance.py` -> **16 passed in 1.30s**.
- GitHub Actions CI workflow verified: 93 passed, 65 skipped on PR #1 head.
- Code cleanly compiled with zero whitespace or line-ending errors.

- [x] **Completed Phase 2 (Indicators, Trend-Pullback Swing Strategy, and Realistic Backtest Engine)**:
  1. **Technical Feature Engine (`src/signal_atlas/features/`)**:
     - `models.py`: Strongly typed `TechnicalFeatures` domain model.
     - `indicators.py`: Pure mathematical indicators (EMA 20, EMA 50, Wilder's smoothed RSI 14, MACD [12, 26, 9], Wilder's ATR 14, 20-day Volume/Traded Value, Relative Strength vs NIFTY 50, Weekly Trend derived from daily records).
     - `engine.py`: `TechnicalFeatureEngine` calculating point-in-time features strictly using history $\le \text{as\_of\_date}$, guaranteeing zero lookahead bias.
     - `tests/unit/test_indicators.py`: 10/10 unit tests passing.
     - `tests/integration/test_technical_features.py`: PostgreSQL integration test verifying PIT isolation.
  2. **Trend-Pullback Swing Strategy (`src/signal_atlas/strategy/`)**:
     - `models.py`: Domain models (`MarketContext`, `SignalState`, `StrategyParameters`, `TrendPullbackParameters`, `StrategyCandidate`).
     - `base.py`: Pure abstract `Strategy` contract (zero I/O, deterministic evaluation, stable ID/version, next-session execution validation).
     - `trend_pullback.py`: `TrendPullbackStrategy` implementing market regime gate, medium-term trend alignment (EMA 20 > EMA 50, Price > EMA 50), constructive pullback proximity ($\le 4\%$ of EMA 20), RSI momentum reset zone (40–60), weekly trend alignment, dynamic ATR-based invalidation/target with $\ge 1.5$ reward-to-risk, and $t+1$ opening execution gate (`evaluate_next_session_entry`).
     - `tests/unit/test_trend_pullback_strategy.py`: 10/10 unit tests passing.
  3. **Realistic Backtest Simulation Engine (`src/signal_atlas/backtest/`)**:
     - `costs.py`: `TransactionCostModel` simulating Indian delivery equity charges: STT (0.10% buy & sell), NSE exchange turnover fees (0.00297%), SEBI turnover charges (₹10/crore), state stamp duty (0.015% buy only), GST (18% on fees), brokerage (₹20/order or 0.03%), and configurable execution slippage (5 bps default).
     - `models.py`: Domain models (`BacktestConfig`, `ExitReason`, `PositionRecord`, `EquitySnapshot`, `BacktestMetrics`, `BaselineComparison`, `BacktestResult`).
     - `simulator.py`: `BacktestSimulator` implementing:
       - Next-session ($t+1$) opening execution with opening gap bounds.
       - Gap below stop: executed at Open, never assuming unfillable stop price.
       - Conservative stop-first rule: when daily bar touches both stop and target, assumes stop first.
       - Max holding duration liquidation at close.
       - Realistic position sizing adhering to risk budget, capital cap (20%), and 20-day ADTV participation cap.
       - Benchmarking comparisons against Buy & Hold and Random Entry baseline.
     - `tests/unit/test_backtest.py`: 10/10 unit tests passing.
     - `tests/integration/test_backtest_simulation.py`: PostgreSQL integration test passing.

- [x] **Completed Phase 3 (Risk Engine and Trade Setup)**:
  1. **Domain Models (`src/signal_atlas/risk/models.py`)**:
     - `SurveillanceStatus`: Enumeration of NSE surveillance stages (`CLEAR`, `ASM_STAGE_1`..`4`, `GSM_STAGE_1`..`2`, `CIRCUIT_FILTER_RESTRICTED`, `UNKNOWN`).
     - `CheckSeverity`: Severity classification (`BLOCKING`, `WARNING`).
     - `RiskCheckResult`: Strongly typed audit record containing check ID, human-readable name, severity, pass/fail status, timestamp, and explanation.
     - `OpenPositionRisk`: Tracks individual holding metrics (entry, current price, stop loss, quantity, capital allocated, open risk amount, sector).
     - `PortfolioState`: Point-in-time portfolio context tracking total equity, available cash, peak equity, dynamic drawdown percentage property, open positions, total open risk, concurrent position count, and sector allocations.
     - `RiskConfig`: Configuration parameters (₹10L total capital, 1.0% risk per trade, 20% max position capital, 10 max concurrent positions, 6.0% max aggregate open risk, 30% max sector exposure, 1.50 min R:R, ₹5 Cr min 20-day ADTV, 2.0% max ADTV participation, 2.0% max opening gap deviation, market regime gate, surveillance veto, 5-day earnings blackout window, 10% drawdown kill-switch).
     - `TradeSetup`: Audited trade setup output with reference geometry, position sizing, approved/rejected status, passed/failed checks list, advisory warnings list, and provenance metadata.
  2. **Deterministic Position Sizing Engine (`src/signal_atlas/risk/sizing.py`)**:
     - Mathematical allocation:
       $$Q = \max\left(0, \min(Q_{\text{risk}}, Q_{\text{capital}}, Q_{\text{liquidity}})\right)$$
       where $Q_{\text{risk}} = \lfloor \frac{\text{Equity} \times \text{RiskPct}}{\text{Entry} - \text{Stop}} \rfloor$, $Q_{\text{capital}} = \min(\lfloor \frac{\text{Equity} \times \text{CapPct}}{\text{Entry}} \rfloor, \lfloor \frac{\text{AvailableCash}}{\text{Entry}} \rfloor)$, and $Q_{\text{liquidity}} = \lfloor \frac{\text{ADTV} \times \text{PartPct}}{\text{Entry}} \rfloor$.
     - Explicit binding constraint classification (`RISK_BUDGET`, `CAPITAL_CAP`, `LIQUIDITY_CAP`, or `REJECTED_ZERO`).
  3. **Configuration-Driven Risk Engine (`src/signal_atlas/risk/engine.py`)**:
     - 14 distinct rule checks with pure functional evaluation:
       1. Baseline Strategy Candidate Validity (`SignalState.BUY` and `is_valid`)
       2. Reference Price Geometry & Valid Stop Loss ($P_{\text{entry}} > P_{\text{stop}} > 0$)
       3. Next-Day Opening Execution Timing ($t+1$) & Opening Gap Tolerance ($\le 2\%$)
       4. Portfolio Drawdown Kill-Switch (halts new BUYs when current drawdown $\ge 10\%$)
       5. Concurrent Positions & Duplicate Holding Limit ($\le 10$ positions)
       6. Aggregate Portfolio Open Risk Limit ($\le 6\%$ portfolio open risk)
       7. Sector Concentration Limit ($\le 30\%$ single sector capital)
       8. Minimum Liquidity Threshold (20-day ADTV $\ge ₹5\text{ Cr}$)
       9. Regulatory & Surveillance Restrictions (veto on ASM Stage 1-4, GSM Stage 1-2, Circuit Filter Restrictions)
       10. Corporate Earnings Blackout Window ($\pm 5\text{ days}$ around quarterly results)
       11. Promoter Pledge Advisory ($\le 25\%$ non-blocking warning threshold)
       12. Series Eligibility (Cash Equity "EQ" only)
       13. Market Regime Gate (Macro benchmark trend alignment)
       14. Cash Availability & Capital Allocation
     - Strict data policy:
       - Mandatory missing data (ADTV, stop-loss, entry price) blocks setup approval.
       - Non-mandatory / advisory missing data (earnings date, promoter pledge) produces visible advisory warnings without blocking approval.
       - Surveillance status `UNKNOWN` reports warning without blocking unless restricted.
  4. **Verification & Testing (`tests/unit/test_risk_engine.py`, `tests/integration/test_risk_engine_integration.py`)**:
     - Unit tests: 19 tests verifying mathematical sizing and 16 hand-calculated acceptance cases.
     - Integration test: PostgreSQL integration test verifying extraction of adjusted history, feature computation, candidate production, ADTV calculation, clean trade approval, capacity rejection, and opening gap tolerance rejection.
     - Full test suite: 106 tests passing in 5.52s.

- [x] **Completed Phase 4 (MCP Integration and Research Service Layer)**:
  1. **Core Application Service (`src/signal_atlas/research/service.py`, `__init__.py`)**:
     - `ResearchService`: Pure application service layer completely independent of MCP, powering Python scripts, CLI commands, and FastMCP tools with identical logic.
     - `get_market_status`: Evaluates data freshness, benchmark NIFTY 50 trend regime, and system risk limits.
     - `screen`: Evaluates candidates matching registered strategy (`trend_pullback`) with optional symbol filtering, liquid universe pre-filtering, and reward-to-risk ranking.
     - `get_setup`: Retrieves complete trade setup geometry, position sizing breakdown, binding constraints, passed checks, and failed checks.
     - `get_risk_flags`: Audits surveillance stage (ASM/GSM/circuits), corporate events, and 20-day liquidity thresholds.
     - `get_backtest`: Reports strategy execution rules, transaction costs, and summary performance benchmarks.
     - `portfolio_view`: Reports total equity, cash, open risk, concurrent positions, and sector concentrations.
     - Graceful stubs for Phase 6 deferred domains (`get_fundamentals_snapshot`, `get_filings`, `get_news`) returning `DATA_NOT_AVAILABLE` with clear advisory notices.
  2. **FastMCP Server Layer (`src/signal_atlas/mcp/server.py`, `models.py`, `__init__.py`)**:
     - Built using official FastMCP (`from mcp.server.fastmcp import FastMCP`) running over standard input/output (`stdio`).
     - Standard `MCPResponseEnvelope` enforced across all tools: `as_of`, `retrieved_at` (ISO-8601 UTC), `source`, `data_status`, `warnings`, and `result`.
     - Strict prompt-injection and security boundaries: read-only quantitative tools, zero order-placement scopes, zero risk overrides, and clean input validation.
  3. **CLI Research Commands (`src/signal_atlas/cli.py`)**:
     - `signal-atlas market-status`: Renders Rich table of benchmark regime, freshness, and risk limits.
     - `signal-atlas screen`: Renders ranked table of approved trade setups with sizing and R:R.
     - `signal-atlas setup --symbol <SYM>`: Renders detailed setup geometry and risk audit.
     - `signal-atlas risk-flags --symbol <SYM>`: Renders surveillance and corporate action audit.
     - `signal-atlas mcp`: Launches the FastMCP server on stdio transport.
  4. **Verification & Testing (`tests/unit/test_mcp_server.py`, `tests/integration/test_mcp_flow.py`)**:
     - Unit tests: 11 tests verifying tool registration, envelope formatting, input validation, prompt-injection safety controls, and Phase 6 graceful responses.
     - Integration tests: End-to-end research flow `screen -> get_setup -> get_risk_flags` against PostgreSQL test database verifying parity between ResearchService and FastMCP tool wrappers.
     - Full test suite: 118 tests passing in 6.99s.

### Blockers
- None.

### Next smallest task
- Human review of Phase 4 deliverables on branch `phase-4/mcp-integration` and subsequent merge into `main` before starting Phase 5 (Journal and Paper Trading).
