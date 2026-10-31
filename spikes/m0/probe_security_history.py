#!/usr/bin/env python3
"""
probe_security_history.py - Phase 0 Spike: Delisted Security & Historical Identity Probe

Tests historical availability and tracking of securities that were subsequently delisted
or underwent significant series transitions:
1. DHFL (Dewan Housing Finance Corporation Limited)
   - Pre-delisting (2019-01-10): Actively traded in EQ series.
   - Post-delisting (2022-07-28, 2024-10-25): Absent from Bhavcopy.
2. JETAIRWAYS (Jet Airways (India) Limited)
   - Demonstrates transition from EQ series to BZ series (surveillance/trade-for-trade).

Outputs:
- Original downloaded historical files in spikes/m0/downloads/
- SHA-256 for all source archives
- JSON summary at spikes/m0/security_history_summary.json
"""

import argparse
import datetime
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import zipfile

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("probe_security_history")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)


class NSESecurityHistoryProbe:
    def __init__(self, download_dir: Path, timeout: int = 15):
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "*/*",
                "Referer": "https://www.nseindia.com/",
            }
        )

    def ensure_bhavcopy(self, dt_str: str) -> Path:
        dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d").date()
        udiff_cutoff = datetime.date(2024, 7, 8)

        if dt >= udiff_cutoff:
            yyyymmdd = dt.strftime("%Y%m%d")
            fname = f"BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
            url = f"https://nsearchives.nseindia.com/content/cm/{fname}"
        else:
            dd = dt.strftime("%d")
            mmm = dt.strftime("%b").upper()
            yyyy = dt.strftime("%Y")
            fname = f"cm{dd}{mmm}{yyyy}bhav.csv.zip"
            url = f"https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mmm}/{fname}"

        out_path = self.download_dir / fname
        if not out_path.exists():
            logger.info("Downloading bhavcopy for %s from %s", dt_str, url)
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200 or not resp.content.startswith(b"PK\x03\x04"):
                raise RuntimeError(f"Failed downloading {url}: status={resp.status_code}")
            with open(out_path, "wb") as f:
                f.write(resp.content)

        return out_path

    def inspect_security(self, symbol: str, isin: str, dt_str: str) -> Dict[str, Any]:
        archive_path = self.ensure_bhavcopy(dt_str)
        with open(archive_path, "rb") as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()

        with zipfile.ZipFile(archive_path) as z:
            csv_name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
            df = pd.read_csv(z.open(csv_name))
            df.columns = [str(c).strip() for c in df.columns]

            sym_col = "SYMBOL" if "SYMBOL" in df.columns else "TckrSymb"
            srs_col = "SERIES" if "SERIES" in df.columns else "SctySrs"
            isin_col = "ISIN" if "ISIN" in df.columns else "isin"

            # Check matches by symbol or ISIN
            match_sym = df[df[sym_col].astype(str) == symbol]
            match_isin = df[df[isin_col].astype(str) == isin] if isin_col in df.columns else pd.DataFrame()

            found = len(match_sym) > 0 or len(match_isin) > 0
            series_found = []
            records = []

            for _, row in match_sym.iterrows():
                series_val = str(row.get(srs_col, ""))
                series_found.append(series_val)
                records.append(
                    {
                        "symbol": str(row.get(sym_col, "")),
                        "series": series_val,
                        "isin": str(row.get(isin_col, "")),
                        "close": float(row.get("CLOSE", row.get("ClsPric", 0.0))),
                        "volume": int(row.get("TOTTRDQTY", row.get("TtlTradgVol", 0))),
                    }
                )

            return {
                "date": dt_str,
                "archive_file": archive_path.name,
                "archive_sha256": sha256,
                "found": found,
                "symbol_matches": len(match_sym),
                "isin_matches": len(match_isin),
                "series_list": series_found,
                "records": records,
            }


def main():
    parser = argparse.ArgumentParser(description="Probe delisted security history.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("spikes/m0/downloads"),
        help="Directory to store bhavcopy archives.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("spikes/m0/security_history_summary.json"),
        help="Summary output path.",
    )
    args = parser.parse_args()

    probe = NSESecurityHistoryProbe(download_dir=args.out_dir)

    print("=" * 70)
    print("STARTING DELISTED SECURITY & HISTORICAL IDENTITY PROBE")
    print("=" * 70)

    # Security 1: Dewan Housing Finance Corporation Limited (DHFL)
    # Delisted on June 14, 2021 post CIRP resolution.
    dhfl_target = {
        "company_name": "Dewan Housing Finance Corporation Limited",
        "symbol": "DHFL",
        "isin": "INE202B01012",
        "delisting_date_approx": "2021-06-14",
        "delisting_reason": "CIRP Resolution Plan approved by NCLT (delisting of equity)",
        "test_dates": [
            "2019-01-10",  # Active pre-delisting
            "2020-01-10",  # Stressed period pre-delisting
            "2022-07-28",  # Post-delisting (Legacy era)
            "2024-10-25",  # Post-delisting (UDiFF era)
        ],
    }

    # Security 2: Jet Airways (India) Limited (JETAIRWAYS)
    # Series change from EQ to BZ
    jet_target = {
        "company_name": "Jet Airways (India) Limited",
        "symbol": "JETAIRWAYS",
        "isin": "INE802G01018",
        "status": "Suspended / trade-for-trade under CIRP",
        "test_dates": [
            "2019-01-10",
            "2022-07-28",
            "2024-10-25",
        ],
    }

    results = {"targets": []}

    for target in [dhfl_target, jet_target]:
        sym = target["symbol"]
        isin = target["isin"]
        print(f"\nProbing {target['company_name']} ({sym}, ISIN={isin})...")
        target_res = {
            "symbol": sym,
            "isin": isin,
            "company_name": target["company_name"],
            "observations": [],
        }
        for dt_str in target["test_dates"]:
            obs = probe.inspect_security(symbol=sym, isin=isin, dt_str=dt_str)
            target_res["observations"].append(obs)
            status_text = "PRESENT" if obs["found"] else "ABSENT"
            series_text = f"(Series: {', '.join(obs['series_list'])})" if obs["found"] else ""
            print(f"  {dt_str}: [{status_text}] {series_text}")
        results["targets"].append(target_res)

    args.summary.parent.mkdir(parents=True, exist_ok=True)
    with open(args.summary, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 70)
    print(f"Probe completed. Summary written to: {args.summary.resolve()}")
    print("=" * 70)


if __name__ == "__main__":
    main()
