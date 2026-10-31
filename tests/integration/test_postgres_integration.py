import datetime
from decimal import Decimal
from unittest.mock import MagicMock
import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from signal_atlas.db.models import (
    DailyPriceRaw,
    IngestionRun,
    Instrument,
    InstrumentSymbolHistory,
    TradingCalendar,
)
from signal_atlas.ingestion.archiver import RawArchiver
from signal_atlas.ingestion.pipeline import IngestionPipeline, PipelineError
from tests.fixtures.sample_udiff import create_sample_udiff_zip


def test_postgres_unique_constraint_enforcement(pg_db):
    """
    Verify PostgreSQL strictly enforces the unique constraint (instrument_id, trade_date)
    and prevents duplicate daily prices.
    """
    trade_date = datetime.date(2024, 10, 25)
    inst = Instrument(instrument_id="inst-uuid-1", name="TEST CORP", status="ACTIVE")
    run = IngestionRun(
        run_id="run-uuid-1",
        source="NSE",
        trade_date=trade_date,
        file_name="test.zip",
        file_hash="hash123",
        parser_version="v1",
        status="SUCCESS",
        row_count=1,
    )
    pg_db.add_all([inst, run])
    pg_db.flush()

    p1 = DailyPriceRaw(
        instrument_id="inst-uuid-1",
        trade_date=trade_date,
        open=Decimal("100.00"),
        high=Decimal("105.00"),
        low=Decimal("95.00"),
        close=Decimal("102.50"),
        prev_close=Decimal("99.00"),
        volume=1000,
        traded_value=Decimal("102500.00"),
        series="EQ",
        source="NSE",
        ingestion_run_id="run-uuid-1",
    )
    pg_db.add(p1)
    pg_db.flush()

    # Second row with different series (e.g. BL block deal) for same instrument on same date is allowed
    p_bl = DailyPriceRaw(
        instrument_id="inst-uuid-1",
        trade_date=trade_date,
        open=Decimal("101.00"),
        high=Decimal("106.00"),
        low=Decimal("96.00"),
        close=Decimal("103.50"),
        prev_close=Decimal("99.00"),
        volume=2000,
        traded_value=Decimal("207000.00"),
        series="BL",
        source="NSE",
        ingestion_run_id="run-uuid-1",
    )
    pg_db.add(p_bl)
    pg_db.flush()

    # Third row with identical (instrument_id, trade_date, series) must raise IntegrityError
    p_dup = DailyPriceRaw(
        instrument_id="inst-uuid-1",
        trade_date=trade_date,
        open=Decimal("100.00"),
        high=Decimal("105.00"),
        low=Decimal("95.00"),
        close=Decimal("102.50"),
        prev_close=Decimal("99.00"),
        volume=1000,
        traded_value=Decimal("102500.00"),
        series="EQ",  # duplicate series
        source="NSE",
        ingestion_run_id="run-uuid-1",
    )
    pg_db.add(p_dup)
    with pytest.raises(IntegrityError, match="uq_daily_price_inst_date_series"):
        pg_db.flush()
    pg_db.rollback()


def test_postgres_exact_decimal_precision(pg_db):
    """
    Verify PostgreSQL numeric types preserve exact decimal representation without float drift.
    """
    trade_date = datetime.date(2024, 10, 25)
    inst = Instrument(instrument_id="inst-dec-1", name="PRECISION CORP", status="ACTIVE")
    run = IngestionRun(
        run_id="run-dec-1",
        source="NSE",
        trade_date=trade_date,
        file_name="dec.zip",
        file_hash="hash_dec",
        parser_version="v1",
        status="SUCCESS",
        row_count=1,
    )
    pg_db.add_all([inst, run])
    pg_db.flush()

    exact_price = Decimal("2940.25")
    exact_value = Decimal("4395000000.75")

    p = DailyPriceRaw(
        instrument_id="inst-dec-1",
        trade_date=trade_date,
        open=Decimal("2900.05"),
        high=Decimal("2950.50"),
        low=Decimal("2890.10"),
        close=exact_price,
        prev_close=Decimal("2895.00"),
        volume=1500000,
        traded_value=exact_value,
        series="EQ",
        source="NSE",
        ingestion_run_id="run-dec-1",
    )
    pg_db.add(p)
    pg_db.commit()

    saved = pg_db.execute(select(DailyPriceRaw).where(DailyPriceRaw.instrument_id == "inst-dec-1")).scalar_one()
    assert isinstance(saved.close, Decimal)
    assert saved.close == exact_price
    assert isinstance(saved.traded_value, Decimal)
    assert saved.traded_value == exact_value


def test_postgres_transaction_rollback_on_failure(tmp_path, pg_db):
    """
    Verify that an ingestion failure rolls back the entire transaction,
    leaving no partial records committed to PostgreSQL.
    """
    trade_date = datetime.date(2029, 10, 25)
    # Generate CSV with valid date in filename but date mismatch inside rows -> fatal validation failure
    bad_zip = create_sample_udiff_zip(trade_date="2029-10-24")

    mock_downloader = MagicMock()
    mock_downloader.download.return_value = (
        "BhavCopy_NSE_CM_0_0_0_20291025_F_0000.csv.zip",
        bad_zip,
        "https://test.nseindia.com/sample.zip",
    )
    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)

    initial_prices = pg_db.execute(select(func.count(DailyPriceRaw.id))).scalar()
    initial_instruments = pg_db.execute(select(func.count(Instrument.instrument_id))).scalar()

    with pytest.raises(PipelineError, match="Fatal validation error"):
        pipeline.ingest_date(trade_date=trade_date, session=pg_db)

    # Verify no partial prices or instruments were committed
    prices_after = pg_db.execute(select(func.count(DailyPriceRaw.id))).scalar()
    instruments_after = pg_db.execute(select(func.count(Instrument.instrument_id))).scalar()
    assert prices_after == initial_prices
    assert instruments_after == initial_instruments


def test_postgres_idempotent_ingestion(tmp_path, pg_db):
    """
    Verify that running ingestion twice against PostgreSQL produces identical row counts
    and skips redundant processing unless force=True.
    """
    trade_date = datetime.date(2029, 10, 25)
    sample_zip = create_sample_udiff_zip(trade_date=str(trade_date))

    mock_downloader = MagicMock()
    mock_downloader.download.return_value = (
        "BhavCopy_NSE_CM_0_0_0_20291025_F_0000.csv.zip",
        sample_zip,
        "https://test.nseindia.com/sample.zip",
    )
    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)

    # Initial Run
    res1 = pipeline.ingest_date(trade_date=trade_date, session=pg_db)
    assert res1["status"] == "SUCCESS"
    assert res1["row_count"] == 3

    # Re-run (Idempotent skip)
    res2 = pipeline.ingest_date(trade_date=trade_date, session=pg_db)
    assert res2["status"] == "ALREADY_INGESTED"

    price_count = pg_db.execute(
        select(func.count(DailyPriceRaw.id)).where(DailyPriceRaw.trade_date == trade_date)
    ).scalar()
    assert price_count == 3

    # Force re-ingestion
    res3 = pipeline.ingest_date(trade_date=trade_date, force=True, session=pg_db)
    assert res3["status"] == "SUCCESS"
    assert res3["row_count"] == 3

    price_count_after_force = pg_db.execute(
        select(func.count(DailyPriceRaw.id)).where(DailyPriceRaw.trade_date == trade_date)
    ).scalar()
    assert price_count_after_force == 3


def test_postgres_series_transition_preserves_instrument(tmp_path, pg_db):
    """
    Verify that an instrument moving from EQ to BE retains the same instrument_id in PostgreSQL.
    """
    d1 = datetime.date(2029, 10, 24)
    d2 = datetime.date(2029, 10, 25)

    rec1 = [{"symbol": "ABC", "series": "EQ", "isin": "INE123A01015", "open": "50.0", "high": "52.0", "low": "49.0", "close": "51.0", "prev_close": "48.0", "vol": "100", "val": "5100.0"}]
    rec2 = [{"symbol": "ABC", "series": "BE", "isin": "INE123A01015", "open": "51.0", "high": "53.0", "low": "50.0", "close": "52.0", "prev_close": "51.0", "vol": "200", "val": "10400.0"}]

    zip1 = create_sample_udiff_zip(trade_date=str(d1), records=rec1)
    zip2 = create_sample_udiff_zip(trade_date=str(d2), records=rec2)

    mock_downloader = MagicMock()
    archiver = RawArchiver(raw_dir=tmp_path / "raw")
    pipeline = IngestionPipeline(downloader=mock_downloader, archiver=archiver)

    mock_downloader.download.return_value = ("d1.zip", zip1, "http://d1")
    pipeline.ingest_date(trade_date=d1, session=pg_db)

    mock_downloader.download.return_value = ("d2.zip", zip2, "http://d2")
    pipeline.ingest_date(trade_date=d2, session=pg_db)

    instruments = pg_db.execute(
        select(Instrument).join(InstrumentSymbolHistory).where(InstrumentSymbolHistory.isin == "INE123A01015").distinct()
    ).scalars().all()
    assert len(instruments) == 1
    inst_id = instruments[0].instrument_id

    # Check symbol history in PostgreSQL has 2 records for the single instrument
    histories = pg_db.execute(
        select(InstrumentSymbolHistory).where(InstrumentSymbolHistory.instrument_id == inst_id)
    ).scalars().all()
    assert len(histories) == 2
    assert {h.series for h in histories} == {"EQ", "BE"}

    # Check daily prices has 2 rows for the same instrument_id
    prices = pg_db.execute(
        select(DailyPriceRaw).where(DailyPriceRaw.instrument_id == inst_id)
    ).scalars().all()
    assert len(prices) == 2
    assert {p.series for p in prices} == {"EQ", "BE"}
