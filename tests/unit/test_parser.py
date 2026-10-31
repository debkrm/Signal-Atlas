import io
import zipfile
import pytest

from signal_atlas.providers.nse.legacy_parser import (
    LEGACY_REQUIRED_COLUMNS,
    LegacyBhavcopyParser,
)
from signal_atlas.providers.nse.udiff_parser import ParserError, UDiFFParser
from tests.fixtures.sample_legacy import create_sample_legacy_zip
from tests.fixtures.sample_udiff import create_sample_udiff_zip


def test_udiff_parser_valid_archive():
    zip_bytes = create_sample_udiff_zip(trade_date="2024-10-25")
    parser = UDiFFParser()
    records = parser.parse_archive(zip_bytes)

    assert len(records) == 3
    symbols = [r["TckrSymb"] for r in records]
    assert "RELIANCE" in symbols
    assert "TATASTEEL" in symbols
    assert "INFY" in symbols
    assert records[0]["TradDt"] == "2024-10-25"


def test_udiff_parser_corrupt_zip():
    parser = UDiFFParser()
    with pytest.raises(ParserError, match="Corrupted or invalid ZIP archive"):
        parser.parse_archive(b"not a valid zip binary content")


def test_udiff_parser_empty_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("empty.txt", "hello world")
    parser = UDiFFParser()
    with pytest.raises(ParserError, match="No CSV file found"):
        parser.parse_archive(buf.getvalue())


def test_udiff_parser_missing_required_columns():
    bad_csv = "TradDt,TckrSymb,ClsPric\n2024-10-25,RELIANCE,2900.0\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("bhav.csv", bad_csv)

    parser = UDiFFParser()
    with pytest.raises(ParserError, match="missing required columns"):
        parser.parse_archive(buf.getvalue())


def test_udiff_parser_literal_na_series():
    """Regression test: literal 'NA' series in UDiFF must not be converted to NaN."""
    records_data = [
        {
            "symbol": "NHAI76",
            "series": "NA",
            "isin": "INE906B07EJ8",
            "name": "NHAI 7.6 NCD",
            "open": "1100.00",
            "high": "1110.00",
            "low": "1100.00",
            "close": "1105.00",
            "last": "1105.00",
            "prev_close": "1102.00",
            "vol": "500",
            "val": "552500.00",
            "txs": "15",
        }
    ]
    zip_bytes = create_sample_udiff_zip(trade_date="2024-10-25", records=records_data)
    parser = UDiFFParser()
    records = parser.parse_archive(zip_bytes)

    assert len(records) == 1
    rec = records[0]
    assert rec["SctySrs"] == "NA"
    assert isinstance(rec["SctySrs"], str)
    assert rec["SctySrs"] != "NaN"
    assert rec["SctySrs"] != "nan"


def test_legacy_parser_valid_archive():
    zip_bytes = create_sample_legacy_zip(trade_date_str="28-JUL-2022")
    parser = LegacyBhavcopyParser()
    records = parser.parse_archive(zip_bytes)

    assert len(records) == 3
    symbols = [r["SYMBOL"] for r in records]
    assert "RELIANCE" in symbols
    assert "TATASTEEL" in symbols
    assert "NHAI76" in symbols
    assert records[0]["TIMESTAMP"] == "28-JUL-2022"

    # Confirm trailing unnamed column from legacy CSV is stripped
    for r in records:
        assert not any(k.startswith("Unnamed:") for k in r.keys())
        for req_col in LEGACY_REQUIRED_COLUMNS:
            assert req_col in r


def test_legacy_parser_corrupt_zip():
    parser = LegacyBhavcopyParser()
    with pytest.raises(ParserError, match="Corrupted or invalid ZIP archive"):
        parser.parse_archive(b"bad zip bytes")


def test_legacy_parser_empty_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("empty.txt", "data")
    parser = LegacyBhavcopyParser()
    with pytest.raises(ParserError, match="No CSV file found"):
        parser.parse_archive(buf.getvalue())


def test_legacy_parser_missing_required_columns():
    bad_csv = "SYMBOL,SERIES,CLOSE\nRELIANCE,EQ,2400.0\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("cm28JUL2022bhav.csv", bad_csv)

    parser = LegacyBhavcopyParser()
    with pytest.raises(ParserError, match="missing required columns"):
        parser.parse_archive(buf.getvalue())


def test_legacy_parser_literal_na_series():
    """Regression test: literal 'NA' series in Legacy Bhavcopy must not be converted to NaN."""
    zip_bytes = create_sample_legacy_zip(trade_date_str="28-JUL-2022")
    parser = LegacyBhavcopyParser()
    records = parser.parse_archive(zip_bytes)

    nhai_rec = next(r for r in records if r["SYMBOL"] == "NHAI76")
    assert nhai_rec["SERIES"] == "NA"
    assert isinstance(nhai_rec["SERIES"], str)
    assert nhai_rec["SERIES"] != "NaN"
    assert nhai_rec["SERIES"] != "nan"
