#!/usr/bin/env python3
"""
audit_20241025.py - Detailed audit of the 2024-10-25 CM-UDiFF Bhavcopy.
Reconciles duplicate ISINs, duplicate symbols, series distribution,
and validates uniqueness constraints.
"""

import json
from pathlib import Path
import zipfile
import pandas as pd


def audit_udiff_file(zip_path: Path):
    with zipfile.ZipFile(zip_path) as z:
        csv_name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
        with z.open(csv_name) as f:
            df = pd.read_csv(f, dtype=str)

    df.columns = [c.strip() for c in df.columns]

    total_rows = len(df)
    unique_isins = df["ISIN"].nunique()
    unique_symbols = df["TckrSymb"].nunique()

    # 1. Duplicate ISIN check
    isin_counts = df["ISIN"].value_counts()
    dup_isins = isin_counts[isin_counts > 1]

    # 2. Duplicate Symbol check
    sym_counts = df["TckrSymb"].value_counts()
    dup_syms = sym_counts[sym_counts > 1]

    dup_sym_details = {}
    for sym, count in dup_syms.items():
        sub = df[df["TckrSymb"] == sym][["TckrSymb", "SctySrs", "ISIN", "FinInstrmNm", "FinInstrmTp"]]
        dup_sym_details[sym] = sub.to_dict(orient="records")

    # 3. Duplicate (ISIN, Symbol) check
    dup_isin_sym_count = int(df.duplicated(subset=["ISIN", "TckrSymb"]).sum())

    # 4. Duplicate (ISIN, Series) check
    dup_isin_series_count = int(df.duplicated(subset=["ISIN", "SctySrs"]).sum())

    # 5. Check whether any ISIN appears with more than one series on this date
    isin_series_grp = df.groupby("ISIN")["SctySrs"].nunique()
    multi_series_isins = isin_series_grp[isin_series_grp > 1]

    # 6. Series distribution
    series_dist = df["SctySrs"].value_counts().to_dict()

    # 7. Instrument type distribution
    type_dist = df["FinInstrmTp"].value_counts().to_dict()

    # 8. Segment distribution
    segment_dist = df["Sgmt"].value_counts().to_dict()

    report = {
        "source_file": zip_path.name,
        "total_source_rows": total_rows,
        "unique_isins": unique_isins,
        "unique_symbols": unique_symbols,
        "duplicate_isin_count": len(dup_isins),
        "duplicate_symbol_count": len(dup_syms),
        "duplicate_isin_symbol_rows": dup_isin_sym_count,
        "duplicate_isin_series_rows": dup_isin_series_count,
        "multi_series_isins_on_same_date": len(multi_series_isins),
        "duplicate_symbols_detail": dup_sym_details,
        "series_distribution": series_dist,
        "instrument_type_distribution": type_dist,
        "segment_distribution": segment_dist,
    }

    return report


def main():
    zip_path = Path("data/raw/2024/BhavCopy_NSE_CM_0_0_0_20241025_F_0000.csv.zip")
    if not zip_path.exists():
        zip_path = Path("spikes/m0/downloads/BhavCopy_NSE_CM_0_0_0_20241025_F_0000.csv.zip")

    report = audit_udiff_file(zip_path)

    print("=" * 70)
    print("AUDIT REPORT: 2024-10-25 CM-UDiFF BHAVCOPY")
    print("=" * 70)
    print(f"Total Source CSV Rows: {report['total_source_rows']}")
    print(f"Unique ISINs:          {report['unique_isins']}")
    print(f"Unique Symbols:        {report['unique_symbols']}")
    print(f"Duplicate ISINs:       {report['duplicate_isin_count']}")
    print(f"Multi-series ISINs on same date: {report['multi_series_isins_on_same_date']}")
    print(f"Duplicate Symbols:     {report['duplicate_symbol_count']}")

    print("\nDuplicate Symbol Breakdown:")
    for sym, records in report["duplicate_symbols_detail"].items():
        print(f"  Symbol '{sym}' occurs {len(records)} times:")
        for r in records:
            print(f"    - Series: {r['SctySrs']}, ISIN: {r['ISIN']}, Type: {r['FinInstrmTp']}, Name: {r['FinInstrmNm']}")

    print("\nSeries Distribution:")
    for srs, count in report["series_distribution"].items():
        print(f"  {srs:6s}: {count:5d}")

    print("\nInstrument Type Distribution:")
    for tp, count in report["instrument_type_distribution"].items():
        print(f"  {tp:6s}: {count:5d}")

    out_file = Path("spikes/m0/audit_20241025_summary.json")
    with open(out_file, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nFull audit written to: {out_file.resolve()}")
    print("=" * 70)


if __name__ == "__main__":
    main()
