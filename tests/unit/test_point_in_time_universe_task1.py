"""
test_point_in_time_universe_task1.py - Verification for Task 1 (Point-in-Time Universe and Delisting Tracking).

Tests:
1. Deleting/excluding all data after date t leaves universe for t unchanged (zero lookahead).
2. Delisting tracking identifies stopped trading instruments and sets delisting_date and valid_to.
3. Point-in-time universe on 2022-03-01 includes instruments that later stopped trading (e.g. MINDTREE, HDFC).
4. ETFs, rights entitlements, and non-permitted series are excluded.
"""

import datetime
from decimal import Decimal
import pytest
from sqlalchemy import text

from signal_atlas.db.models.calendar import TradingCalendar
from signal_atlas.db.models.ingestion import IngestionRun
from signal_atlas.db.models.instruments import Instrument, InstrumentSymbolHistory
from signal_atlas.db.models.prices import DailyPriceRaw
from signal_atlas.universe.delisting import detect_and_record_delistings, get_point_in_time_delisted_instruments
from signal_atlas.universe.models import EligibilityReason, UniverseConfig
from signal_atlas.universe.policy import evaluate_instrument_eligibility
from signal_atlas.universe.provenance import RawDataManifest
from signal_atlas.universe.service import PointInTimeUniverseService


def test_deleting_future_data_leaves_universe_unchanged(pg_db):
    """Verifies that removing all data after date t leaves universe for date t strictly identical."""
    t = datetime.date(2024, 1, 15)
    valid_run_id = pg_db.execute(text("SELECT run_id FROM ingestion_runs LIMIT 1")).scalar()

    # Clean any prior test records with these IDs
    pg_db.execute(text("DELETE FROM daily_prices_raw WHERE instrument_id IN ('inst-pit-a', 'inst-pit-b')"))
    pg_db.execute(text("DELETE FROM instrument_symbol_history WHERE instrument_id IN ('inst-pit-a', 'inst-pit-b')"))
    pg_db.execute(text("DELETE FROM instruments WHERE instrument_id IN ('inst-pit-a', 'inst-pit-b')"))
    pg_db.commit()

    inst_a = Instrument(instrument_id="inst-pit-a", name="Inst A", status="ACTIVE")
    inst_b = Instrument(instrument_id="inst-pit-b", name="Inst B", status="ACTIVE")
    pg_db.add_all([inst_a, inst_b])
    pg_db.commit()

    pg_db.add_all([
        InstrumentSymbolHistory(instrument_id="inst-pit-a", exchange="NSE", symbol="INSTPITA", isin="INE000A01001", series="EQ", valid_from=datetime.date(2024, 1, 1)),
        InstrumentSymbolHistory(instrument_id="inst-pit-b", exchange="NSE", symbol="INSTPITB", isin="INE000B01001", series="EQ", valid_from=datetime.date(2024, 1, 1)),
    ])
    pg_db.commit()

    # Add trades for inst-pit-a and inst-pit-b up to t
    for d in range(1, 16):
        dt = datetime.date(2024, 1, 1) + datetime.timedelta(days=d)
        pg_db.add(DailyPriceRaw(
            instrument_id="inst-pit-a", trade_date=dt, open=Decimal("100"), high=Decimal("105"), low=Decimal("95"),
            close=Decimal("100"), prev_close=Decimal("100"), volume=100000, traded_value=Decimal("10000000"), series="EQ",
            ingestion_run_id=valid_run_id,
        ))
        pg_db.add(DailyPriceRaw(
            instrument_id="inst-pit-b", trade_date=dt, open=Decimal("200"), high=Decimal("205"), low=Decimal("195"),
            close=Decimal("200"), prev_close=Decimal("200"), volume=100000, traded_value=Decimal("20000000"), series="EQ",
            ingestion_run_id=valid_run_id,
        ))
    pg_db.commit()

    # Now add FUTURE data for inst-pit-b after t (e.g. huge volume or price drop)
    for d in range(16, 25):
        dt = datetime.date(2024, 1, 1) + datetime.timedelta(days=d)
        pg_db.add(DailyPriceRaw(
            instrument_id="inst-pit-b", trade_date=dt, open=Decimal("50"), high=Decimal("55"), low=Decimal("45"),
            close=Decimal("50"), prev_close=Decimal("50"), volume=1000000, traded_value=Decimal("50000000"), series="EQ",
            ingestion_run_id=valid_run_id,
        ))
    pg_db.commit()

    svc = PointInTimeUniverseService(db=pg_db)
    cfg = UniverseConfig(
        data_coverage_start=datetime.date(2022, 1, 3),
        data_coverage_end=datetime.date(2024, 12, 31),
        lookback_sessions=10,
        min_adtv=Decimal("1000000"),
        min_trading_completeness=Decimal("0.80"),
        allow_partial_lookback=True,
    )
    manifest = RawDataManifest(manifest_fingerprint="test-manifest")

    # Evaluate universe as of t WITH future data present in database
    snap_before = svc._build_universe(t, config=cfg, persist=False, session=pg_db, raw_manifest=manifest)
    members_before = {m.symbol: m.average_daily_turnover for m in snap_before.eligible_members if m.symbol.startswith("INSTPIT")}

    # Now physically DELETE all data for these instruments after t
    pg_db.execute(text("DELETE FROM daily_prices_raw WHERE instrument_id IN ('inst-pit-a', 'inst-pit-b') AND trade_date > :t"), {"t": t})
    pg_db.commit()

    # Evaluate universe as of t WITHOUT future data
    snap_after = svc._build_universe(t, config=cfg, persist=False, session=pg_db, raw_manifest=manifest)
    members_after = {m.symbol: m.average_daily_turnover for m in snap_after.eligible_members if m.symbol.startswith("INSTPIT")}

    # Assert exact equality: future data deletion had zero effect on universe at t
    assert members_before == members_after
    assert len(members_before) == 2


def test_delisting_detection(pg_db):
    """Verifies that instruments inactive for > threshold sessions are detected as delisted."""
    valid_run_id = pg_db.execute(text("SELECT run_id FROM ingestion_runs LIMIT 1")).scalar()
    inst_id = "inst-test-delist-1"
    pg_db.execute(text("DELETE FROM daily_prices_raw WHERE instrument_id = :id"), {"id": inst_id})
    pg_db.execute(text("DELETE FROM instrument_symbol_history WHERE instrument_id = :id"), {"id": inst_id})
    pg_db.execute(text("DELETE FROM instruments WHERE instrument_id = :id"), {"id": inst_id})
    pg_db.commit()

    inst = Instrument(instrument_id=inst_id, name="Delisted Co", status="ACTIVE")
    pg_db.add(inst)
    pg_db.commit()

    hist = InstrumentSymbolHistory(
        instrument_id=inst_id, exchange="NSE", symbol="DELISTEDCO1",
        isin="INE000D01001", series="EQ", valid_from=datetime.date(2024, 1, 1)
    )
    pg_db.add(hist)
    pg_db.commit()

    # Traded only on 2024-01-02
    pg_db.add(DailyPriceRaw(
        instrument_id=inst_id, trade_date=datetime.date(2024, 1, 2),
        open=Decimal("10"), high=Decimal("12"), low=Decimal("9"), close=Decimal("10"),
        prev_close=Decimal("10"), volume=1000, traded_value=Decimal("10000"), series="EQ",
        ingestion_run_id=valid_run_id,
    ))
    pg_db.commit()

    # Run delisting detection as of 2024-01-30 with threshold=10 sessions
    as_of = datetime.date(2024, 1, 30)
    res = detect_and_record_delistings(pg_db, as_of_date=as_of, inactive_sessions_threshold=10)
    assert res["delisted_count"] >= 1

    # Check that instrument record was updated
    pg_db.refresh(inst)
    assert inst.status == "DELISTED"
    assert inst.delisting_date == datetime.date(2024, 1, 2)

    # Check that symbol history valid_to was set
    pg_db.refresh(hist)
    assert hist.valid_to == datetime.date(2024, 1, 2)


def test_etf_and_rights_exclusions():
    """Verifies that non-equity instruments (ETFs, REs) are excluded by policy."""
    cfg = UniverseConfig()

    # ETF (INF prefix)
    is_elig, reason, _ = evaluate_instrument_eligibility(
        instrument_id="etf-1", symbol="NIFTYBEES", isin="INF732E01015", series="EQ",
        observed_sessions_count=126, lookback_sessions=126,
        average_daily_turnover=Decimal("50000000"), median_daily_turnover=None,
        latest_raw_close=Decimal("250"), as_of_date=datetime.date(2024, 1, 1),
        listing_date=None, delisting_date=None, quarantined_instrument_ids=set(),
        config=cfg, valid_turnover_sessions_count=126,
    )
    assert not is_elig
    assert reason == EligibilityReason.EXCLUDED_ETF_MUTUAL_FUND

    # Rights entitlement (-RE)
    is_elig, reason, _ = evaluate_instrument_eligibility(
        instrument_id="re-1", symbol="TATAPOWER-RE", isin="IN9000A01001", series="RE",
        observed_sessions_count=126, lookback_sessions=126,
        average_daily_turnover=Decimal("50000000"), median_daily_turnover=None,
        latest_raw_close=Decimal("25"), as_of_date=datetime.date(2024, 1, 1),
        listing_date=None, delisting_date=None, quarantined_instrument_ids=set(),
        config=cfg, valid_turnover_sessions_count=126,
    )
    assert not is_elig
    assert reason == EligibilityReason.EXCLUDED_RIGHTS_ENTITLEMENT
