#!/usr/bin/env python3
"""
audit_multi_date_identity.py - Multi-date identity and daily uniqueness audit.
Verifies instrument identity resolution and UNIQUE(instrument_id, trade_date)
across multiple Legacy and UDiFF historical dates.
"""

import json
from pathlib import Path
import zipfile
import pandas as pd


def audit_file(zip_path: Path):
    with zipfile.ZipFile(zip_path) as z:
        csv_name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
        with z.open(csv_name) as f:
            df = pd.read_csv(f, dtype=str, keep_default_na=False)

    df.columns = [c.strip() for c in df.columns]
    unnamed = [c for c in df.columns if c.startswith("Unnamed:")]
    if unnamed:
        df = df.drop(columns=unnamed)

    is_udiff = "TradDt" in df.columns
    date_col = "TradDt" if is_udiff else "TIMESTAMP"
    sym_col = "TckrSymb" if is_udiff else "SYMBOL"
    srs_col = "SctySrs" if is_udiff else "SERIES"
    isin_col = "ISIN"

    total_rows = len(df)
    unique_isins = df[isin_col].nunique()
    unique_syms = df[sym_col].nunique()

    # 1. Duplicate ISIN check on this date
    isin_counts = df[isin_col].value_counts()
    dup_isins = isin_counts[isin_counts > 1]

    # 2. Duplicate Symbol check
    sym_counts = df[sym_col].value_counts()
    dup_syms = sym_counts[sym_counts > 1]

    # 3. Check whether any ISIN appears with more than one series on this date
    isin_series_grp = df.groupby(isin_col)[srs_col].nunique()
    multi_srs_isins = isin_series_grp[isin_series_grp > 1]

    # 4. Check whether (ISIN, Symbol) has duplicates
    dup_isin_sym = df.duplicated(subset=[isin_col, sym_col]).sum()

    # 5. Check if ISIN is missing or blank
    blank_isins = (df[isin_col].isna() | (df[isin_col].str.strip() == "")).sum()

    # 6. Check literal "NA" series presence
    na_series_count = (df[srs_col] == "NA").sum()

    return {
        "file": zip_path.name,
        "format": "UDiFF" if is_udiff else "Legacy",
        "trade_date": df[date_col].iloc[0] if len(df) > 0 else None,
        "total_rows": total_rows,
        "unique_isins": unique_isins,
        "unique_symbols": unique_syms,
        "duplicate_isins": int(len(dup_isins)),
        "multi_series_isins_same_day": int(len(multi_srs_isins)),
        "duplicate_symbols": int(len(dup_syms)),
        "duplicate_isin_sym": int(dup_isin_sym),
        "blank_isins": int(blank_isins),
        "na_series_count": int(na_series_count),
        "duplicate_symbols_sample": list(dup_syms.index[:5]),
    }


def main():
    downloads_dir = Path("spikes/m0/downloads")
    zip_files = sorted(downloads_dir.glob("*.zip"))

    results = []
    print("=" * 85)
    print(f"{'File':<40} {'Format':<8} {'Rows':<6} {'ISINs':<6} {'DupISIN':<8} {'DupSym':<8} {'NA_Srs':<6}")
    print("=" * 85)

    all_safe = True
    for z in zip_files:
        res = audit_file(z)
        results.append(res)
        print(
            f"{res['file']:<40} {res['format']:<8} {res['total_rows']:<6} "
            f"{res['unique_isins']:<6} {res['duplicate_isins']:<8} "
            f"{res['duplicate_symbols']:<8} {res['na_series_count']:<6}"
        )
        if res["duplicate_isins"] > 0:
            all_safe = False
            print(f"  WARNING: Duplicate ISINs found in {res['file']}!")
        if res["blank_isins"] > 0:
            all_safe = False
            print(f"  WARNING: Blank ISINs found in {res['file']}!")

    print("=" * 85)
    print(f"Audit completed across {len(results)} historical files.")
    print(f"All ISINs strictly unique per date: {all_safe}")

    out_file = Path("spikes/m0/historical_identity_audit_summary.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Summary saved to: {out_file}")


if __name__ == "__main__":
    main()
