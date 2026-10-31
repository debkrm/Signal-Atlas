import datetime
from decimal import Decimal
from unittest.mock import MagicMock
import pytest
from sqlalchemy import select, func

from signal_atlas.db.models import (
    DailyPriceRaw,
    IngestionRun,
    Instrument,
    InstrumentSymbolHistory,
    TradingCalendar,
)
from signal_atlas.ingestion.archiver import RawArchiver
from signal_atlas.ingestion.pipeline import IngestionPipeline
from tests.fixtures.sample_udiff import create_sample_udiff_zip


def test_pipeline_integration_end_to_end(tmp_path, test_db):
    trade_date = datetime.date(2024, 10, 25)
    sample_zip = create_sample_udiff_zip(trade_date=str(trade_date))

    # Mock downloader to return test fixture without network access
    mock_downloader = MagicMock()
    mock_downloader.download.return_value = (
        "BhavCopy_NSE_CM_0_0_0_20241025_F_0000.csv.zip",
        sample_zip,
        "https://test.nseindia.com/sample.zip",
    )

    # Use tmp_path for archiving
    archiver = RawArchiver(raw_dir=tmp_path / "raw")

    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)
    res = pipeline.ingest_date(trade_date=trade_date, session=test_db)

    assert res["status"] == "SUCCESS"
    assert res["row_count"] == 3
    assert res["quarantine_count"] == 0

    # Verify database persistence
    run = test_db.execute(select(IngestionRun).where(IngestionRun.trade_date == trade_date)).scalar_one()
    assert run.status == "SUCCESS"
    assert run.row_count == 3

    # Check daily prices
    prices = test_db.execute(select(DailyPriceRaw).where(DailyPriceRaw.trade_date == trade_date)).scalars().all()
    assert len(prices) == 3

    # Check instruments and symbol history
    instruments = test_db.execute(select(Instrument)).scalars().all()
    assert len(instruments) == 3
    histories = test_db.execute(select(InstrumentSymbolHistory)).scalars().all()
    assert len(histories) == 3

    # Check calendar marked as trading day
    cal = test_db.get(TradingCalendar, trade_date)
    assert cal is not None
    assert cal.is_trading_day is True


def test_pipeline_idempotency(tmp_path, test_db):
    trade_date = datetime.date(2024, 10, 25)
    sample_zip = create_sample_udiff_zip(trade_date=str(trade_date))

    mock_downloader = MagicMock()
    mock_downloader.download.return_value = (
        "BhavCopy_NSE_CM_0_0_0_20241025_F_0000.csv.zip",
        sample_zip,
        "https://test.nseindia.com/sample.zip",
    )

    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)

    # Run 1: initial ingestion
    res1 = pipeline.ingest_date(trade_date=trade_date, session=test_db)
    assert res1["status"] == "SUCCESS"
    assert res1["row_count"] == 3

    # Run 2: idempotent retry without --force
    res2 = pipeline.ingest_date(trade_date=trade_date, session=test_db)
    assert res2["status"] == "ALREADY_INGESTED"
    assert res2["run_id"] == res1["run_id"]

    # Verify no duplicates were created in the database
    price_count = test_db.execute(
        select(func.count(DailyPriceRaw.id)).where(DailyPriceRaw.trade_date == trade_date)
    ).scalar()
    assert price_count == 3


def test_pipeline_series_transition_preserves_instrument_identity(tmp_path, test_db):
    """
    Test that an instrument transitioning from EQ to BE series preserves the same instrument_id.
    """
    date1 = datetime.date(2024, 10, 24)
    date2 = datetime.date(2024, 10, 25)

    # Day 1: XYZ is in series EQ
    rec_day1 = [
        {
            "symbol": "XYZCORP",
            "series": "EQ",
            "isin": "INE999A01019",
            "name": "XYZ CORP LTD",
            "open": "100.00",
            "high": "105.00",
            "low": "98.00",
            "close": "102.00",
            "prev_close": "99.00",
            "vol": "10000",
            "val": "1020000.00",
        }
    ]
    zip_day1 = create_sample_udiff_zip(trade_date=str(date1), records=rec_day1)

    # Day 2: XYZ shifted to BE series (Trade-for-Trade surveillance), same ISIN
    rec_day2 = [
        {
            "symbol": "XYZCORP",
            "series": "BE",
            "isin": "INE999A01019",
            "name": "XYZ CORP LTD",
            "open": "102.00",
            "high": "104.00",
            "low": "101.00",
            "close": "103.00",
            "prev_close": "102.00",
            "vol": "5000",
            "val": "515000.00",
        }
    ]
    zip_day2 = create_sample_udiff_zip(trade_date=str(date2), records=rec_day2)

    mock_downloader = MagicMock()
    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)

    # Ingest Day 1
    mock_downloader.download.return_value = ("day1.zip", zip_day1, "http://day1")
    pipeline.ingest_date(trade_date=date1, session=test_db)

    # Ingest Day 2
    mock_downloader.download.return_value = ("day2.zip", zip_day2, "http://day2")
    pipeline.ingest_date(trade_date=date2, session=test_db)

    # Verification: Only 1 Instrument should exist!
    instruments = test_db.execute(select(Instrument)).scalars().all()
    assert len(instruments) == 1
    inst = instruments[0]

    # But 2 symbol history records should exist (one for EQ, one for BE)
    histories = test_db.execute(
        select(InstrumentSymbolHistory).where(InstrumentSymbolHistory.instrument_id == inst.instrument_id)
    ).scalars().all()
    assert len(histories) == 2
    series_set = {h.series for h in histories}
    assert series_set == {"EQ", "BE"}

    # And 2 daily price records, both mapped to the same instrument_id
    prices = test_db.execute(
        select(DailyPriceRaw).where(DailyPriceRaw.instrument_id == inst.instrument_id)
    ).scalars().all()
    assert len(prices) == 2


def test_pipeline_legacy_ingestion(tmp_path, test_db):
    """Verify ingestion pipeline seamlessly ingests Legacy Bhavcopy files (< 2024-07-08)."""
    from tests.fixtures.sample_legacy import create_sample_legacy_zip

    trade_date = datetime.date(2022, 7, 28)
    sample_zip = create_sample_legacy_zip(trade_date_str="28-JUL-2022")

    mock_downloader = MagicMock()
    mock_downloader.download.return_value = (
        "cm28JUL2022bhav.csv.zip",
        sample_zip,
        "https://archives.nseindia.com/sample_legacy.zip",
    )

    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)
    res = pipeline.ingest_date(trade_date=trade_date, session=test_db)

    assert res["status"] == "SUCCESS"
    assert res["source"] == "NSE_LEGACY"
    assert res["row_count"] == 3

    # Check ingestion run
    run = test_db.execute(select(IngestionRun).where(IngestionRun.trade_date == trade_date)).scalar_one()
    assert run.source == "NSE_LEGACY"
    assert run.parser_version == "legacy_v1"
    assert run.row_count == 3

    # Verify prices in db
    prices = test_db.execute(select(DailyPriceRaw).where(DailyPriceRaw.trade_date == trade_date)).scalars().all()
    assert len(prices) == 3
    # Check that literal 'NA' series was preserved in the database
    na_price = next(p for p in prices if p.series == "NA")
    assert na_price.series == "NA"
    assert na_price.open == Decimal("1100.00")


def test_pipeline_ingest_range_skips_weekends(tmp_path, test_db):
    """Verify ingest_range skips weekends and processes consecutive trading dates."""
    date_thu = datetime.date(2024, 10, 24)
    date_fri = datetime.date(2024, 10, 25)
    date_sat = datetime.date(2024, 10, 26)  # weekend, should be skipped
    date_sun = datetime.date(2024, 10, 27)  # weekend, should be skipped

    zip_thu = create_sample_udiff_zip(trade_date=str(date_thu))
    zip_fri = create_sample_udiff_zip(trade_date=str(date_fri))

    mock_downloader = MagicMock()

    def mock_download(dt, use_cache=True):
        if dt == date_thu:
            return "bhav_thu.zip", zip_thu, "http://thu"
        elif dt == date_fri:
            return "bhav_fri.zip", zip_fri, "http://fri"
        else:
            raise RuntimeError(f"Unexpected date {dt}")

    mock_downloader.download.side_effect = mock_download
    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)

    # Ingest Thursday through Sunday
    results = pipeline.ingest_range(start_date=date_thu, end_date=date_sun)

    # Weekend days should not even be attempted
    assert len(results) == 2
    dates = [r["trade_date"] for r in results]
    assert "2024-10-24" in dates
    assert "2024-10-25" in dates
    assert "2024-10-26" not in dates
    assert "2024-10-27" not in dates
