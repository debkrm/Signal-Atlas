#!/usr/bin/env python3
"""
reconcile_all_743_dates.py - Complete 743-Session Historical Date-Level Audit.

Audits every single expected trading session across 2022-01-01 to 2024-12-31:
- Trade date
- Expected trading status
- Original source archive availability
- Source file SHA-256
- Source row count
- Parsed row count
- Valid row count
- Quarantined row count
- Persisted raw-price row count
- Ingestion status
- Row reconciliation: source_rows == persisted_rows + quarantined_rows
"""

import csv
import datetime
import hashlib
import json
from pathlib import Path
import time
import zipfile
import pandas as pd
from sqlalchemy import func, select

from signal_atlas.providers.nse.calendar import NSETradingCalendar, SPECIAL_WEEKEND_SESSIONS

MUHURAT_SESSIONS = {
    datetime.date(2022, 10, 24),
    datetime.date(2023, 11, 12),
    datetime.date(2024, 11, 1),
}
from signal_atlas.db.models import DailyPriceRaw, IngestionRun, DailyPriceQuarantine
from signal_atlas.db.session import get_db

def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def get_expected_status(d: datetime.date) -> str:
    if d in MUHURAT_SESSIONS:
        return "SPECIAL_MUHURAT_SESSION"
    if d in SPECIAL_WEEKEND_SESSIONS:
        return "SPECIAL_SATURDAY_SESSION"
    return "REGULAR_TRADING_SESSION"

def audit_all_dates():
    start_date = datetime.date(2022, 1, 1)
    end_date = datetime.date(2024, 12, 31)

    # 1. Determine all expected trading sessions using official calendar
    expected_dates = []
    curr = start_date
    while curr <= end_date:
        is_hol, _ = NSETradingCalendar.is_confirmed_holiday(curr)
        if is_hol:
            curr += datetime.timedelta(days=1)
            continue
        if curr.weekday() >= 5 and curr not in SPECIAL_WEEKEND_SESSIONS:
            curr += datetime.timedelta(days=1)
            continue
        expected_dates.append(curr)
        curr += datetime.timedelta(days=1)

    print(f"Total expected trading sessions to audit: {len(expected_dates)}")
    assert len(expected_dates) == 743, f"Expected 743 dates, got {len(expected_dates)}"

    # 2. Pre-fetch DB aggregations for fast processing
    print("Loading DB runs, prices, and quarantine counts...")
    t0 = time.time()
    with get_db() as db:
        # Ingestion runs
        runs = {
            r[0]: {"file_name": r[1], "status": r[2]}
            for r in db.execute(
                select(IngestionRun.trade_date, IngestionRun.file_name, IngestionRun.status)
            ).all()
        }
        # Price counts per date
        price_counts = dict(
            db.execute(
                select(DailyPriceRaw.trade_date, func.count(DailyPriceRaw.id))
                .group_by(DailyPriceRaw.trade_date)
            ).all()
        )
        # Quarantine counts per date
        quarantine_counts = dict(
            db.execute(
                select(DailyPriceQuarantine.trade_date, func.count(DailyPriceQuarantine.id))
                .group_by(DailyPriceQuarantine.trade_date)
            ).all()
        )
    print(f"Loaded DB stats in {round(time.time() - t0, 2)}s.")

    audit_records = []
    perfect_matches = 0
    quarantined_sessions = 0
    discrepancies = []

    total_source_rows = 0
    total_persisted_rows = 0
    total_quarantined_rows = 0

    print("Auditing each date against stored raw archives...")
    for idx, d in enumerate(expected_dates, 1):
        d_str = str(d)
        expected_status = get_expected_status(d)
        run = runs.get(d)

        if not run:
            audit_records.append({
                "trade_date": d_str,
                "expected_status": expected_status,
                "archive_available": False,
                "file_sha256": "N/A",
                "source_row_count": 0,
                "parsed_row_count": 0,
                "valid_row_count": 0,
                "quarantined_row_count": 0,
                "persisted_row_count": 0,
                "ingestion_status": "MISSING_FROM_RUNS",
                "reconciliation_status": "FAILED",
            })
            discrepancies.append((d_str, "Missing IngestionRun record"))
            continue

        filename = run["file_name"]
        ingestion_status = run["status"]

        # Locate archive
        archive_path = Path("data/raw") / str(d.year) / filename
        if not archive_path.exists():
            archive_path = Path("spikes/m0/downloads") / filename

        archive_available = archive_path.exists()
        file_sha256 = compute_sha256(archive_path) if archive_available else "N/A"

        # Read CSV inside archive to get exact source row count
        source_rows = 0
        parsed_rows = 0
        if archive_available:
            with zipfile.ZipFile(archive_path) as z:
                csv_names = [n for n in z.namelist() if n.lower().endswith(".csv")]
                if csv_names:
                    with z.open(csv_names[0]) as f:
                        df = pd.read_csv(f, dtype=str, keep_default_na=False)
                        unnamed = [c for c in df.columns if c.startswith("Unnamed:")]
                        if unnamed:
                            df = df.drop(columns=unnamed)
                        source_rows = len(df)
                        parsed_rows = source_rows

        persisted_rows = price_counts.get(d, 0)
        quarantined_rows = quarantine_counts.get(d, 0)
        valid_rows = source_rows - quarantined_rows

        total_source_rows += source_rows
        total_persisted_rows += persisted_rows
        total_quarantined_rows += quarantined_rows

        # Verification check
        # A date reconciles if persisted_rows == valid_rows AND persisted_rows + quarantined_rows == source_rows
        is_reconciled = (persisted_rows == valid_rows) and ((persisted_rows + quarantined_rows) == source_rows)

        if is_reconciled:
            perfect_matches += 1
            rec_status = "RECONCILED"
        else:
            rec_status = "DISCREPANCY"
            discrepancies.append((
                d_str,
                f"Source: {source_rows}, Persisted: {persisted_rows}, Quarantined: {quarantined_rows}"
            ))

        if quarantined_rows > 0:
            quarantined_sessions += 1

        audit_records.append({
            "trade_date": d_str,
            "expected_status": expected_status,
            "archive_available": archive_available,
            "file_sha256": file_sha256,
            "source_row_count": source_rows,
            "parsed_row_count": parsed_rows,
            "valid_row_count": valid_rows,
            "quarantined_row_count": quarantined_rows,
            "persisted_row_count": persisted_rows,
            "ingestion_status": ingestion_status,
            "reconciliation_status": rec_status,
        })

        if idx % 100 == 0 or idx == len(expected_dates):
            print(f"Processed {idx}/{len(expected_dates)} dates...")

    print("\n" + "=" * 60)
    print("RECONCILIATION AUDIT SUMMARY (2022-2024)")
    print("=" * 60)
    print(f"Total Expected Trading Sessions: {len(expected_dates)}")
    print(f"Total Sessions Audited:          {len(audit_records)}")
    print(f"Total Clean Sessions:            {len(expected_dates) - quarantined_sessions}")
    print(f"Total Quarantined Sessions:      {quarantined_sessions}")
    print(f"Reconciled Sessions:             {perfect_matches} / {len(expected_dates)} ({round(perfect_matches/len(expected_dates)*100, 2)}%)")
    print(f"Total Source Rows:               {total_source_rows:,}")
    print(f"Total Persisted Raw Rows:        {total_persisted_rows:,}")
    print(f"Total Quarantined Rows:          {total_quarantined_rows:,}")
    print(f"Sum (Persisted + Quarantined):   {total_persisted_rows + total_quarantined_rows:,}")
    print(f"Unaccounted Rows:                {total_source_rows - (total_persisted_rows + total_quarantined_rows)}")
    print("=" * 60)

    if discrepancies:
        print(f"\nDiscrepancies found ({len(discrepancies)}):")
        for dt, msg in discrepancies[:10]:
            print(f"  {dt}: {msg}")
    else:
        print("\nSUCCESS: 100% of rows across all 743 sessions are accounted for!")

    # Save to CSV
    csv_path = Path("data/checkpoints/full_743_date_reconciliation.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(audit_records[0].keys()))
        writer.writeheader()
        writer.writerows(audit_records)
    print(f"Saved audit CSV to {csv_path}")

    # Save to JSON
    json_path = Path("data/checkpoints/full_743_date_reconciliation.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(audit_records, f, indent=2)
    print(f"Saved audit JSON to {json_path}")

if __name__ == "__main__":
    audit_all_dates()
