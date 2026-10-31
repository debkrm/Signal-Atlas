import zipfile
from pathlib import Path
import pandas as pd

downloads_dir = Path("spikes/m0/downloads")
for zpath in sorted(downloads_dir.glob("*.zip")):
    with zipfile.ZipFile(zpath) as z:
        csv_name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
        with z.open(csv_name) as f:
            df = pd.read_csv(f, dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    isin_col = "ISIN"
    sym_col = "TckrSymb" if "TckrSymb" in df.columns else "SYMBOL"
    srs_col = "SctySrs" if "SctySrs" in df.columns else "SERIES"
    dups = df[df.duplicated(subset=[isin_col], keep=False)]
    if not dups.empty:
        print(f"\n=== {zpath.name} (Duplicate ISINs: {len(dups)}) ===")
        for _, row in dups.iterrows():
            close_val = row.get("CLOSE") or row.get("ClsPric")
            vol_val = row.get("TOTTRDQTY") or row.get("TtlTradgVol")
            print(f"  {row[sym_col]:12s} | Series: {row[srs_col]:5s} | ISIN: {row[isin_col]} | Close: {close_val} | Vol: {vol_val}")
