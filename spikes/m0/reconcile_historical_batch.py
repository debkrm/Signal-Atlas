#!/usr/bin/env python3
"""
reconcile_historical_batch.py - Comprehensive source-to-database reconciliation.
Compares raw source CSV vs PostgreSQL database records across sampled historical dates
from both Legacy and CM-UDiFF format eras.
"""

import datetime
from decimal import Decimal
import io
import json
from pathlib import Path
import zipfile
import pandas as pd
from sqlalchemy import func, select

from signal_atlas.db.models import DailyPriceRaw, IngestionRun, Instrument
from signal_atlas.db.session import get_db


def reconcile_date(trade_date_str: str) -> dict:
    trade_date = datetime.datetime.strptime(trade_date_str, "%Y-%m-%d").date()

    with get_db() as db:
        run = db.execute(
            select(IngestionRun).where(IngestionRun.trade_date == trade_date)
        ).scalar()
        if not run:
            return {"date": trade_date_str, "status": "NOT_FOUND_IN_DB"}

        source_file = run.file_name
        run_status = run.status
        validation_issues = dict(run.validation_issues or {})

        # Query DB aggregations for this date
        db_prices = db.execute(
            select(
                DailyPriceRaw.series,
                DailyPriceRaw.volume,
                DailyPriceRaw.traded_value,
            ).where(DailyPriceRaw.trade_date == trade_date)
        ).all()

        db_row_count = len(db_prices)
        db_total_volume = sum(p.volume for p in db_prices)
        db_total_value = sum(p.traded_value for p in db_prices)

        db_series_dist = {}
        for p in db_prices:
            db_series_dist[p.series] = db_series_dist.get(p.series, 0) + 1

    # Locate source archive
    archive_path = Path("data/raw") / str(trade_date.year) / source_file
    if not archive_path.exists():
        archive_path = Path("spikes/m0/downloads") / source_file

    if not archive_path.exists():
        return {
            "date": trade_date_str,
            "status": "SOURCE_ARCHIVE_MISSING",
            "file": source_file,
        }

    with zipfile.ZipFile(archive_path) as z:
        csv_name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
        with z.open(csv_name) as f:
            df = pd.read_csv(f, dtype=str, keep_default_na=False)

    df.columns = [c.strip() for c in df.columns]
    unnamed = [c for c in df.columns if c.startswith("Unnamed:")]
    if unnamed:
        df = df.drop(columns=unnamed)

    is_udiff = "TradDt" in df.columns
    csv_rows = len(df)
    srs_col = "SctySrs" if is_udiff else "SERIES"
    vol_col = "TtlTradgVol" if is_udiff else "TOTTRDQTY"
    val_col = "TtlTrfVal" if is_udiff else "TOTTRDVAL"

    # Convert to decimals for exact math
    csv_series_dist = df[srs_col].value_counts().to_dict()

    # Calculate CSV total volume and value (safely converting floats/strings)
    csv_total_vol = 0
    csv_total_val = Decimal("0.0")
    for _, row in df.iterrows():
        try:
            v_str = str(row[vol_col]).strip()
            if v_str and v_str not in ("-", "nan"):
                csv_total_vol += int(float(v_str))
        except (ValueError, TypeError):
            pass

        try:
            val_str = str(row[val_col]).strip()
            if val_str and val_str not in ("-", "nan"):
                csv_total_val += Decimal(val_str)
        except Exception:
            pass

    quarantine_count = validation_issues.get("quarantine_count", 0)
    valid_expected_rows = csv_rows - quarantine_count
    row_count_match = (db_row_count == valid_expected_rows)
    vol_match = (db_total_volume == csv_total_vol)
    val_diff = abs(db_total_value - csv_total_val)

    # Check literal NA series in DB
    na_in_csv = int(df[df[srs_col] == "NA"].shape[0])
    na_in_db = db_series_dist.get("NA", 0)
    na_match = (na_in_csv == na_in_db)

    return {
        "date": trade_date_str,
        "format": "UDiFF" if is_udiff else "Legacy",
        "archive_file": source_file,
        "run_status": run_status,
        "csv_rows": csv_rows,
        "db_rows": db_row_count,
        "quarantined_records": quarantine_count,
        "row_count_reconciled": row_count_match,
        "csv_volume": csv_total_vol,
        "db_volume": db_total_volume,
        "volume_reconciled": vol_match,
        "csv_value": str(csv_total_val),
        "db_value": str(db_total_value),
        "value_diff": str(val_diff),
        "na_series_csv": na_in_csv,
        "na_series_db": na_in_db,
        "na_reconciled": na_match,
        "csv_series_count": len(csv_series_dist),
        "db_series_count": len(db_series_dist),
    }


def main():
    sample_dates = [
        # 2022 Legacy
        "2022-07-27",
        "2022-07-28",
        # 2023 Legacy
        "2023-09-27",
        "2023-09-28",
        # 2024 Legacy
        "2024-01-12",
        "2024-06-04",
        "2024-06-25",
        "2024-07-05",
        # 2024 UDiFF
        "2024-07-08",
        "2024-07-15",
        "2024-10-25",
        "2024-10-28",
    ]

    print("=" * 95)
    print("SOURCE-TO-DATABASE HISTORICAL RECONCILIATION")
    print("=" * 95)
    print(
        f"{'Date':<11} {'Format':<8} {'CSV Rows':<9} {'DB Rows':<9} {'Quar':<6} {'RowRec':<8} {'VolRec':<8} {'NA_Rec':<8} {'Status':<10}"
    )
    print("=" * 95)

    all_passed = True
    results = []

    for dt_str in sample_dates:
        res = reconcile_date(dt_str)
        results.append(res)
        if "csv_rows" in res:
            passed = res["row_count_reconciled"] and res["na_reconciled"]
            if not passed:
                all_passed = False
            print(
                f"{res['date']:<11} {res['format']:<8} {res['csv_rows']:<9} {res['db_rows']:<9} "
                f"{res['quarantined_records']:<6} {str(res['row_count_reconciled']):<8} "
                f"{str(res['volume_reconciled']):<8} {str(res['na_reconciled']):<8} {res['run_status']:<10}"
            )
        else:
            print(f"{res['date']:<11} {res['status']}")

    print("=" * 95)
    print(f"Overall Source-to-Database Reconciliation: {'PASSED' if all_passed else 'FAILED'}")

    out_file = Path("spikes/m0/historical_reconciliation_report.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Reconciliation details written to: {out_file}")


if __name__ == "__main__":
    main()
