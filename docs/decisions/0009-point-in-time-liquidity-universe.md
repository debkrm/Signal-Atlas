# ADR 0009: Point-in-Time Liquidity Universe Architecture & Eligibility Policy

## Status
Accepted (Enhanced with Phase 1B-iii.1 Data Integrity Closure)

## Context
A major source of backtesting failure in quantitative finance is **survivorship bias** (testing strategies only on stocks that are actively listed today) and **future-data leakage** (using modern index constituents, future price adjustments, or future trading sessions when deciding whether a stock was eligible on a historical date).

In Phase 1B-iii and Phase 1B-iii.1 of Signal Atlas, we require a deterministic, reproducible Point-in-Time (PIT) Liquidity Universe for NSE cash equities that answers:
> "Which securities would have been eligible for delivery-based swing trading selection based only on information available on or before this historical decision date?"

## Decision

### 1. Stable Identity and Point-in-Time Resolution
- **Stable Identity**: `instrument_id` (UUID) serves as the persistent, immutable security identifier across all historical name, symbol, ISIN, and capital structure changes.
- **Point-in-Time Resolution**: Symbols, ISINs, and series are dynamically resolved from `instrument_symbol_history` where `valid_from <= as_of_date` and `(valid_to IS NULL OR valid_to >= as_of_date)`.
- **Identity Invariance**: Renamed instruments (e.g. `4THDIM` $\rightarrow$ `GVPTECH`, `IIFLWAM` $\rightarrow$ `360ONE`) resolve to the symbol active on the query date while maintaining their stable `instrument_id`. Subdivided ISINs (e.g. `360ONE` or `JTLIND`) resolve to the exact active ISIN on that date and never create duplicate instrument entries.
- **Dynamic Series Disambiguation (Phase 1B-iii.1)**:
  - When an instrument has multiple overlapping symbol history intervals (e.g. `EQ` and `BE` during surveillance entry), series is resolved strictly from **actual exchange trade evidence** from `daily_prices_raw` during the lookback window or most recent active session.
  - If no trade activity differentiates valid records, deterministic recency fallback (`valid_from DESC`) is applied.
  - If ambiguity cannot be deterministically resolved, the security is excluded with reason `EXCLUDED_AMBIGUOUS_SERIES_HISTORY`. Blind preference for `EQ` over `BE` is strictly prohibited.

### 2. Disentangled Listing Date Semantics (Phase 1B-iii.1)
- **`listing_date`**: Represents the **actual exchange listing date**, populated strictly when supported by authoritative exchange/regulatory circulars. Unverified historical backfill dates are restored to `NULL`.
- **`first_observed_trade_date`**: Tracks the **earliest trade date available in our local dataset** (`MIN(daily_prices_raw.trade_date)`).
- **`InstrumentSymbolHistory.valid_from`**: Effective start date for that specific symbol/ISIN/series history record.
- **Future Listing Exclusion**: Future-listing exclusion evaluates verified `listing_date` (if available) and `first_observed_trade_date` $\le \text{as\_of\_date}$, ensuring that older companies are never falsely labeled as newly listed on the dataset inception date (`2022-01-03`).

### 3. Session Counting & Turnover Across EQ/BE (Phase 1B-iii.1)
- **Distinct Trading Date Counting**: `observed_sessions_count` strictly counts distinct calendar trading days (`COUNT(DISTINCT trade_date)`).
- **Completeness Invariance**: `trading_completeness` is strictly bounded: $0.0 \le \text{trading\_completeness} \le 1.0$. Missing sessions is derived as `max(0, expected_lookback_sessions - observed_sessions_count)`.
- **Zero Double-Counting**: Verified that across permitted series `('EQ', 'BE')`, there are 0 duplicate rows on the same calendar trade date in `daily_prices_raw`. Multi-series occurrences are restricted to block deals (`BL`), which are excluded by the permitted series filter.

### 4. Turnover-Data Completeness & Null Semantics (Phase 1B-iii.1)
- **Authoritative Turnover**: Must strictly use the exchange-reported `traded_value` column from `daily_prices_raw` (never `close × volume`).
- **Null Semantics Preservation**:
  - `NULL`: Unavailable/missing turnover. Tracked in `null_turnover_count`. Excluded from turnover denominator rather than fabricated into zero.
  - `0.00`: Genuine zero turnover (e.g. circuit-halted or zero trading activity). Tracked in `zero_turnover_count`. Dilutes ADTV.
  - `> 0.00`: Positive turnover. Tracked in `positive_turnover_count`.
- **Turnover Coverage Metric**:
  $$\text{Turnover Data Completeness} = \frac{\text{Valid Turnover Sessions}}{\text{Expected Lookback Sessions}}$$
- **Coverage Policy**: Requires `turnover_data_completeness >= min_turnover_completeness` (default: 80%). Securities with massive turnover on a trivial number of sessions are strictly excluded with `EXCLUDED_INSUFFICIENT_TURNOVER_COVERAGE`.

### 5. Configurable Eligibility Thresholds
| Parameter | Default | Rationale |
| :--- | :--- | :--- |
| `lookback_sessions` | `126` (~6 mos) | Smooths seasonal volume spikes while reflecting current institutional liquidity. Configurable to 60, 252. |
| `min_adtv` | `₹5,000,000.00` (₹50L) | Ensures a swing trading position of ₹1L–₹5L can be entered/exited within 5%–10% of daily volume with minimal market impact. |
| `min_trading_completeness` | `0.85` (85%) | Requires active trading on at least $\lceil 126 \times 0.85 \rceil = 108$ sessions to exclude suspended, illiquid, or newly-listed stocks. |
| `min_turnover_completeness` | `0.80` (80%) | Requires valid non-null turnover data on at least $\lceil 126 \times 0.80 \rceil = 101$ sessions to prevent denominator distortion. |
| `min_price` | `₹10.00` | Standard institutional penny-stock filter against wide spreads and extreme manipulation. Evaluated using raw price at `as_of_date` (never future-adjusted price!). |
| `permitted_series` | `("EQ", "BE")` | Cash equity delivery series. |
| `adjustment_version` | `"v1.4"` | Candidate adjusted historical price dataset version. |
| `raw_data_version` | `"RAW_NSE_2022_2024_V1"` | Raw price dataset version identifier. |
| `code_revision` | `"phase-1b-iii.1"` | Code revision used to generate universe snapshot. |
| `top_n` | `None` (all eligible) | Optional ranking cap by ADTV descending. |

### 6. Persistence & Audit Trail
- PostgreSQL tables `universe_snapshots` and `universe_members` record every evaluation run with full transactional idempotency.
- In `universe_snapshots`, `raw_data_version`, `data_coverage_start`, `data_coverage_end`, and `code_revision` are recorded.
- Overwriting snapshots generated from differing raw data versions is strictly rejected with an explicit error to preserve provenance.
- Export checkpoints saved as JSON and CSV under `data/universe_checkpoints/`.

## Consequences
- **Zero Survivorship Bias**: Delisted securities (such as `HDFC` prior to its July 2023 merger) are fully eligible on historical dates when active.
- **Zero Future Leakage**: No post-decision sessions, prices, or corporate actions are visible to the universe builder.
- **Exact Provenance**: Any historical universe can be exactly reproduced given as-of date, config identifier, raw data version, and code revision.
