import datetime
from decimal import Decimal
import pytest

from signal_atlas.ingestion.normalizer import NormalizedRecord
from signal_atlas.quality.validation import BatchValidator


def _make_record(
    symbol="TATASTEEL",
    series="EQ",
    isin="INE081A01012",
    trade_date=datetime.date(2024, 10, 25),
    open_p=Decimal("145.00"),
    high_p=Decimal("150.00"),
    low_p=Decimal("140.00"),
    close_p=Decimal("148.00"),
    prev_close=Decimal("144.00"),
    vol=10000,
    val=Decimal("1480000.00"),
) -> NormalizedRecord:
    return NormalizedRecord(
        trade_date=trade_date,
        symbol=symbol,
        series=series,
        isin=isin,
        name="Test Company",
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        prev_close=prev_close,
        volume=vol,
        traded_value=val,
        segment="CM",
        instrument_type="STK",
    )


def test_validator_valid_record():
    validator = BatchValidator()
    rec = _make_record()
    valid, result = validator.validate_batch([rec], expected_date=datetime.date(2024, 10, 25))

    assert len(valid) == 1
    assert result.valid_count == 1
    assert result.quarantine_count == 0
    assert not result.is_fatal


def test_validator_date_mismatch_fatal():
    validator = BatchValidator()
    rec = _make_record(trade_date=datetime.date(2024, 10, 24))
    valid, result = validator.validate_batch([rec], expected_date=datetime.date(2024, 10, 25))

    assert len(valid) == 0
    assert result.is_fatal
    assert "Batch date mismatch" in result.fatal_error


def test_validator_low_exceeds_high_quarantine():
    validator = BatchValidator()
    rec = _make_record(high_p=Decimal("140.00"), low_p=Decimal("150.00"))
    valid, result = validator.validate_batch([rec], expected_date=datetime.date(2024, 10, 25))

    assert len(valid) == 0
    assert result.quarantine_count == 1
    assert result.issues[0].rule == "LOW_EXCEEDS_HIGH"


def test_validator_close_out_of_range_quarantine():
    validator = BatchValidator()
    rec = _make_record(high_p=Decimal("150.00"), low_p=Decimal("140.00"), close_p=Decimal("155.00"))
    valid, result = validator.validate_batch([rec], expected_date=datetime.date(2024, 10, 25))

    assert len(valid) == 0
    assert result.quarantine_count == 1
    assert result.issues[0].rule == "CLOSE_OUT_OF_RANGE"


def test_validator_negative_price_quarantine():
    validator = BatchValidator()
    rec = _make_record(open_p=Decimal("-10.00"))
    valid, result = validator.validate_batch([rec], expected_date=datetime.date(2024, 10, 25))

    assert len(valid) == 0
    assert result.quarantine_count == 1
    assert result.issues[0].rule == "NON_POSITIVE_PRICE"


def test_validator_invalid_isin_quarantine():
    validator = BatchValidator()
    rec = _make_record(isin="SHORT_ISIN")
    valid, result = validator.validate_batch([rec], expected_date=datetime.date(2024, 10, 25))

    assert len(valid) == 0
    assert result.quarantine_count == 1
    assert result.issues[0].rule == "INVALID_ISIN"


def test_validator_duplicate_detection_quarantine():
    validator = BatchValidator()
    rec1 = _make_record()
    rec2 = _make_record()
    valid, result = validator.validate_batch([rec1, rec2], expected_date=datetime.date(2024, 10, 25))

    assert len(valid) == 1
    assert result.quarantine_count == 1
    assert result.issues[0].rule == "DUPLICATE_RECORD"


def test_validator_large_price_movement_warning():
    validator = BatchValidator()
    # 80% price move from 100 to 180
    rec = _make_record(
        prev_close=Decimal("100.00"),
        open_p=Decimal("170.00"),
        high_p=Decimal("185.00"),
        low_p=Decimal("165.00"),
        close_p=Decimal("180.00"),
    )
    valid, result = validator.validate_batch([rec], expected_date=datetime.date(2024, 10, 25))

    assert len(valid) == 1
    assert result.warning_count == 1
    assert result.issues[0].rule == "LARGE_PRICE_MOVEMENT"
