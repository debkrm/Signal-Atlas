import io
import zipfile
from typing import List, Optional


def create_sample_legacy_csv(
    trade_date_str: str = "28-JUL-2022",
    records: Optional[List[dict]] = None,
) -> str:
    """Generate a valid Legacy Bhavcopy CSV string with trailing comma artifact."""
    header = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"

    if records is None:
        records = [
            {
                "symbol": "RELIANCE",
                "series": "EQ",
                "open": "2400.00",
                "high": "2430.50",
                "low": "2395.00",
                "close": "2420.25",
                "last": "2421.00",
                "prev_close": "2390.00",
                "vol": "4500000",
                "val": "10890000000.00",
                "txs": "125000",
                "isin": "INE002A01018",
            },
            {
                "symbol": "TATASTEEL",
                "series": "EQ",
                "open": "98.10",
                "high": "102.00",
                "low": "97.15",
                "close": "100.35",
                "last": "100.40",
                "prev_close": "959.40",
                "vol": "137156107",
                "val": "13763615337.45",
                "txs": "350000",
                "isin": "INE081A01012",
            },
            {
                "symbol": "NHAI76",
                "series": "NA",  # Literal NA series for non-convertible debentures
                "open": "1100.00",
                "high": "1110.00",
                "low": "1100.00",
                "close": "1105.00",
                "last": "1105.00",
                "prev_close": "1102.00",
                "vol": "500",
                "val": "552500.00",
                "txs": "15",
                "isin": "INE906B07EJ8",
            },
        ]

    rows = []
    for r in records:
        row = (
            f"{r['symbol']},{r['series']},{r['open']},{r['high']},{r['low']},{r['close']},"
            f"{r.get('last', r['close'])},{r['prev_close']},{r['vol']},{r['val']},"
            f"{trade_date_str},{r.get('txs', '100')},{r['isin']},\n"
        )
        rows.append(row)

    return header + "".join(rows)


def create_sample_legacy_zip(
    filename: str = "cm28JUL2022bhav.csv.zip",
    trade_date_str: str = "28-JUL-2022",
    records: Optional[List[dict]] = None,
) -> bytes:
    """Generate in-memory bytes of a valid Legacy Bhavcopy ZIP archive."""
    csv_content = create_sample_legacy_csv(trade_date_str=trade_date_str, records=records)
    csv_name = filename.replace(".zip", "")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(csv_name, csv_content)

    return buffer.getvalue()
