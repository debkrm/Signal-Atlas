# Decision Record 0001: NSE Data Sources Feasibility & Ingestion Strategy

- **Status:** Completed / Ready for Review
- **Date:** 2026-10-31
- **Authors:** Signal Atlas Core Agent
- **Target Audience:** Project Maintainer
- **Context:** Milestone 0 (Phase 0) Feasibility Spike

---

## 1. Executive Summary & Recommendation

**Recommendation:** **GO** for Phase 1A (Repository bootstrap and single-day production ingestion).

Empirical probes have confirmed that:
1. **Bhavcopy Archives**: Both modern **CM-UDiFF** (introduced July 8, 2024) and **Legacy Bhavcopy** (pre-July 2024) can be downloaded directly and parsed into structured data without paid subscriptions or third-party dependencies.
2. **Provenance Preservation**: All archives download as valid ZIP files, allowing bit-level raw byte preservation with immutable SHA-256 hashes.
3. **Corporate Actions**: Authoritative corporate action disclosures (splits, bonuses, dividends, face value sub-divisions) can be queried and mapped directly by symbol, ISIN, and ex-date.
4. **Price Discontinuities**: Verified raw exchange prices prove that raw Bhavcopy records **do not pre-adjust historical prices or prev-close figures**. Split price drops (e.g. Tata Steel 10:1 and HAL 2:1) appear directly in the raw data, confirming the need for an independent, versioned analytical adjustment layer.
5. **Point-in-Time Universe & Delisted Securities**: Testing historical Bhavcopy archives from 2019 confirmed that subsequently delisted securities (e.g., Dewan Housing Finance / `DHFL`) exist with active trading volume prior to delisting and disappear post-delisting.

---

## 2. Source Inventory & Access Mechanics

| Source Name | Endpoint / URL Pattern | Era / Scope | Auth / Headers Required | Format |
|---|---|---|---|---|
| **NSE CM-UDiFF Common Bhavcopy** | `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip` | Post-2024-07-08 to Present | Standard browser `User-Agent`, `Referer: https://www.nseindia.com/` | ZIP containing CSV (34 columns) |
| **NSE Legacy Equity Bhavcopy** | `https://archives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MMM}/cm{DD}{MMM}{YYYY}bhav.csv.zip` | Historical to 2024-07-05 | Standard browser `User-Agent`, `Referer: https://www.nseindia.com/` | ZIP containing CSV (14 columns) |
| **NSE Corporate Actions API** | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date={DD-MM-YYYY}&to_date={DD-MM-YYYY}&symbol={SYMBOL}` | Historical & Current | Pre-visit `https://www.nseindia.com` to obtain session cookies (`nsit`, `nseappid`) | JSON array |

### Access Rules and Pacing Controls
- **Pacing**: Minimum 1.0 to 1.5 seconds delay between requests to avoid rate-limiting.
- **Session Cookies**: Direct archive endpoints (`nsearchives.nseindia.com` and `archives.nseindia.com`) do not require session cookies. However, `www.nseindia.com/api/...` endpoints require an initial handshake to receive cookies before API requests succeed.
- **Error Page Guards**: NSE returns HTML error pages on invalid parameters or 404s. Downloader implementations must check that binary content begins with the ZIP magic bytes (`PK\x03\x04`) and must reject HTML payloads immediately.

---

## 3. Format Eras & Column Mappings

The ingestion engine must support two format parsers, normalizing into a single internal target schema:

### Internal Target Model: `DailyPriceRaw`
- `trade_date`: Date
- `symbol`: String
- `series`: String (e.g., `EQ`, `BE`, `SM`)
- `isin`: String
- `open`: Decimal
- `high`: Decimal
- `low`: Decimal
- `close`: Decimal
- `last`: Decimal
- `prev_close`: Decimal
- `volume`: Integer (Total traded quantity)
- `traded_value`: Decimal (Total traded value)
- `trades_count`: Integer (Number of transactions executed)

### Field Mapping Across Eras

| Internal Field | Legacy Era Field (Pre-July 2024) | UDiFF Era Field (Post-July 2024) | Notes |
|---|---|---|---|
| `trade_date` | `TIMESTAMP` (e.g. `28-JUL-2022`) | `TradDt` (e.g. `2024-07-15`) | Date string format differs |
| `symbol` | `SYMBOL` | `TckrSymb` | e.g. `TATASTEEL` |
| `series` | `SERIES` | `SctySrs` | e.g. `EQ`, `BE`, `BZ` |
| `isin` | `ISIN` | `ISIN` | 12-character ISIN |
| `open` | `OPEN` | `OpnPric` | Numeric float |
| `high` | `HIGH` | `HghPric` | Numeric float |
| `low` | `LOW` | `LwPric` | Numeric float |
| `close` | `CLOSE` | `ClsPric` | Numeric float |
| `last` | `LAST` | `LastPric` | Numeric float |
| `prev_close` | `PREVCLOSE` | `PrvsClsgPric` | Unadjusted previous close |
| `volume` | `TOTTRDQTY` | `TtlTradgVol` | Traded shares |
| `traded_value` | `TOTTRDVAL` | `TtlTrfVal` | Traded rupees |
| `trades_count` | `TOTALTRADES` | `TtlNbOfTxsExctd` | Transaction count |

*Note on Legacy format:* Legacy CSV contains a trailing comma resulting in an artifact column `Unnamed: 13`, which the normalizer must safely strip.

---

## 4. Empirical Evidence

### 4.1 Sample Downloaded Dates & File Hashes (10 Sample Dates)

| Date | Era | File Name | Size (Bytes) | Rows | Cols | SHA-256 Hash |
|---|---|---|---|---|---|---|
| 2022-07-28 | Legacy | `cm28JUL2022bhav.csv.zip` | 83,253 | 2,222 | 14 | `6efdacccfe775d2b21201eeb0e4531c0355de4d81b7eccdc170415bfd0dc36fe` |
| 2023-06-15 | Legacy | `cm15JUN2023bhav.csv.zip` | 91,812 | 2,436 | 14 | `872d0bbc89f2575cbafd5f1fc082113228f5487ec4e0c3f8f613c34bb38479f4` |
| 2023-11-03 | Legacy | `cm03NOV2023bhav.csv.zip` | 97,787 | 2,588 | 14 | `cde504a91e57c6b4bb5b6b1076f8c772c9bc27da48c0812b3c2bb6f6242810f5` |
| 2024-01-12 | Legacy | `cm12JAN2024bhav.csv.zip` | 100,217 | 2,652 | 14 | `91cfbe82d46e2717a61d1ea1787c93630f576e27cb188bfb979aebaa48e4e7be` |
| 2024-04-12 | Legacy | `cm12APR2024bhav.csv.zip` | 103,462 | 2,728 | 14 | `cc2b98816c74d6426435c24e6ffec06a88b5066465452d9a60aa5adcc6e96f1a` |
| 2024-07-15 | UDiFF | `BhavCopy_NSE_CM_0_0_0_20240715_F_0000.csv.zip` | 167,495 | 2,839 | 34 | `0b1644a66a150c266a4da499c8942b03d258356da7aa8bfdfae1a44bad145f22` |
| 2024-08-05 | UDiFF | `BhavCopy_NSE_CM_0_0_0_20240805_F_0000.csv.zip` | 168,785 | 2,859 | 34 | `1a0bf2364ca81c4ca493495f2472dc7c77e7a5e35b339dcf90326fade6462597` |
| 2024-09-06 | UDiFF | `BhavCopy_NSE_CM_0_0_0_20240906_F_0000.csv.zip` | 166,692 | 2,826 | 34 | `e496e85fe39f4a13c9df946e3cbfeef51ef43fa9bb13ff2400f40a1b3c4d5752` |
| 2024-10-04 | UDiFF | `BhavCopy_NSE_CM_0_0_0_20241004_F_0000.csv.zip` | 172,504 | 2,917 | 34 | `76aee8dc46e45f9fb29c322b7c6c738cb20b2aa712a20a67137b08d219c00119` |
| 2024-10-25 | UDiFF | `BhavCopy_NSE_CM_0_0_0_20241025_F_0000.csv.zip` | 170,963 | 2,902 | 34 | `1bffc104f8ab173eac972d0ef4a14dd609eb3e54138dac547817d8a6659b7e6c` |

### 4.2 Corporate Actions & Price Discontinuity Evidence

#### Event 1: Tata Steel Limited (`TATASTEEL`) 10:1 Stock Split
- **Authoritative Action Record**:
  - Ex-Date: `28-Jul-2022`
  - Record Date: `29-Jul-2022`
  - Raw Subject Text: `"Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share"`
  - ISIN: `INE081A01012`
- **Raw Exchange Price Observation**:
  - `2022-07-27` (Pre-split): Close = **Rs. 959.40**, Traded Volume = 5,255,902
  - `2022-07-28` (Ex-split): Close = **Rs. 100.35**, Traded Volume = 137,156,107
  - Price Ratio: **0.1046** (-89.54% drop)
  - `PREVCLOSE` on ex-split day: **Rs. 959.40** (Raw unadjusted exchange value retained).

#### Event 2: Hindustan Aeronautics Limited (`HAL`) 2:1 Stock Split
- **Authoritative Action Record**:
  - Ex-Date: `28-Sep-2023`
  - Record Date: `29-Sep-2023`
  - Raw Subject Text: `"Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 5/- Per Share"`
  - ISIN: `INE066F01012`
- **Raw Exchange Price Observation**:
  - `2023-09-27` (Pre-split): Close = **Rs. 3837.70**, Volume = 1,061,719
  - `2023-09-28` (Ex-split): Close = **Rs. 1889.15**, Volume = 2,473,810
  - Price Ratio: **0.4923** (-50.77% drop)
  - `PREVCLOSE` on ex-split day: **Rs. 3837.70** (Raw unadjusted exchange value retained).

### 4.3 Delisted Security & Historical Identity Evidence

- **Subject**: Dewan Housing Finance Corporation Limited (`DHFL`, ISIN: `INE202B01012`)
- **Event**: CIRP resolution under IBC; equity shares delisted on June 14, 2021 (NSE Circular NSE/CML/48574).
- **Historical Observations**:
  - `2019-01-10`: **PRESENT**. Actively traded in `EQ` series (Close: Rs. 224.10, Volume: 4,514,692 shares) alongside debt series (`NC`, `NL`, etc.).
  - `2020-01-10`: **PRESENT**. Actively traded in `EQ` series (Close: Rs. 17.70, Volume: 5,618,294 shares).
  - `2022-07-28`: **ABSENT**. Completely removed from Bhavcopy.
  - `2024-10-25`: **ABSENT**. Completely removed from Bhavcopy.
- **Series Transition Subject**: Jet Airways (India) Limited (`JETAIRWAYS`, ISIN: `INE802G01018`)
  - `2019-01-10`: Present under `EQ` series.
  - `2022-07-28` & `2024-10-25`: Present under `BZ` series (trade-for-trade / surveillance), demonstrating that series shifts must not be modeled as new instrument identities.

---

## 5. Feasible Historical Scope & Data Gaps

1. **Feasible Ingestion Depth**:
   - Recent data (July 8, 2024 onwards) is available via UDiFF.
   - 2019 through July 2024 is directly accessible via the Legacy Bhavcopy archive.
   - Recommended initial historical import scope for Phase 1B: **2 to 3 years** (e.g. 2022–2024) to validate corporate action adjustment mechanisms before expanding further back.
2. **Known Gaps & Nuances**:
   - Free-text corporate actions: Corporate action "subject" fields are free text and require structured pattern extraction rather than naive token splitting.
   - Trading holidays: NSE does not publish Bhavcopy on exchange holidays; a deterministic trading calendar table is required to distinguish missing data from non-trading days.
   - Series diversity: Equities trade in `EQ`, `BE`, and `BZ`. Non-equity series (`SM` for SME, `GS` for G-Sec, `N` series for NCDs, SGBs) appear in the Bhavcopy and must be filtered out for the delivery swing trading universe.

---

## 6. Phase 0 Acceptance Criteria Checklist

- [x] ~10 dates fetched across at least two format eras.
- [x] SHA-256 hashes and original files saved for all successful downloads.
- [x] Column mapping documented for every observed format era.
- [x] At least one subsequently delisted security found in an old file with documented identity evidence (DHFL).
- [x] At least one verified split/bonus event found in authoritative records (TATASTEEL 10:1 split, HAL 2:1 split).
- [x] Raw price discontinuity around the event inspected and compared with action records.
- [x] Request headers, pacing, failures, and access limitations documented.
- [x] Clear conclusion on feasible historical period and remaining data gaps.
- [x] Deliverable `docs/decisions/0001-data-sources.md` created.
