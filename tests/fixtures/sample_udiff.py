import io
import zipfile
from typing import List, Optional


def create_sample_udiff_csv(
    trade_date: str = "2024-10-25",
    records: Optional[List[dict]] = None,
) -> str:
    """Generate a valid CM-UDiFF CSV string."""
    header = (
        "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
        "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
        "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
        "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
    )

    if records is None:
        records = [
            {
                "symbol": "RELIANCE",
                "series": "EQ",
                "isin": "INE002A01018",
                "name": "RELIANCE INDUSTRIES LTD",
                "open": "2900.00",
                "high": "2950.50",
                "low": "2890.00",
                "close": "2940.25",
                "last": "2941.00",
                "prev_close": "2895.00",
                "vol": "1500000",
                "val": "4395000000.00",
                "txs": "85000",
            },
            {
                "symbol": "TATASTEEL",
                "series": "EQ",
                "isin": "INE081A01012",
                "name": "TATA STEEL LIMITED",
                "open": "145.00",
                "high": "148.50",
                "low": "144.20",
                "close": "147.80",
                "last": "147.75",
                "prev_close": "144.00",
                "vol": "12000000",
                "val": "1764000000.00",
                "txs": "120000",
            },
            {
                "symbol": "INFY",
                "series": "EQ",
                "isin": "INE009A01021",
                "name": "INFOSYS LIMITED",
                "open": "1850.00",
                "high": "1875.00",
                "low": "1845.00",
                "close": "1868.50",
                "last": "1869.00",
                "prev_close": "1840.00",
                "vol": "3500000",
                "val": "6510000000.00",
                "txs": "95000",
            },
        ]

    rows = []
    for r in records:
        row = (
            f"{trade_date},{trade_date},CM,NSE,STK,12345,{r['isin']},{r['symbol']},{r['series']},,"
            f",,,{r.get('name', '')},{r['open']},{r['high']},{r['low']},{r['close']},"
            f"{r.get('last', r['close'])},{r['prev_close']},,,,{r['vol']},{r['val']},"
            f"{r.get('txs', '100')},1,1,,,,,\n"
        )
        rows.append(row)

    return header + "".join(rows)


def create_sample_udiff_zip(
    trade_date: str = "2024-10-25",
    records: Optional[List[dict]] = None,
) -> bytes:
    """Generate in-memory bytes of a valid CM-UDiFF Bhavcopy ZIP archive."""
    csv_content = create_sample_udiff_csv(trade_date=trade_date, records=records)
    yyyymmdd = trade_date.replace("-", "")
    csv_name = f"BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(csv_name, csv_content)

    return buffer.getvalue()
