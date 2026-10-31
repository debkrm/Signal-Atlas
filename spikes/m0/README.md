# Milestone 0 (Phase 0) — NSE Data Source Feasibility Spikes

This directory contains throwaway research scripts and empirical verification tools for Phase 0 of the Signal Atlas project.

## Scripts Overview

### 1. `probe_bhavcopy.py`
Probes the availability, download mechanics, and formats of NSE Bhavcopy archives across two major historical format eras:
- **Legacy Era (Pre-July 8, 2024)**: `cm<DD><MMM><YYYY>bhav.csv.zip` from `archives.nseindia.com/content/historical/EQUITIES/...`
- **CM-UDiFF Era (Post-July 8, 2024)**: `BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip` from `nsearchives.nseindia.com/content/cm/...`

**Run:**
```bash
python spikes/m0/probe_bhavcopy.py
```
**Options:**
- `--dates YYYY-MM-DD [YYYY-MM-DD ...]`: Specific dates to probe.
- `--out-dir spikes/m0/downloads`: Directory where raw archives and hashes are preserved.
- `--summary spikes/m0/bhavcopy_summary.json`: Machine-readable metadata output.

### 2. `probe_actions.py`
Verifies access to authoritative corporate action records and examines actual raw price discontinuities around ex-split events:
- **TATASTEEL (10:1 split, Ex-date: 2022-07-28)**: Raw price dropped from Rs. 959.40 to Rs. 100.35 (-89.54%), raw PREVCLOSE remained unadjusted at Rs. 959.40.
- **HAL (2:1 split, Ex-date: 2023-09-28)**: Raw price dropped from Rs. 3837.70 to Rs. 1889.15 (-50.77%), raw PREVCLOSE remained unadjusted at Rs. 3837.70.

**Run:**
```bash
python spikes/m0/probe_actions.py
```
**Outputs:**
- `spikes/m0/downloads/corporate_actions_<SYMBOL>_<DATES>.json`
- `spikes/m0/corporate_actions_summary.json`

### 3. `probe_security_history.py`
Demonstrates point-in-time listed security existence, delisting reality, and series transitions:
- **DHFL (ISIN: INE202B01012)**: Confirmed active in 2019-01-10 (EQ series, 4.5M shares traded) and 2020-01-10; completely absent in 2022-07-28 and 2024-10-25 following CIRP resolution and delisting.
- **JETAIRWAYS (ISIN: INE802G01018)**: Present as EQ series in 2019; shifted to BZ series (surveillance / trade-for-trade) in 2022 and 2024.

**Run:**
```bash
python spikes/m0/probe_security_history.py
```
**Outputs:**
- `spikes/m0/security_history_summary.json`

## Requirements
- Python 3.12+ (tested on Python 3.13)
- `requests`, `pandas`
- No third-party commercial data subscriptions or API keys required.
