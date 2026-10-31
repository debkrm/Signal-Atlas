# ADR 0006: Phase 1B-ii.0 Canonical Corporate Action Registry and Verification

## Status
Approved / Implemented (Awaiting Human Review for Phase 1B-ii Adjustment Engine Authorization)

## Context
Following the review of Phase 1B-i.3 (historical data integrity closure), the raw historical dataset was accepted (743/743 trading sessions, 1.855M rows, 27 preserved quarantine records, 43 reconciled holidays).

However, a critical review of the preliminary ISIN identity classification revealed that heuristic price-ratio classification had produced discrepancies:
1. **HAL**: Misclassified in text as 5:1 split; verified official NSE circular specifies a **2:1 split** (FV ₹10 to ₹5, multiplier 2.0).
2. **NESTLEIND**: Misclassified in text as 5:1 split; verified official NSE circular specifies a **10:1 split** (FV ₹10 to ₹1, multiplier 10.0).
3. **RITES**: Misclassified as a split; verified official record specifies a **1:1 bonus issue** in September 2024 (multiplier 2.0, face value and ISIN unchanged).
4. **POLYCAB**: Erroneously claimed as a 10:1 split in prior text; investor disclosures confirm equity face value is ₹10 and no split event ever occurred.
5. **152 vs 154 Discrepancy**: Prior report cited 152 multi-ISIN instruments and 154 transitions without explicitly explaining the mathematical distinction.

Before implementing any price adjustment calculations, Phase 1B-ii.0 was mandated to construct a canonical, verified corporate-action event registry with authoritative circular provenance, exact share multipliers, separate concurrent event modeling, and explicit identity decisions.

---

## 1. Resolution of the 152 vs 154 Discrepancy

The structural and mathematical distinction between instruments and transitions across the 2022–2024 dataset is now formally established:

| Category | Count | Structural Definition |
| :--- | :---: | :--- |
| **Unique Multi-ISIN Instruments** | **152** | Financial instruments in `instruments` with $> 1$ distinct ISIN in Bhavcopies |
| **Instruments with exactly 2 ISINs** | **150** | Single transition between two sequential ISINs ($150 \times 1 = \mathbf{150}$ transitions) |
| **Instruments with exactly 3 ISINs** | **2** | Two sequential transitions ($2 \times 2 = \mathbf{4}$ transitions) |
| **Total Pairwise ISIN Transitions** | **154** | $\mathbf{150 + 4 = 154}$ pairwise old-to-new transition edges |
| **Canonical Corporate Action Events** | **156** | 154 transition events + 1 decomposed bonus (Vertoz) + 1 non-ISIN-changing bonus (RITES) |

### The Two 3-ISIN Instruments
1. **Varun Beverages Limited (`VBL`)**:
   - `INE200M01013` $\rightarrow$ `INE200M01021`: 2:1 stock split on 2023-06-15 (FV ₹10 to ₹5, multiplier 2.0, Circular `NSE/CML/2023/382`).
   - `INE200M01021` $\rightarrow$ `INE200M01039`: 5:2 stock split on 2024-09-12 (FV ₹5 to ₹2, multiplier 2.5, Circular `NSE/CML/2024/630`).
2. **Servotech Power Systems Limited (`SERVOTECH`)**:
   - `INE782X01017` $\rightarrow$ `INE782X01025`: 5:1 stock split on 2023-02-03 (FV ₹10 to ₹2, multiplier 5.0, Circular `NSE/CML/2023/79`).
   - `INE782X01025` $\rightarrow$ `INE782X01033`: 2:1 stock split on 2023-07-28 (FV ₹2 to ₹1, multiplier 2.0, Circular `NSE/CML/2023/505`).

---

## 2. Investigation and Correction of Disputed Classifications

All disputed cases were investigated against exchange circulars and daily prices in PostgreSQL:

| Security | Correct Action Type | Ex-Date | Multiplier | Old FV $\rightarrow$ New FV | Old ISIN $\rightarrow$ New ISIN | Authoritative Circular | Verification Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| **HAL** | `STOCK_SPLIT` | 2023-09-28 | **2.0** | ₹10 $\rightarrow$ ₹5 | `INE066F01012` $\rightarrow$ `INE066F01020` | `NSE/CML/2023/668` | `VERIFIED` |
| **NESTLEIND** | `STOCK_SPLIT` | 2024-01-05 | **10.0** | ₹10 $\rightarrow$ ₹1 | `INE239A01016` $\rightarrow$ `INE239A01024` | `NSE/CML/2023/889` | `VERIFIED` |
| **TATASTEEL** | `STOCK_SPLIT` | 2022-07-28 | **10.0** | ₹10 $\rightarrow$ ₹1 | `INE081A01012` $\rightarrow$ `INE081A01020` | `NSE/CML/2022/33` | `VERIFIED` |
| **RITES** | `BONUS_ISSUE` | 2024-09-20 | **2.0** | ₹10 $\rightarrow$ ₹10 | `INE320J01015` $\rightarrow$ `INE320J01015` | `NSE/CML/2024/645` | `VERIFIED` |
| **POLYCAB** | *No Event* | N/A | N/A | ₹10 $\rightarrow$ ₹10 | `INE455K01017` | Excluded (no split) | `EXCLUDED` |
| **VERTOZ (Split)** | `STOCK_SPLIT` | 2024-07-05 | **10.0** | ₹10 $\rightarrow$ ₹1 | `INE188Y01015` $\rightarrow$ `INE188Y01023` | `NSE/CML/2024/491` | `VERIFIED` |
| **VERTOZ (Bonus)** | `BONUS_ISSUE` | 2024-07-05 | **2.0** | ₹1 $\rightarrow$ ₹1 | `INE188Y01015` $\rightarrow$ `INE188Y01023` | `NSE/CML/2024/492` | `VERIFIED` |

### Architectural Insights & Corroborating Price Ratios
- **HAL**: Cum-close ₹3,837.70 on 2023-09-27 $\rightarrow$ Ex-open ₹1,934.80 on 2023-09-28 ($P_{\text{cum}} / P_{\text{ex}} = 1.983 \approx 2.00$). Confirmed 2:1 split.
- **NESTLEIND**: Cum-close ₹27,116.40 on 2024-01-04 $\rightarrow$ Ex-open ₹2,754.00 on 2024-01-05 ($P_{\text{cum}} / P_{\text{ex}} = 9.846 \approx 10.00$). Confirmed 10:1 split.
- **RITES**: In Indian markets, bonus issues do NOT alter equity face value or ISIN. Cum-close ₹683.45 on 2024-09-19 $\rightarrow$ Ex-open ₹356.00 on 2024-09-20 ($P_{\text{cum}} / P_{\text{ex}} = 1.92 \approx 2.00$). Distinctly represented as `BONUS_ISSUE` with multiplier 2.0.
- **POLYCAB**: Equity face value is confirmed ₹10. No corporate action split occurred. Excluded from registry.
- **VERTOZ**: Vertoz executed a 10:1 split and a 1:1 bonus on the same date (`2024-07-05`). These are preserved as **two distinct corporate action records**, with individual multipliers 10.0 and 2.0 (combined factor = 20.0). Cum-close ₹686.50 on 2024-07-04 $\rightarrow$ Ex-close ₹36.05 on 2024-07-05 ($P_{\text{cum}} / P_{\text{ex}} = 19.04 \approx 20.0$).
- **TATASTEEL Timing Nuance**: Ex-date trading occurred on `2022-07-28` (price adjusted from ₹959.40 to ₹100.35, ratio 9.56) under the old ISIN `INE081A01012`. The exchange activated the new ISIN `INE081A01020` in the Bhavcopy on the next trading day (`2022-07-29`). The registry anchors the corporate action to the true ex-date (`2022-07-28`).

---

## 3. Canonical Corporate Action Database Schema

Alembic migration `0004_corporate_actions.py` implemented the canonical `corporate_actions` table:
- `action_id`: String(64) primary key.
- `instrument_id`: String(36) foreign key to `instruments.instrument_id`.
- `symbol`: String(64) symbol at event date.
- `series`: String(16) series (default `EQ`).
- `action_type`: `STOCK_SPLIT`, `BONUS_ISSUE`, `CAPITAL_REORGANIZATION`, `ETF_SCHEME_RESTRUCTURING`.
- `ex_date`: Exact trading date on which stock trades ex-entitlement.
- `record_date`: Record date for beneficiary identification.
- `old_isin` / `new_isin`: ISIN transition tracking.
- `old_face_value` / `new_face_value`: Exact nominal face value in INR.
- `old_share_qty` / `new_share_qty`: Ratio parameters.
- `share_multiplier`: Numeric(12, 6) multiplier (e.g. 10.0, 2.0, 2.5, 5.0, 1.0).
- `purpose`: Description of the corporate action.
- `source_circular`: Official exchange circular identifier (e.g. `NSE/CML/2023/668`).
- `identity_decision`: `UNIFIED_IDENTITY` vs `PREDECESSOR_SUCCESSOR`.
- `verification_status`: `VERIFIED`, `UNRESOLVED`, `REJECTED`.
- `parser_version`: `v1.0`.

All 156 canonical events were persisted to PostgreSQL and exported to:
- `data/checkpoints/corporate_action_registry.json`
- `data/checkpoints/corporate_action_registry.csv`

---

## 4. Identity Decision Breakdown across 154 Transitions

Every audited ISIN transition has an explicit identity decision:
- **`UNIFIED_IDENTITY` (143 transitions)**:
  - 31 stock splits (10:1)
  - 30 stock splits (5:1)
  - 23 stock splits (2:1)
  - 4 stock splits (5:2)
  - 2 combined split + bonus events (20:1)
  - 45 capital reorganizations / pari-passu transitions (1:1 multiplier)
  - 8 non-standard verified splits
- **`PREDECESSOR_SUCCESSOR` (11 transitions)**:
  - 11 ETF scheme restructurings / mergers (e.g. `UTINIFTETF`, `SETFGOLD`, `HDFCNIFETF`, `AXISNIFTY`) where scheme identities must remain distinct.

---

## 5. Automated Tests & Verification

Added integration tests in `tests/integration/test_corporate_actions.py` verifying:
1. `test_multi_isin_and_transition_counts`: Proves 152 instruments $\rightarrow$ 150 (2-ISIN) + 2 (3-ISIN) = 154 transitions.
2. `test_tatasteel_split_event_and_multiplier`: Validates Tata Steel 10:1 split, ex-date 2022-07-28, multiplier 10.0.
3. `test_hal_split_event_and_multiplier`: Validates HAL 2:1 split, ex-date 2023-09-28, multiplier 2.0.
4. `test_nestleind_split_event_and_multiplier`: Validates Nestlé India 10:1 split, ex-date 2024-01-05, multiplier 10.0.
5. `test_rites_bonus_distinct_representation`: Validates RITES 1:1 bonus, ex-date 2024-09-20, multiplier 2.0, same ISIN, face value unchanged.
6. `test_vertoz_split_and_bonus_decomposition`: Validates separate atomic split (10.0) and bonus (2.0) events on 2024-07-05, with combined multiplier 20.0.
7. `test_polycab_split_exclusion`: Validates Polycab is excluded from split events.
8. `test_raw_prices_unmodified_by_corporate_actions`: Confirms raw market prices remain strictly 1,855,370 records.
9. `test_registry_checkpoint_files_exist_and_match`: Confirms JSON and CSV checkpoint integrity.

**Result**: **61 / 61 tests passed** in 3.32s (100% test pass rate across the full test suite).
