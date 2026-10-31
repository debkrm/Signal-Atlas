import datetime
from decimal import Decimal
import pytest

from signal_atlas.ingestion.normalizer import RecordNormalizer


def test_record_normalizer_valid():
    normalizer = RecordNormalizer()
    raw = {
        "TradDt": "2024-10-25",
        "TckrSymb": " reliance ",
        "SctySrs": " eq ",
        "ISIN": " ine002a01018 ",
        "FinInstrmNm": "Reliance Industries Ltd",
        "OpnPric": "2900.05",
        "HghPric": "2950.50",
        "LwPric": "2890.10",
        "ClsPric": "2940.25",
        "LastPric": "2941.00",
        "PrvsClsgPric": "2895.00",
        "TtlTradgVol": "1500000",
        "TtlTrfVal": "4395000000.75",
        "TtlNbOfTxsExctd": "85000",
        "Sgmt": "cm",
        "FinInstrmTp": "stk",
    }

    norm = normalizer.normalize_record(raw)
    assert norm.trade_date == datetime.date(2024, 10, 25)
    assert norm.symbol == "RELIANCE"
    assert norm.series == "EQ"
    assert norm.isin == "INE002A01018"
    assert norm.name == "Reliance Industries Ltd"
    assert norm.open == Decimal("2900.05")
    assert norm.high == Decimal("2950.50")
    assert norm.low == Decimal("2890.10")
    assert norm.close == Decimal("2940.25")
    assert norm.last == Decimal("2941.00")
    assert norm.prev_close == Decimal("2895.00")
    assert norm.volume == 1500000
    assert norm.traded_value == Decimal("4395000000.75")
    assert norm.trades_count == 85000
    assert norm.segment == "CM"
    assert norm.instrument_type == "STK"


def test_financial_decimal_precision():
    """Ensure floating-point representation errors like 0.1 + 0.2 != 0.3 do not happen."""
    normalizer = RecordNormalizer()
    val = normalizer._to_decimal("147.80")
    assert isinstance(val, Decimal)
    assert str(val) == "147.80"
    # Exact decimal arithmetic
    assert val * Decimal("10") == Decimal("1478.00")


def test_invalid_decimal_raises():
    normalizer = RecordNormalizer()
    with pytest.raises(ValueError, match="Invalid decimal string"):
        normalizer._to_decimal("NOT_A_NUMBER")


def test_invalid_date_raises():
    normalizer = RecordNormalizer()
    with pytest.raises(ValueError, match="Invalid date string"):
        normalizer._to_date("INVALID-DATE")


def test_legacy_record_normalizer_valid():
    """Ensure Legacy Bhavcopy records normalize correctly into NormalizedRecord schema."""
    normalizer = RecordNormalizer()
    raw = {
        "TIMESTAMP": "28-JUL-2022",
        "SYMBOL": " TATASTEEL ",
        "SERIES": " eq ",
        "OPEN": "98.10",
        "HIGH": "102.00",
        "LOW": "97.15",
        "CLOSE": "100.35",
        "LAST": "100.40",
        "PREVCLOSE": "959.40",
        "TOTTRDQTY": "137156107",
        "TOTTRDVAL": "13763615337.45",
        "TOTALTRADES": "350000",
        "ISIN": " ine081a01012 ",
    }

    norm = normalizer.normalize_record(raw)
    assert norm.trade_date == datetime.date(2022, 7, 28)
    assert norm.symbol == "TATASTEEL"
    assert norm.series == "EQ"
    assert norm.isin == "INE081A01012"
    assert norm.name is None
    assert norm.open == Decimal("98.10")
    assert norm.high == Decimal("102.00")
    assert norm.low == Decimal("97.15")
    assert norm.close == Decimal("100.35")
    assert norm.last == Decimal("100.40")
    assert norm.prev_close == Decimal("959.40")
    assert norm.volume == 137156107
    assert norm.traded_value == Decimal("13763615337.45")
    assert norm.trades_count == 350000
    assert norm.segment == "CM"
    assert norm.instrument_type == "STK"


def test_regression_literal_na_series():
    """
    Regression Test Safeguard:
    1. 'NA' remains the literal series value (not NaN).
    2. Empty fields remain distinguishable from 'NA'.
    3. Invalid numeric fields are not silently converted to zero.
    """
    normalizer = RecordNormalizer()

    # 1. 'NA' remains literal series value
    raw_na = {
        "TIMESTAMP": "28-JUL-2022",
        "SYMBOL": "NHAI76",
        "SERIES": "NA",
        "OPEN": "1100.00",
        "HIGH": "1110.00",
        "LOW": "1100.00",
        "CLOSE": "1105.00",
        "LAST": "1105.00",
        "PREVCLOSE": "1102.00",
        "TOTTRDQTY": "500",
        "TOTTRDVAL": "552500.00",
        "TOTALTRADES": "15",
        "ISIN": "INE906B07EJ8",
    }
    norm_na = normalizer.normalize_record(raw_na)
    assert norm_na.series == "NA"
    assert norm_na.series != "NaN"
    assert norm_na.series != ""

    # 2. Empty fields remain distinguishable from 'NA'
    raw_empty_series = dict(raw_na)
    raw_empty_series["SERIES"] = ""
    norm_empty = normalizer.normalize_record(raw_empty_series)
    assert norm_empty.series == ""
    assert norm_empty.series != "NA"

    # Missing optional fields are None, distinguishable from 'NA'
    assert norm_na.name is None
    assert norm_na.name != "NA"

    # 3. Invalid numeric fields are NOT silently converted to zero
    raw_invalid_price = dict(raw_na)
    raw_invalid_price["OPEN"] = "NOT_A_PRICE"
    with pytest.raises(ValueError, match="Invalid decimal string"):
        normalizer.normalize_record(raw_invalid_price)

    raw_invalid_close = dict(raw_na)
    raw_invalid_close["CLOSE"] = "nan"
    with pytest.raises(ValueError, match="Value cannot be converted to Decimal"):
        normalizer.normalize_record(raw_invalid_close)

    raw_invalid_vol = dict(raw_na)
    raw_invalid_vol["TOTTRDQTY"] = "INVALID_INT"
    with pytest.raises(ValueError, match="Invalid integer string"):
        normalizer.normalize_record(raw_invalid_vol)
