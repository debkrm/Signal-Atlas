#!/usr/bin/env python3
"""
probe_bhavcopy.py - Phase 0 Spike: NSE Bhavcopy Feasibility Probe

Tests downloading, archiving, and parsing NSE Bhavcopy files across format eras:
1. Legacy format: cm<DD><MMM><YYYY>bhav.csv.zip (Pre-July 2024)
2. UDiFF format: BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip (Post-July 2024)

Outputs:
- Original downloaded files in spikes/m0/downloads/
- SHA-256 calculation for every downloaded artifact
- Formats, columns, dtypes, row counts, series distribution
- Summary metadata in spikes/m0/bhavcopy_summary.json
"""

import argparse
import datetime
import hashlib
import json
import logging
import os
import sys
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("probe_bhavcopy")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

# Representative sample dates across two format eras:
# Pre-UDiFF (Legacy format) and Post-UDiFF (UDiFF format introduced July 8, 2024)
SAMPLE_DATES = [
    # Legacy format era
    "2022-07-28",  # Historical date around Tata Steel split
    "2023-06-15",
    "2023-11-03",
    "2024-01-12",
    "2024-04-12",
    # UDiFF format era (Post July 8, 2024)
    "2024-07-15",
    "2024-08-05",
    "2024-09-06",
    "2024-10-04",
    "2024-10-25",
]


class NSEBhavcopyProbe:
    def __init__(self, download_dir: Path, timeout: int = 15, delay: float = 1.5):
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.nseindia.com/",
            }
        )
        self._session_initialized = False

    def init_nse_session(self) -> None:
        """Initialize session by visiting nseindia homepage to acquire cookies if needed."""
        if self._session_initialized:
            return
        try:
            logger.info("Initializing session via https://www.nseindia.com...")
            resp = self.session.get("https://www.nseindia.com", timeout=self.timeout)
            logger.info("Homepage status: %s (cookies: %d)", resp.status_code, len(self.session.cookies))
            self._session_initialized = True
            time.sleep(1.0)
        except Exception as e:
            logger.warning("Could not pre-fetch NSE homepage cookies: %s. Proceeding with direct archive requests.", e)

    def get_candidate_urls(self, dt: datetime.date) -> List[Tuple[str, str, str]]:
        """
        Return list of candidate (era, url, filename) for a given date.
        """
        udiff_transition_date = datetime.date(2024, 7, 8)
        dd = dt.strftime("%d")
        mmm = dt.strftime("%b").upper()
        yyyy = dt.strftime("%Y")
        yyyymmdd = dt.strftime("%Y%m%d")

        candidates = []

        if dt >= udiff_transition_date:
            # UDiFF candidate primary
            filename = f"BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
            url1 = f"https://nsearchives.nseindia.com/content/cm/{filename}"
            url2 = f"https://archives.nseindia.com/content/cm/{filename}"
            candidates.append(("UDiFF", url1, filename))
            candidates.append(("UDiFF", url2, filename))
        else:
            # Legacy candidate primary
            filename = f"cm{dd}{mmm}{yyyy}bhav.csv.zip"
            url1 = f"https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mmm}/{filename}"
            url2 = f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mmm}/{filename}"
            candidates.append(("Legacy", url1, filename))
            candidates.append(("Legacy", url2, filename))

        return candidates

    def download_and_probe(self, dt_str: str) -> Dict[str, Any]:
        dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d").date()
        candidates = self.get_candidate_urls(dt)

        record: Dict[str, Any] = {
            "date": dt_str,
            "success": False,
            "url": None,
            "era": None,
            "filename": None,
            "file_size": 0,
            "sha256": None,
            "status_code": None,
            "error": None,
            "columns": [],
            "dtypes": {},
            "row_count": 0,
            "series_distribution": {},
            "sample_symbols": [],
        }

        for era, url, filename in candidates:
            out_path = self.download_dir / filename
            logger.info("Attempting [%s] %s -> %s", era, url, filename)
            try:
                time.sleep(self.delay)
                resp = self.session.get(url, timeout=self.timeout)
                record["status_code"] = resp.status_code

                if resp.status_code == 403 and not self._session_initialized:
                    logger.info("403 encountered. Attempting to initialize NSE session and retry...")
                    self.init_nse_session()
                    time.sleep(self.delay)
                    resp = self.session.get(url, timeout=self.timeout)
                    record["status_code"] = resp.status_code

                if resp.status_code != 200:
                    record["error"] = f"HTTP {resp.status_code}"
                    logger.warning("Failed [%s]: HTTP %s", url, resp.status_code)
                    continue

                content = resp.content
                # Guard against HTML error pages returned with HTTP 200
                if content.strip().startswith(b"<") or b"<html" in content[:200].lower():
                    record["error"] = "Received HTML response instead of binary ZIP"
                    logger.warning("Failed [%s]: Content is HTML error page", url)
                    continue

                if not content.startswith(b"PK\x03\x04"):
                    record["error"] = f"Invalid ZIP signature (first 4 bytes: {content[:4]!r})"
                    logger.warning("Failed [%s]: Not a valid ZIP file", url)
                    continue

                # Save raw original bytes
                with open(out_path, "wb") as f:
                    f.write(content)

                sha256 = hashlib.sha256(content).hexdigest()
                file_size = len(content)

                record["success"] = True
                record["url"] = url
                record["era"] = era
                record["filename"] = filename
                record["file_size"] = file_size
                record["sha256"] = sha256
                record["error"] = None

                # Parse ZIP content
                with zipfile.ZipFile(BytesIO(content)) as z:
                    csv_names = [n for n in z.namelist() if n.lower().endswith(".csv")]
                    if not csv_names:
                        record["error"] = "No CSV found inside ZIP"
                        break
                    with z.open(csv_names[0]) as csv_file:
                        df = pd.read_csv(csv_file)
                        # Clean column whitespace
                        df.columns = [str(c).strip() for c in df.columns]

                        record["columns"] = list(df.columns)
                        record["dtypes"] = {col: str(dtype) for col, dtype in df.dtypes.items()}
                        record["row_count"] = int(len(df))

                        # Identify series column
                        series_col = None
                        symbol_col = None
                        for sc in ["SERIES", "SctySrs", "scty_srs"]:
                            if sc in df.columns:
                                series_col = sc
                                break
                        for sym in ["SYMBOL", "TckrSymb", "symbol"]:
                            if sym in df.columns:
                                symbol_col = sym
                                break

                        if series_col:
                            series_dist = df[series_col].astype(str).value_counts().head(10).to_dict()
                            record["series_distribution"] = {str(k): int(v) for k, v in series_dist.items()}

                        if symbol_col:
                            sample = df[symbol_col].dropna().astype(str).head(10).tolist()
                            record["sample_symbols"] = sample

                logger.info(
                    "SUCCESS [%s] %s: %d rows, %d cols, SHA256=%s...%s",
                    era,
                    filename,
                    record["row_count"],
                    len(record["columns"]),
                    sha256[:8],
                    sha256[-8:],
                )
                break  # Successful download for this date
            except Exception as e:
                logger.error("Exception fetching %s: %s", url, e)
                record["error"] = str(e)

        return record


def main():
    parser = argparse.ArgumentParser(description="Probe NSE Bhavcopy accessibility and formats.")
    parser.add_argument(
        "--dates",
        nargs="*",
        default=SAMPLE_DATES,
        help="List of dates (YYYY-MM-DD) to probe. Default is sample across two eras.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("spikes/m0/downloads"),
        help="Directory to store downloaded raw archives.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("spikes/m0/bhavcopy_summary.json"),
        help="Path for saving JSON probe summary.",
    )
    args = parser.parse_args()

    probe = NSEBhavcopyProbe(download_dir=args.out_dir)
    results = []

    print("=" * 70)
    print("STARTING NSE BHAVCOPY FEASIBILITY PROBE")
    print(f"Target dates ({len(args.dates)}): {args.dates}")
    print(f"Output directory: {args.out_dir.resolve()}")
    print("=" * 70)

    for dt_str in args.dates:
        res = probe.download_and_probe(dt_str)
        results.append(res)

    args.summary.parent.mkdir(parents=True, exist_ok=True)
    with open(args.summary, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    successful = [r for r in results if r["success"]]
    print("\n" + "=" * 70)
    print(f"PROBE SUMMARY: {len(successful)}/{len(results)} successful")
    for r in results:
        status = "OK" if r["success"] else "FAIL"
        err = f" ({r['error']})" if r["error"] else ""
        print(f"  {r['date']}: [{status}] Era={r.get('era')} File={r.get('filename')} Rows={r.get('row_count')}{err}")
    print(f"Metadata saved to: {args.summary.resolve()}")
    print("=" * 70)


if __name__ == "__main__":
    main()
