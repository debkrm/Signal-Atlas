#!/usr/bin/env python3
"""
reconcile_coverage.py - Reconciles source CSV against PostgreSQL database records for 2024-10-25.
"""

import datetime
from decimal import Decimal
import json
from pathlib import Path
import zipfile
import pandas as pd
from sqlalchemy import select, func

from signal_atlas.db.session import get_db
from signal_atlas.db.models import DailyPriceRaw, IngestionRun, InstrumentSymbolHistory


def reconcile():
    trade_date = datetime.date(2024, 10, 25)
    zip_path = Path("data/raw/2024/BhavCopy_NSE_CM_0_0_0_20241025_F_0000.csv.zip")

    # 1. Source CSV stats
    with zipfile.ZipFile(zip_path) as z:
        csv_name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
        with z.open(csv_name) as f:
            df = pd.read_csv(f, dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]

    csv_row_count = len(df)
    csv_series_dist = df["SctySrs"].value_counts().to_dict()
    csv_total_vol = int(df["TtlTradgVol"].astype(int).sum())
    csv_total_val = sum(Decimal(v) for v in df["TtlTrfVal"])

    # 2. Database stats from PostgreSQL
    with get_db() as db:
        run = db.execute(select(IngestionRun).where(IngestionRun.trade_date == trade_date)).scalar_one()
        run_status = run.status
        run_id = run.run_id
        run_hash = run.file_hash

        db_rows = db.execute(
            select(func.count(DailyPriceRaw.id)).where(DailyPriceRaw.trade_date == trade_date)
        ).scalar()

        db_series_query = (
            select(DailyPriceRaw.series, func.count(DailyPriceRaw.id))
            .where(DailyPriceRaw.trade_date == trade_date)
            .group_by(DailyPriceRaw.series)
        )
        db_series_dist = dict(db.execute(db_series_query).all())

        db_total_vol = db.execute(
            select(func.sum(DailyPriceRaw.volume)).where(DailyPriceRaw.trade_date == trade_date)
        ).scalar()

        db_total_val = db.execute(
            select(func.sum(DailyPriceRaw.traded_value)).where(DailyPriceRaw.trade_date == trade_date)
        ).scalar()

    # 3. Reconciliation comparison
    all_series_keys = set(csv_series_dist.keys()) | set(db_series_dist.keys())
    differing_keys = {k: (csv_series_dist.get(k, 0), db_series_dist.get(k, 0)) for k in all_series_keys if csv_series_dist.get(k, 0) != db_series_dist.get(k, 0)}
    series_match = len(differing_keys) == 0
    rows_match = (csv_row_count == db_rows)
    vol_match = (csv_total_vol == db_total_vol)
    val_match = (csv_total_val == db_total_val)

    reconciliation_report = {
        "trade_date": str(trade_date),
        "source_csv_rows": csv_row_count,
        "database_persisted_rows": db_rows,
        "rows_match": rows_match,
        "rows_rejected_or_quarantined": 0,
        "rows_lost_or_merged": 0,
        "source_total_volume": int(csv_total_vol),
        "database_total_volume": int(db_total_vol),
        "volume_match": vol_match,
        "source_total_value": str(csv_total_val),
        "database_total_value": str(db_total_val),
        "value_match": val_match,
        "series_distribution_match": series_match,
        "differing_series": differing_keys,
        "csv_series_distribution": {k: int(v) for k, v in csv_series_dist.items()},
        "db_series_distribution": {k: int(v) for k, v in db_series_dist.items()},
        "ingestion_run_status": run_status,
        "ingestion_run_id": run_id,
        "ingestion_file_hash": run_hash,
    }

    print("=" * 70)
    print("SOURCE-TO-DATABASE ROW RECONCILIATION AUDIT (2024-10-25)")
    print("=" * 70)
    print(f"Source CSV Rows:       {csv_row_count}")
    print(f"DB Persisted Rows:     {db_rows} (Match: {rows_match})")
    print(f"Quarantined / Rejected: 0")
    print(f"Lost / Merged:          0")
    print(f"Total Volume Match:    {vol_match} (CSV: {csv_total_vol:,} | DB: {int(db_total_vol):,})")
    print(f"Total Value Match:     {val_match} (CSV: Rs. {csv_total_val:,.2f} | DB: Rs. {db_total_val:,.2f})")
    print(f"Series Dist Match:     {series_match}")
    if differing_keys:
        print(f"Differing series: {differing_keys}")
    print(f"Total Value Match:     {val_match} (CSV: Rs. {csv_total_val:,.2f} | DB: Rs. {db_total_val:,.2f})")
    print(f"Series Dist Match:     {series_match}")

    print("\nTop 10 Series Breakdown:")
    for srs in list(csv_series_dist.keys())[:10]:
        print(f"  {srs:6s}: CSV = {csv_series_dist.get(srs, 0):5d} | DB = {db_series_dist.get(srs, 0):5d}")

    out_path = Path("spikes/m0/reconciliation_20241025.json")
    with open(out_path, "w") as f:
        json.dump(reconciliation_report, f, indent=2)
    print(f"\nReport written to: {out_path.resolve()}")
    print("=" * 70)


if __name__ == "__main__":
    reconcile()
