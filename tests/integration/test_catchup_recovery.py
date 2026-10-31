import datetime
from decimal import Decimal
import io
from unittest.mock import MagicMock, patch
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
from signal_atlas.ingestion.pipeline import IngestionPipeline, PipelineError
from signal_atlas.providers.nse.calendar import NSETradingCalendar
from signal_atlas.providers.nse.downloader import DownloaderError
from tests.fixtures.sample_udiff import create_sample_udiff_zip


def test_catchup_discovers_internal_gap(tmp_path, test_db):
    """
    Test Item B: Catch-up engine MUST discover internal missing gaps between
    two successfully ingested trading dates (e.g. Oct 7, Oct 8, Oct 10 present; Oct 9 missing).
    """
    d_mon = datetime.date(2024, 10, 7)
    d_tue = datetime.date(2024, 10, 8)
    d_wed = datetime.date(2024, 10, 9)  # Missing internal gap!
    d_thu = datetime.date(2024, 10, 10)
    d_fri = datetime.date(2024, 10, 11)

    zip_mon = create_sample_udiff_zip(trade_date=str(d_mon))
    zip_tue = create_sample_udiff_zip(trade_date=str(d_tue))
    zip_wed = create_sample_udiff_zip(trade_date=str(d_wed))
    zip_thu = create_sample_udiff_zip(trade_date=str(d_thu))
    zip_fri = create_sample_udiff_zip(trade_date=str(d_fri))

    zip_map = {
        d_mon: zip_mon,
        d_tue: zip_tue,
        d_wed: zip_wed,
        d_thu: zip_thu,
        d_fri: zip_fri,
    }

    mock_downloader = MagicMock()
    mock_downloader.download.side_effect = lambda dt, use_cache=True: (
        f"bhav_{dt}.zip",
        zip_map[dt],
        f"http://test/{dt}",
    )

    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)

    # 1. Ingest Monday, Tuesday, Thursday, Friday (intentionally omitting Wednesday Oct 9)
    pipeline.ingest_date(d_mon, session=test_db)
    pipeline.ingest_date(d_tue, session=test_db)
    pipeline.ingest_date(d_thu, session=test_db)
    pipeline.ingest_date(d_fri, session=test_db)

    # Confirm 4 dates in DB and Oct 9 is MISSING
    runs_before = test_db.execute(
        select(IngestionRun.trade_date).where(IngestionRun.status == "SUCCESS")
    ).scalars().all()
    assert d_wed not in runs_before
    assert len(runs_before) == 4

    # 2. Run catch-up (--since-last) scanning from Monday to Friday
    catchup_results = pipeline.ingest_since_last(
        start_date=d_mon,
        target_date=d_fri,
        session=test_db,
    )

    # Verification: catch-up MUST discover Oct 9 and ingest it!
    assert len(catchup_results) == 1
    assert catchup_results[0]["trade_date"] == str(d_wed)
    assert catchup_results[0]["status"] == "SUCCESS"

    # Confirm Oct 9 is now in DB
    runs_after = test_db.execute(
        select(IngestionRun.trade_date).where(IngestionRun.status == "SUCCESS")
    ).scalars().all()
    assert d_wed in runs_after
    assert len(runs_after) == 5


def test_recovery_after_download_failure(tmp_path, test_db):
    """Verify pipeline records failed attempt and successfully recovers on retry."""
    dt = datetime.date(2024, 10, 9)
    valid_zip = create_sample_udiff_zip(trade_date=str(dt))

    mock_downloader = MagicMock()
    # First attempt fails with network error
    mock_downloader.download.side_effect = DownloaderError("Simulated network timeout")

    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)

    # Attempt 1: fails
    with pytest.raises(PipelineError, match="Download failed"):
        pipeline.ingest_date(dt, session=test_db)

    # Attempt 2: network recovers, retry with force=True
    mock_downloader.download.side_effect = None
    mock_downloader.download.return_value = ("bhav.zip", valid_zip, "http://valid")

    res = pipeline.ingest_date(dt, force=True, session=test_db)
    assert res["status"] == "SUCCESS"
    assert res["row_count"] == 3


def test_recovery_after_parser_error(tmp_path, test_db):
    """Verify pipeline records FAILED status on corrupted archive and recovers on retry."""
    dt = datetime.date(2024, 10, 9)
    valid_zip = create_sample_udiff_zip(trade_date=str(dt))

    mock_downloader = MagicMock()
    # Corrupt zip (header without valid central directory)
    mock_downloader.download.return_value = ("bhav.zip", b"PK\x03\x04corrupteddata", "http://corrupt")

    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)

    # Attempt 1: raises parse error
    with pytest.raises(PipelineError, match="Parse error"):
        pipeline.ingest_date(dt, session=test_db)

    # Verify run marked FAILED
    failed_run = test_db.execute(
        select(IngestionRun).where(IngestionRun.trade_date == dt)
    ).scalar_one()
    assert failed_run.status == "FAILED"

    # Attempt 2: retry with valid zip and force=True
    mock_downloader.download.return_value = ("bhav.zip", valid_zip, "http://valid")
    res = pipeline.ingest_date(dt, force=True, session=test_db)
    assert res["status"] == "SUCCESS"
    assert res["row_count"] == 3


def test_archive_conflict_preservation_without_silent_overwrite(tmp_path):
    """Verify archiver preserves conflicting revisions when SHA256 differs."""
    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    filename = "test_archive.zip"
    content_v1 = b"PK\x03\x04content_v1"
    content_v2 = b"PK\x03\x04content_v2_different_hash"

    # Write v1
    p1, sha1 = archiver.archive(filename, content_v1, trade_date=datetime.date(2024, 6, 5))
    assert p1.exists()

    # Attempt to write v2 with different hash
    p2, sha2 = archiver.archive(filename, content_v2, trade_date=datetime.date(2024, 6, 5))

    # Verification: p1 must NOT be overwritten! Both files must exist!
    assert sha1 != sha2
    assert p1.exists()
    assert p2.exists()
    assert p1 != p2
    assert "conflict" in str(p2)
    assert p1.read_bytes() == content_v1
    assert p2.read_bytes() == content_v2


def test_overlapping_series_symbol_history(tmp_path, test_db):
    """
    Test Item C: Check that instrument_symbol_history supports overlapping
    effective dates when an instrument appears in multiple series on the same date (e.g. EQ and BL/BO).
    """
    trade_date = datetime.date(2024, 7, 15)
    records = [
        {
            "symbol": "GODREJCP",
            "series": "EQ",
            "isin": "INE102D01028",
            "name": "Godrej Consumer Products Ltd",
            "open": "1440.00",
            "high": "1450.00",
            "low": "1430.00",
            "close": "1436.70",
            "last": "1436.70",
            "prev_close": "1443.00",
            "vol": "521240",
            "val": "748865508.00",
        },
        {
            "symbol": "GODREJCP",
            "series": "BL",  # Block Deal on same date!
            "isin": "INE102D01028",
            "name": "Godrej Consumer Products Ltd",
            "open": "1443.90",
            "high": "1443.90",
            "low": "1443.90",
            "close": "1443.90",
            "last": "1443.90",
            "prev_close": "1443.90",
            "vol": "11392858",
            "val": "16450147666.20",
        },
    ]

    zip_bytes = create_sample_udiff_zip(trade_date=str(trade_date), records=records)

    mock_downloader = MagicMock()
    mock_downloader.download.return_value = ("godrej_block.zip", zip_bytes, "http://test")
    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)

    res = pipeline.ingest_date(trade_date=trade_date, session=test_db)
    assert res["status"] == "SUCCESS"
    assert res["row_count"] == 2

    # Verification 1: Exactly ONE instrument exists for INE102D01028
    inst = test_db.execute(select(Instrument)).scalar_one()
    assert inst is not None

    # Verification 2: Two concurrent symbol history entries exist for the same instrument
    histories = test_db.execute(
        select(InstrumentSymbolHistory).where(InstrumentSymbolHistory.instrument_id == inst.instrument_id)
    ).scalars().all()

    assert len(histories) == 2
    series_map = {h.series: h for h in histories}
    assert "EQ" in series_map
    assert "BL" in series_map

    # Overlapping validity: both are valid starting on the same trade date!
    assert series_map["EQ"].valid_from == trade_date
    assert series_map["BL"].valid_from == trade_date
    assert series_map["EQ"].valid_to is None
    assert series_map["BL"].valid_to is None

    # Verification 3: Two distinct daily price rows exist for the same instrument
    prices = test_db.execute(
        select(DailyPriceRaw).where(DailyPriceRaw.instrument_id == inst.instrument_id)
    ).scalars().all()
    assert len(prices) == 2
    p_series = {p.series for p in prices}
    assert p_series == {"EQ", "BL"}


def test_recovery_after_database_failure(tmp_path, test_db):
    """Verify transaction rollback on DB failure leaves no partial state, and subsequent retry succeeds."""
    dt = datetime.date(2024, 10, 10)
    valid_zip = create_sample_udiff_zip(trade_date=str(dt))

    mock_downloader = MagicMock()
    mock_downloader.download.return_value = ("bhav.zip", valid_zip, "http://valid")
    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)

    # Attempt 1: DB flush fails (simulate integrity or connection error)
    with patch.object(test_db, "flush", side_effect=RuntimeError("Simulated DB connection lost")):
        with pytest.raises(RuntimeError, match="Simulated DB connection lost"):
            pipeline.ingest_date(dt, session=test_db)
    test_db.rollback()

    # Verify no price rows were committed
    prices = test_db.execute(
        select(DailyPriceRaw).where(DailyPriceRaw.trade_date == dt)
    ).scalars().all()
    assert len(prices) == 0

    # Attempt 2: retry without DB failure
    res = pipeline.ingest_date(dt, force=True, session=test_db)
    assert res["status"] == "SUCCESS"
    assert res["row_count"] == 3

    # Verify prices are now committed
    prices_after = test_db.execute(
        select(DailyPriceRaw).where(DailyPriceRaw.trade_date == dt)
    ).scalars().all()
    assert len(prices_after) == 3


def test_interrupted_batch_recovery(tmp_path, test_db):
    """Verify an interrupted multi-day batch can cleanly resume without duplicating records."""
    dates = [
        datetime.date(2024, 10, 14),
        datetime.date(2024, 10, 15),
        datetime.date(2024, 10, 16),
        datetime.date(2024, 10, 17),
        datetime.date(2024, 10, 18),
    ]
    zip_map = {d: create_sample_udiff_zip(trade_date=str(d)) for d in dates}

    mock_downloader = MagicMock()
    mock_downloader.download.side_effect = lambda dt, use_cache=True: (
        f"bhav_{dt}.zip",
        zip_map[dt],
        f"http://test/{dt}",
    )
    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)

    # Ingest dates 1 and 2, then interrupt (simulate crash before date 3)
    pipeline.ingest_date(dates[0], session=test_db)
    pipeline.ingest_date(dates[1], session=test_db)

    assert test_db.execute(select(func.count(DailyPriceRaw.id))).scalar() == 6

    # Resume the entire batch from date 1 to date 5
    batch_results = pipeline.ingest_range(start_date=dates[0], end_date=dates[4], session=test_db)

    # Verification: Dates 0 and 1 are skipped as ALREADY_INGESTED, Dates 2, 3, 4 are ingested as SUCCESS
    assert len(batch_results) == 5
    assert batch_results[0]["status"] == "ALREADY_INGESTED"
    assert batch_results[1]["status"] == "ALREADY_INGESTED"
    assert batch_results[2]["status"] == "SUCCESS"
    assert batch_results[3]["status"] == "SUCCESS"
    assert batch_results[4]["status"] == "SUCCESS"

    # Total 5 dates * 3 rows = 15 rows total in DB (zero duplicates created)
    total_rows = test_db.execute(select(func.count(DailyPriceRaw.id))).scalar()
    assert total_rows == 15

