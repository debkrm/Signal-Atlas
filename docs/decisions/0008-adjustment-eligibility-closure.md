# 0008. Final Adjustment Eligibility and Data Quality Closure (Phase 1B-ii.2.2)

Date: 2024-10-31
Status: Accepted

## Context

Following the review of Phase 1B-ii.2.1, three data-integrity issues and one provenance verification issue were identified:
1. **Reverse-Split Adjustment Eligibility**: The condition `share_multiplier > 1.0` in provenance reporting improperly excluded reverse splits / consolidations (specifically `KAUSHALYA` on 2024-02-06, a 100:1 reverse split with $M = 0.010000$).
2. **Missing Turnover vs Zero Turnover Semantics**: Defaulting missing/null source `traded_value` to `Decimal("0.00")` destroyed the crucial distinction between exchange-reported zero turnover and source-missing turnover.
3. **Candidate ISIN Reconciliation Assumptions**: Classification in bonus reconciliation and the 486-candidate sweep relied partly on hard-coded heuristics (`sym in ["VERTOZ", "GOLDSTAR"]`, `is_duplicate_observation=False`, and disposition-derived ISIN categories) rather than dynamic event-level evidence.
4. **Provenance Validation Rigor**: Tier 1 circular PDFs required SHA-256 byte-level verification against local files on disk. Missing publication dates needed preservation as `None` rather than falling back to the ex-date.

## Decision & Technical Design

### 1. Reverse-Split Adjustment Policy & Engine Parity
- **Unified Policy Function**: Defined `is_action_eligible_for_price_adjustment(ca)` in `src/signal_atlas/quality/adjustment.py`:
  - Verified `action_type in ("STOCK_SPLIT", "BONUS_ISSUE")`.
  - Non-neutral multiplier: `share_multiplier != Decimal("1.000000")` and `share_multiplier > Decimal("0.000000")`.
  - Explicit evidence status: `verification_status == "VERIFIED"`.
  - Neutral actions ($M=1.0$) and quarantined actions (Tier 4 ETFs) strictly do not adjust prices or volume.
- **Reverse Split Mathematics**:
  - $P_{\text{adj}} = P_{\text{raw}} / M$. For KAUSHALYA ($M = 0.010000$), historical prices are scaled by $1 / 0.01 = 100\times$.
  - $V_{\text{adj}} = V_{\text{raw}} \times M$. Historical volume is scaled by $0.01\times$.
- **Exchange Base-Price Resumption Alignment**:
  - For capital reorganizations where trading was suspended (e.g. `KAUSHALYA` from 2024-01-12 to 2024-02-05), NSE publishes the post-consolidation base price directly into `PREVCLOSE` on the resumption ex-date (₹985.00).
  - The engine dynamically detects when `raw_prev_close` on ex-date is already pre-scaled by the exchange: `abs(r_prev_close - (prior_close / M)) < abs(r_prev_close - prior_close)`.
  - In this case, `adj_prev_close = raw_prev_close` (₹985.00), perfectly matching the prior session's adjusted close (₹985.00, derived from raw ₹9.85 / 0.01), producing an exact overnight return of $+0.335\%$.
- **Parity Guarantee**: Both the bulk adjustment engine (`src/signal_atlas/quality/bulk_adjustment.py`) and the provenance exporter (`spikes/m0/build_canonical_corporate_actions.py`) import and consume `is_action_eligible_for_price_adjustment()`.

### 2. Missing Turnover Financial Semantics
- **Database Schema**: Created and applied Alembic migration `0009_allow_nullable_traded_value.py`, altering `traded_value` and `raw_traded_value` in `daily_prices_adjusted` to `Numeric(18, 2)` nullable.
- **Input Preservation**:
  - Source-reported zero remains `Decimal("0.00")`.
  - Missing/null source turnover remains `None`.
  - Raw exchange turnover is preserved untouched.
  - VWAP (`raw_vwap` and `adjusted_vwap`) remains `None` whenever volume is 0 or turnover is `None`.
- **Liquidity Ranking Policy**: Records with `traded_value is None` are strictly ineligible for liquidity ranking until explicitly handled.

### 3. Genuine Event-Level ISIN Continuity
- Built `spikes/m0/generate_event_level_reconciliation.py` using dynamic queries against `InstrumentSymbolHistory`:
  - `pre_isin`: Active ISIN strictly before the candidate ex-date.
  - `post_isin`: Active ISIN on or immediately after the candidate ex-date.
  - `is_isin_changed`: Evaluated directly as `pre_isin != post_isin`.
  - `is_companion_action`: Evaluated by detecting multiple canonical actions for the instrument on the same ex-date.
  - `is_duplicate_observation`: Computed by grouping candidate observations by `(symbol, ex_date)`.
- Re-exported `candidates_disposition_cross_tabulation.json` and `bonus_candidates_row_level_reconciliation.json` / `.csv`.

### 4. Cryptographic Provenance Verification
- Tier 1 Circulars: Computed SHA-256 directly from the bytes of files in `data/circulars/*.pdf` using `hashlib.sha256()`.
- Verified 7 of 7 Tier 1 PDFs match the recorded hash with zero mismatches.
- Missing publication dates are preserved as `None` (not defaulted to ex-date).

### 5. Adjustment Dataset Versioning (`v1.2`)
- Preserved existing `v1.0` (1,848,718 records) and `v1.1` (1,848,718 records) unchanged.
- Generated new version **`v1.2`** with 1,848,718 records:
  - 180,301 corporate action instrument records (including `KAUSHALYA` now correctly backward-adjusted).
  - 1,668,417 identity instrument records.
  - 6,652 quarantined ETF records excluded.
  - 1,855,370 raw price records completely immutable.
