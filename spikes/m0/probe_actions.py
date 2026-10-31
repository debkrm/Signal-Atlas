#!/usr/bin/env python3
"""
probe_actions.py - Phase 0 Spike: NSE Corporate Actions Feasibility Probe

Tests fetching, archiving, and analyzing raw corporate action records:
- Authoritative event extraction from NSE corporate action endpoints.
- Analysis of raw purpose strings, ex-dates, record dates, and ISIN mapping.
- Raw price discontinuity verification around corporate action ex-dates.

Target Verified Events:
1. Tata Steel Limited (TATASTEEL): 10:1 split (Ex-date: 2022-07-28)
2. Hindustan Aeronautics Limited (HAL): 2:1 split (Ex-date: 2023-09-28)
"""

import argparse
import datetime
import hashlib
import json
import logging
from io import BytesIO
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
logger = logging.getLogger("probe_actions")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)


class NSEActionsProbe:
    def __init__(self, download_dir: Path, timeout: int = 15):
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.nseindia.com/",
            }
        )
        self._init_session()

    def _init_session(self) -> None:
        try:
            logger.info("Initializing NSE session cookies from homepage...")
            resp = self.session.get("https://www.nseindia.com", timeout=self.timeout)
            logger.info("Homepage status: %s (cookies: %d)", resp.status_code, len(self.session.cookies))
        except Exception as e:
            logger.warning("Session initialization warning: %s", e)

    def fetch_corporate_actions(
        self, symbol: str, from_date: str, to_date: str
    ) -> Dict[str, Any]:
        """
        Fetch corporate actions from NSE API for a given symbol and date window.
        Dates format: DD-MM-YYYY
        """
        url = (
            f"https://www.nseindia.com/api/corporates-corporateActions"
            f"?index=equities&from_date={from_date}&to_date={to_date}&symbol={symbol}"
        )
        logger.info("Fetching corporate actions for %s from %s to %s", symbol, from_date, to_date)

        resp = self.session.get(url, timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} fetching actions: {resp.text[:200]}")

        raw_bytes = resp.content
        filename = f"corporate_actions_{symbol}_{from_date}_{to_date}.json"
        out_path = self.download_dir / filename
        with open(out_path, "wb") as f:
            f.write(raw_bytes)

        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        data = resp.json()

        return {
            "symbol": symbol,
            "url": url,
            "filename": filename,
            "sha256": sha256,
            "byte_size": len(raw_bytes),
            "record_count": len(data) if isinstance(data, list) else 0,
            "records": data if isinstance(data, list) else [],
        }

    def inspect_price_discontinuity(
        self,
        symbol: str,
        pre_date_str: str,
        post_date_str: str,
    ) -> Dict[str, Any]:
        """
        Inspect raw exchange prices before and on ex-split date to measure raw discontinuity.
        """
        logger.info("Inspecting price discontinuity for %s across %s -> %s", symbol, pre_date_str, post_date_str)

        def get_ohlc(dt_str: str) -> Optional[Dict[str, Any]]:
            dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d").date()
            dd = dt.strftime("%d")
            mmm = dt.strftime("%b").upper()
            yyyy = dt.strftime("%Y")
            fname = f"cm{dd}{mmm}{yyyy}bhav.csv.zip"
            fpath = self.download_dir / fname

            if not fpath.exists():
                url = f"https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mmm}/{fname}"
                logger.info("Downloading historical bhavcopy: %s", url)
                r = self.session.get(url, timeout=self.timeout)
                if r.status_code == 200 and r.content.startswith(b"PK\x03\x04"):
                    with open(fpath, "wb") as f:
                        f.write(r.content)
                else:
                    return None

            with zipfile.ZipFile(fpath) as z:
                csv_name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
                df = pd.read_csv(z.open(csv_name))
                df.columns = [str(c).strip() for c in df.columns]
                row = df[(df["SYMBOL"] == symbol) & (df["SERIES"] == "EQ")]
                if len(row) > 0:
                    r = row.iloc[0]
                    return {
                        "date": dt_str,
                        "open": float(r["OPEN"]),
                        "high": float(r["HIGH"]),
                        "low": float(r["LOW"]),
                        "close": float(r["CLOSE"]),
                        "prev_close": float(r["PREVCLOSE"]),
                        "volume": int(r["TOTTRDQTY"]),
                        "isin": str(r.get("ISIN", "")),
                    }
            return None

        pre_data = get_ohlc(pre_date_str)
        post_data = get_ohlc(post_date_str)

        if not pre_data or not post_data:
            return {"error": "Could not locate symbol in historical bhavcopy"}

        ratio = post_data["close"] / pre_data["close"]
        volume_ratio = post_data["volume"] / pre_data["volume"] if pre_data["volume"] > 0 else 0

        return {
            "symbol": symbol,
            "pre_split": pre_data,
            "post_split": post_data,
            "close_price_ratio": round(ratio, 4),
            "raw_drop_percent": round((1.0 - ratio) * 100, 2),
            "volume_multiplier": round(volume_ratio, 2),
            "raw_prevclose_retained": post_data["prev_close"] == pre_data["close"],
        }


def main():
    parser = argparse.ArgumentParser(description="Probe NSE Corporate Actions and raw price discontinuities.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("spikes/m0/downloads"),
        help="Directory to store corporate action files and bhavcopy archives.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("spikes/m0/corporate_actions_summary.json"),
        help="Summary JSON output path.",
    )
    args = parser.parse_args()

    probe = NSEActionsProbe(download_dir=args.out_dir)

    print("=" * 70)
    print("STARTING CORPORATE ACTIONS & PRICE DISCONTINUITY PROBE")
    print("=" * 70)

    # 1. Tata Steel 10:1 split (July 2022)
    tata_actions = probe.fetch_corporate_actions(
        symbol="TATASTEEL", from_date="01-01-2022", to_date="31-12-2022"
    )
    tata_discontinuity = probe.inspect_price_discontinuity(
        symbol="TATASTEEL", pre_date_str="2022-07-27", post_date_str="2022-07-28"
    )

    # 2. HAL 2:1 split (September 2023)
    hal_actions = probe.fetch_corporate_actions(
        symbol="HAL", from_date="01-01-2023", to_date="31-12-2023"
    )
    hal_discontinuity = probe.inspect_price_discontinuity(
        symbol="HAL", pre_date_str="2023-09-27", post_date_str="2023-09-28"
    )

    summary = {
        "verified_events": [
            {
                "event_id": "TATASTEEL_SPLIT_2022",
                "company": "Tata Steel Limited",
                "symbol": "TATASTEEL",
                "ex_date": "2022-07-28",
                "actions_provenance": {
                    "filename": tata_actions["filename"],
                    "sha256": tata_actions["sha256"],
                    "record_count": tata_actions["record_count"],
                    "raw_records": tata_actions["records"],
                },
                "discontinuity_evidence": tata_discontinuity,
            },
            {
                "event_id": "HAL_SPLIT_2023",
                "company": "Hindustan Aeronautics Limited",
                "symbol": "HAL",
                "ex_date": "2023-09-28",
                "actions_provenance": {
                    "filename": hal_actions["filename"],
                    "sha256": hal_actions["sha256"],
                    "record_count": hal_actions["record_count"],
                    "raw_records": hal_actions["records"],
                },
                "discontinuity_evidence": hal_discontinuity,
            },
        ]
    }

    args.summary.parent.mkdir(parents=True, exist_ok=True)
    with open(args.summary, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 70)
    print("PROBE RESULTS:")
    for ev in summary["verified_events"]:
        print(f"\nEvent: {ev['event_id']} ({ev['company']})")
        disc = ev["discontinuity_evidence"]
        pre = disc.get("pre_split", {})
        post = disc.get("post_split", {})
        print(f"  Ex-date: {ev['ex_date']}")
        print(f"  Pre-split Close ({pre.get('date')}): Rs. {pre.get('close')}")
        print(f"  Post-split Close ({post.get('date')}): Rs. {post.get('close')}")
        print(f"  Close price ratio: {disc.get('close_price_ratio')} (Drop: {disc.get('raw_drop_percent')}%)")
        print(f"  Volume multiplier: {disc.get('volume_multiplier')}x")
        print(f"  Raw prevclose retained unchanged: {disc.get('raw_prevclose_retained')}")
    print(f"\nMetadata saved to: {args.summary.resolve()}")
    print("=" * 70)


if __name__ == "__main__":
    main()
