import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class NormalizedRecord(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    trade_date: datetime.date
    symbol: str
    series: str
    isin: str
    name: Optional[str] = None
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    last: Optional[Decimal] = None
    prev_close: Decimal
    volume: int
    traded_value: Decimal
    trades_count: Optional[int] = None
    segment: str
    instrument_type: str
    raw_payload: Optional[Dict[str, Any]] = None
    source_row_number: Optional[int] = None


class NormalizerError(Exception):
    pass


class RecordNormalizer:
    """
    Normalizes raw CM-UDiFF dictionary records into strongly typed,
    decimal-safe NormalizedRecord models.
    """

    @staticmethod
    def _to_decimal(val: Any, default: Optional[Decimal] = None) -> Decimal:
        if val is None or str(val).strip() in ("", "-", "nan", "NaN"):
            if default is not None:
                return default
            raise ValueError("Value cannot be converted to Decimal")
        try:
            return Decimal(str(val).strip())
        except (InvalidOperation, ValueError) as e:
            raise ValueError(f"Invalid decimal string: {val}") from e

    @staticmethod
    def _to_int(val: Any, default: int = 0) -> int:
        if val is None or str(val).strip() in ("", "-", "nan", "NaN"):
            return default
        try:
            # Handle possible float strings like "100.0"
            f_val = float(str(val).strip())
            return int(f_val)
        except ValueError as e:
            raise ValueError(f"Invalid integer string: {val}") from e

    @staticmethod
    def _to_date(val: Any) -> datetime.date:
        if isinstance(val, datetime.date):
            return val
        s = str(val).strip()
        # Common format in CM-UDiFF is YYYY-MM-DD
        try:
            return datetime.datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            # Fallback format for alternative dates e.g. DD-Mon-YYYY
            try:
                return datetime.datetime.strptime(s, "%d-%b-%Y").date()
            except ValueError as e:
                raise ValueError(f"Invalid date string: {val}") from e

    def normalize_record(self, raw: Dict[str, Any], row_number: Optional[int] = None) -> NormalizedRecord:
        """
        Normalize a single raw record from either CM-UDiFF or Legacy Bhavcopy.

        Raises:
            ValueError: If parsing or type conversion fails.
        """
        # Detect era by presence of TradDt (UDiFF) vs TIMESTAMP (Legacy)
        if "TradDt" in raw:
            trade_date = self._to_date(raw.get("TradDt"))
            symbol = str(raw.get("TckrSymb", "")).strip().upper()
            series = str(raw.get("SctySrs", "")).strip().upper()
            isin = str(raw.get("ISIN", "")).strip().upper()
            name = str(raw.get("FinInstrmNm", "")).strip() or None

            open_p = self._to_decimal(raw.get("OpnPric"))
            high_p = self._to_decimal(raw.get("HghPric"))
            low_p = self._to_decimal(raw.get("LwPric"))
            close_p = self._to_decimal(raw.get("ClsPric"))

            last_raw = raw.get("LastPric")
            last_p = self._to_decimal(last_raw) if last_raw and str(last_raw).strip() not in ("", "-", "nan") else None

            prev_close_p = self._to_decimal(raw.get("PrvsClsgPric"))
            volume = self._to_int(raw.get("TtlTradgVol"), default=0)
            traded_val = self._to_decimal(raw.get("TtlTrfVal"), default=Decimal("0.0"))

            trades_count_raw = raw.get("TtlNbOfTxsExctd")
            trades_count = (
                self._to_int(trades_count_raw)
                if trades_count_raw and str(trades_count_raw).strip() not in ("", "-", "nan")
                else None
            )

            segment = str(raw.get("Sgmt", "CM")).strip().upper()
            instr_type = str(raw.get("FinInstrmTp", "STK")).strip().upper()

        elif "TIMESTAMP" in raw:
            trade_date = self._to_date(raw.get("TIMESTAMP"))
            symbol = str(raw.get("SYMBOL", "")).strip().upper()
            series = str(raw.get("SERIES", "")).strip().upper()
            isin = str(raw.get("ISIN", "")).strip().upper()
            name = None

            open_p = self._to_decimal(raw.get("OPEN"))
            high_p = self._to_decimal(raw.get("HIGH"))
            low_p = self._to_decimal(raw.get("LOW"))
            close_p = self._to_decimal(raw.get("CLOSE"))

            last_raw = raw.get("LAST")
            last_p = self._to_decimal(last_raw) if last_raw and str(last_raw).strip() not in ("", "-", "nan") else None

            prev_close_p = self._to_decimal(raw.get("PREVCLOSE"))
            volume = self._to_int(raw.get("TOTTRDQTY"), default=0)
            traded_val = self._to_decimal(raw.get("TOTTRDVAL"), default=Decimal("0.0"))

            trades_count_raw = raw.get("TOTALTRADES")
            trades_count = (
                self._to_int(trades_count_raw)
                if trades_count_raw and str(trades_count_raw).strip() not in ("", "-", "nan")
                else None
            )

            segment = "CM"
            instr_type = "STK"
        else:
            raise ValueError(f"Unrecognized Bhavcopy format. Available keys: {list(raw.keys())[:10]}")

        return NormalizedRecord(
            trade_date=trade_date,
            symbol=symbol,
            series=series,
            isin=isin,
            name=name,
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            last=last_p,
            prev_close=prev_close_p,
            volume=volume,
            traded_value=traded_val,
            trades_count=trades_count,
            segment=segment,
            instrument_type=instr_type,
            raw_payload=raw,
            source_row_number=row_number,
        )

    def normalize_batch(self, raw_records: List[Dict[str, Any]]) -> List[NormalizedRecord]:
        normalized = []
        for idx, raw in enumerate(raw_records, start=2):
            normalized.append(self.normalize_record(raw, row_number=idx))
        return normalized
