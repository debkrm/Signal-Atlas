#!/usr/bin/env python3
"""
sync_true_symbol_history_dates.py - High-performance timeline extractor.
Chronologically scans all 743 raw Bhavcopy archives to determine the exact earliest date (valid_from)
and latest date (valid_to) for every (symbol, series, isin) tuple.
"""

import datetime
from pathlib import Path
import time
import zipfile
import pandas as pd
from sqlalchemy import select
from signal_atlas.db.models import InstrumentSymbolHistory
from signal_atlas.db.session import get_db

import re

def parse_date_from_filename(filename: str) -> datetime.date:
    name = Path(filename).name
    if name.startswith("cm") and "bhav" in name:
        return datetime.datetime.strptime(name[2:11], "%d%b%Y").date()
    elif "BhavCopy_NSE_CM" in name:
        match = re.search(r"(\d{8})", name)
        if match:
            return datetime.datetime.strptime(match.group(1), "%Y%m%d").date()
    raise ValueError(f"Unknown filename format: {filename}")

def sync_dates():
    t0 = time.time()
    print("Scanning all 743 raw archives chronologically to build exact ISIN presence timeline...")

    # Collect all zip paths sorted chronologically
    all_zips = []
    for y in ["2022", "2023", "2024"]:
        all_zips.extend(sorted(Path(f"data/raw/{y}").glob("*.zip")))

    # Sort strictly by date parsed from filename
    all_zips = sorted(all_zips, key=lambda p: parse_date_from_filename(p.name))
    print(f"Found {len(all_zips)} archives. Date range: {parse_date_from_filename(all_zips[0].name)} to {parse_date_from_filename(all_zips[-1].name)}")

    earliest_seen = {}
    latest_seen = {}

    for idx, p in enumerate(all_zips, 1):
        trade_date = parse_date_from_filename(p.name)
        with zipfile.ZipFile(p) as z:
            csv_names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                continue
            with z.open(csv_names[0]) as f:
                df = pd.read_csv(f, dtype=str, keep_default_na=False)
                df.columns = [c.strip() for c in df.columns]

                # Determine columns
                is_udiff = "TradDt" in df.columns
                sym_col = "TckrSymb" if is_udiff else "SYMBOL"
                srs_col = "SctySrs" if is_udiff else "SERIES"
                isin_col = "ISIN"

                if sym_col not in df.columns or isin_col not in df.columns:
                    continue

                symbols = df[sym_col].values
                series = df[srs_col].values if srs_col in df.columns else ["EQ"] * len(df)
                isins = df[isin_col].values

                for s, sr, isin in zip(symbols, series, isins):
                    s = s.strip()
                    sr = sr.strip()
                    isin = isin.strip()
                    if not s or not isin:
                        continue
                    key = (s, sr, isin)
                    if key not in earliest_seen:
                        earliest_seen[key] = trade_date
                    latest_seen[key] = trade_date

        if idx % 100 == 0 or idx == len(all_zips):
            print(f"Scanned {idx}/{len(all_zips)} archives in {round(time.time() - t0, 1)}s... (tracked {len(earliest_seen):,} tuples)")

    print(f"\nCompleted scan of 743 archives in {round(time.time() - t0, 1)}s.")
    print(f"Total distinct (symbol, series, isin) tuples found in archives: {len(earliest_seen):,}")

    # Now update instrument_symbol_history in DB
    print("\nUpdating instrument_symbol_history in DB...")
    updated_count = 0
    with get_db() as db:
        histories = db.execute(select(InstrumentSymbolHistory)).scalars().all()
        for h in histories:
            key = (h.symbol, h.series, h.isin)
            if key in earliest_seen:
                true_earliest = earliest_seen[key]
                true_latest = latest_seen[key]
                changed = False
                if h.valid_from != true_earliest:
                    h.valid_from = true_earliest
                    changed = True
                if h.valid_to != true_latest:
                    h.valid_to = true_latest
                    changed = True
                if changed:
                    updated_count += 1
        db.commit()

    print(f"Successfully updated {updated_count:,} instrument_symbol_history records with true valid_from and valid_to!")

if __name__ == "__main__":
    sync_dates()
