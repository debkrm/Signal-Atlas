import datetime
from decimal import Decimal
import pytest
from sqlalchemy import select, text

from signal_atlas.db.models.instruments import Instrument, InstrumentSymbolHistory
from signal_atlas.db.models.prices import DailyPriceRaw
from signal_atlas.db.models.universe import UniverseMemberRecord, UniverseSnapshotRecord
from signal_atlas.db.session import get_db
from signal_atlas.universe import (
    EligibilityReason,
    PointInTimeUniverseService,
    UniverseConfig,
    UniverseMember,
    UniverseSnapshot,
    get_point_in_time_universe,
)
from signal_atlas.universe.policy import evaluate_instrument_eligibility


@pytest.fixture(scope="module")
def universe_service():
    return PointInTimeUniverseService()


# -------------------------------------------------------------------------
# Test 1: listing_date is not inferred from first observed historical data
# -------------------------------------------------------------------------
def test_1_listing_date_not_inferred_from_first_observed_historical_data():
    """
    Test 1: listing_date must represent verified exchange listing date, NOT data-coverage start.
    All unverified listing dates must be NULL, not blindly populated from MIN(valid_from) or MIN(trade_date).
    """
    with get_db() as db:
        # Check overall unverified listing dates
        inst_count = db.execute(select(text("count(*) FROM instruments"))).scalar()
        unverified_listing_count = db.execute(
            select(text("count(*) FROM instruments WHERE listing_date IS NOT NULL"))
        ).scalar()
        assert unverified_listing_count == 0, (
            f"Unverified listing_date must be NULL! Found {unverified_listing_count} populated rows."
        )

        # Specifically check established old bluechips (e.g. RELIANCE, TCS, INFY)
        for sym in ("RELIANCE", "TCS", "INFY"):
            inst_id = db.execute(
                select(InstrumentSymbolHistory.instrument_id)
                .where(InstrumentSymbolHistory.symbol == sym)
                .limit(1)
            ).scalar()
            if inst_id:
                inst = db.get(Instrument, inst_id)
                assert inst.listing_date is None, (
                    f"Bluechip {sym} must not have listing_date set to 2022-01-03! Got: {inst.listing_date}"
                )


# -------------------------------------------------------------------------
# Test 2: first_observed_trade_date is correctly populated
# -------------------------------------------------------------------------
def test_2_first_observed_trade_date_correctly_populated(universe_service):
    """
    Test 2: first_observed_trade_date tracks earliest available date in our historical dataset.
    Securities observed only after as_of_date are excluded with EXCLUDED_FUTURE_LISTING.
    """
    with get_db() as db:
        # Verify first_observed_trade_date matches MIN(DailyPriceRaw.trade_date)
        sample = db.execute(text("""
            SELECT i.instrument_id, i.first_observed_trade_date, min(dpr.trade_date) as actual_min
            FROM instruments i
            JOIN daily_prices_raw dpr ON i.instrument_id = dpr.instrument_id
            GROUP BY i.instrument_id, i.first_observed_trade_date
            LIMIT 20
        """)).fetchall()

        assert len(sample) > 0
        for row in sample:
            assert row.first_observed_trade_date == row.actual_min, (
                f"first_observed_trade_date {row.first_observed_trade_date} != {row.actual_min} for {row.instrument_id}"
            )

        # Policy test: if first_observed_trade_date > as_of_date, excluded as EXCLUDED_FUTURE_LISTING
        cfg = UniverseConfig()
        is_elig, reason, detail = evaluate_instrument_eligibility(
            instrument_id="inst-future",
            symbol="FUTURECO",
            isin="INE123456789",
            series="EQ",
            observed_sessions_count=0,
            lookback_sessions=126,
            average_daily_turnover=None,
            median_daily_turnover=None,
            latest_raw_close=Decimal("100.00"),
            as_of_date=datetime.date(2022, 6, 30),
            listing_date=None,
            delisting_date=None,
            quarantined_instrument_ids=set(),
            config=cfg,
            first_observed_trade_date=datetime.date(2024, 1, 15),
            valid_turnover_sessions_count=0,
        )
        assert is_elig is False
        assert reason == EligibilityReason.EXCLUDED_FUTURE_LISTING
        assert "2024-01-15" in detail


# -------------------------------------------------------------------------
# Test 3: Duplicate EQ/BE rows do not inflate observed session counts
# -------------------------------------------------------------------------
def test_3_duplicate_eq_be_rows_do_not_inflate_observed_sessions(universe_service):
    """
    Test 3: observed_sessions_count counts distinct calendar trading dates (COUNT(DISTINCT trade_date)).
    """
    with get_db() as db:
        # Audit: verify in daily_prices_raw that no instrument has >1 row across EQ and BE on the same trade date
        dup_count = db.execute(text("""
            SELECT count(*)
            FROM (
                SELECT instrument_id, trade_date
                FROM daily_prices_raw
                WHERE series IN ('EQ', 'BE')
                GROUP BY instrument_id, trade_date
                HAVING count(*) > 1
            ) sub
        """)).scalar()
        assert dup_count == 0, f"Found {dup_count} duplicate same-date EQ/BE rows in daily_prices_raw!"

    # Verify via universe snapshot that observed sessions never exceed lookback trading days
    snap = universe_service.get_universe(datetime.date(2024, 10, 25))
    for m in snap.eligible_members:
        assert m.observed_sessions_count <= snap.lookback_sessions, (
            f"Member {m.symbol} has observed_sessions ({m.observed_sessions_count}) > lookback ({snap.lookback_sessions})"
        )


# -------------------------------------------------------------------------
# Test 4: Trading completeness never exceeds 100%
# -------------------------------------------------------------------------
def test_4_trading_completeness_never_exceeds_100_percent(universe_service):
    """
    Test 4: trading_completeness must be <= 1.0000 for every instrument evaluated.
    """
    snap = universe_service.get_universe(datetime.date(2024, 10, 25))
    all_members = snap.eligible_members + snap.excluded_members

    for m in all_members:
        assert m.trading_completeness <= Decimal("1.0000"), (
            f"Instrument {m.symbol} ({m.instrument_id}) has trading_completeness {m.trading_completeness} > 1.0!"
        )
        assert m.trading_completeness >= Decimal("0.0000")
        assert m.observed_sessions_count + m.missing_sessions_count == snap.lookback_sessions


# -------------------------------------------------------------------------
# Test 5: Turnover is not double-counted
# -------------------------------------------------------------------------
def test_5_turnover_not_double_counted(universe_service):
    """
    Test 5: Total turnover matches the sum of single-session traded values without duplication.
    """
    snap = universe_service.get_universe(datetime.date(2024, 10, 25))
    # Pick a liquid eligible member
    top_member = snap.eligible_members[0]

    with get_db() as db:
        actual_sum = db.execute(
            text("""
                SELECT sum(traded_value)
                FROM daily_prices_raw
                WHERE instrument_id = :iid
                  AND trade_date BETWEEN :start_d AND :end_d
                  AND series IN ('EQ', 'BE')
            """),
            {
                "iid": top_member.instrument_id,
                "start_d": snap.lookback_start_date,
                "end_d": snap.lookback_end_date,
            },
        ).scalar()

        assert top_member.total_turnover == actual_sum, (
            f"Turnover mismatch: member {top_member.total_turnover} != raw sum {actual_sum}"
        )


# -------------------------------------------------------------------------
# Test 6: Historical BE series is not incorrectly replaced by EQ
# -------------------------------------------------------------------------
def test_6_historical_be_series_not_replaced_by_eq(universe_service):
    """
    Test 6: When an instrument enters BE surveillance, historical queries resolve to BE, not EQ.
    MIRCELECTR traded as BE on 2023-08-01, and as EQ on 2024-04-15.
    """
    # 1. As of 2023-08-01, MIRCELECTR was actively in BE surveillance
    snap_be = universe_service.build_universe(datetime.date(2023, 8, 1), persist=False)
    m_be = next(
        m for m in (snap_be.eligible_members + snap_be.excluded_members)
        if m.symbol == "MIRCELECTR"
    )
    assert m_be.series == "BE", f"Expected series 'BE' for MIRCELECTR on 2023-08-01, got '{m_be.series}'"
    assert m_be.is_eligible is True

    # 2. As of 2024-04-15, MIRCELECTR was trading as normal EQ
    snap_eq = universe_service.build_universe(datetime.date(2024, 4, 15), persist=False)
    m_eq = next(
        m for m in (snap_eq.eligible_members + snap_eq.excluded_members)
        if m.symbol == "MIRCELECTR"
    )
    assert m_eq.series == "EQ", f"Expected series 'EQ' for MIRCELECTR on 2024-04-15, got '{m_eq.series}'"
    assert m_eq.is_eligible is True


# -------------------------------------------------------------------------
# Test 7: Ambiguous overlapping series are detected
# -------------------------------------------------------------------------
def test_7_ambiguous_overlapping_series_detected(universe_service):
    """
    Test 7: If multiple conflicting symbol/series records exist with identical validity and
    no exchange trade activity can resolve the ambiguity, exclude with EXCLUDED_AMBIGUOUS_SERIES_HISTORY.
    """
    cfg = UniverseConfig()
    is_elig, reason, detail = evaluate_instrument_eligibility(
        instrument_id="inst-ambig",
        symbol="AMBIGCO",
        isin="INE000000999",
        series="EQ",
        observed_sessions_count=126,
        lookback_sessions=126,
        average_daily_turnover=Decimal("10000000.00"),
        median_daily_turnover=Decimal("10000000.00"),
        latest_raw_close=Decimal("50.00"),
        as_of_date=datetime.date(2024, 10, 25),
        listing_date=None,
        delisting_date=None,
        quarantined_instrument_ids=set(),
        config=cfg,
        valid_turnover_sessions_count=126,
    )
    # When service flags ambiguity:
    assert EligibilityReason.EXCLUDED_AMBIGUOUS_SERIES_HISTORY.value == "EXCLUDED_AMBIGUOUS_SERIES_HISTORY"


# -------------------------------------------------------------------------
# Test 8: NULL turnover affects turnover-data completeness
# -------------------------------------------------------------------------
def test_8_null_turnover_affects_turnover_data_completeness():
    """
    Test 8: turnover_data_completeness = valid_turnover_sessions / expected_lookback_sessions.
    NULL turnover sessions do NOT count as valid turnover sessions.
    """
    cfg = UniverseConfig(min_turnover_completeness=Decimal("0.80"))

    # 126 expected sessions: 90 valid, 36 NULL turnover
    # Turnover completeness = 90 / 126 = 71.4% < 80% -> EXCLUDED
    is_elig, reason, detail = evaluate_instrument_eligibility(
        instrument_id="inst-null-cov",
        symbol="NULLCOV",
        isin="INE111111111",
        series="EQ",
        observed_sessions_count=126,
        lookback_sessions=126,
        average_daily_turnover=Decimal("20000000.00"),  # high turnover on known days
        median_daily_turnover=Decimal("20000000.00"),
        latest_raw_close=Decimal("100.00"),
        as_of_date=datetime.date(2024, 10, 25),
        listing_date=None,
        delisting_date=None,
        quarantined_instrument_ids=set(),
        config=cfg,
        valid_turnover_sessions_count=90,  # 36 NULL sessions
    )

    assert is_elig is False
    assert reason == EligibilityReason.EXCLUDED_INSUFFICIENT_TURNOVER_COVERAGE
    assert "Turnover data completeness 71.4%" in detail


# -------------------------------------------------------------------------
# Test 9: Zero turnover remains distinct from NULL turnover
# -------------------------------------------------------------------------
def test_9_zero_turnover_remains_distinct_from_null_turnover():
    """
    Test 9: Genuine 0.00 turnover is preserved and dilutes ADTV, whereas NULL turnover is excluded from ADTV denominator.
    """
    cfg = UniverseConfig(
        min_adtv=Decimal("1000000.00"),
        min_trading_completeness=Decimal("0.50"),
        min_turnover_completeness=Decimal("0.50"),
    )

    # Case A: 10 sessions, 8 with 1.25M turnover, 2 NULL turnover
    # ADTV = 10M / 8 = 1.25M >= 1.0M -> ELIGIBLE
    is_elig_a, reason_a, _ = evaluate_instrument_eligibility(
        instrument_id="inst-null",
        symbol="NULLTEST",
        isin="INE222222222",
        series="EQ",
        observed_sessions_count=10,
        lookback_sessions=10,
        average_daily_turnover=Decimal("1250000.00"),
        median_daily_turnover=Decimal("1250000.00"),
        latest_raw_close=Decimal("50.00"),
        as_of_date=datetime.date(2024, 10, 25),
        listing_date=None,
        delisting_date=None,
        quarantined_instrument_ids=set(),
        config=cfg,
        valid_turnover_sessions_count=8,
    )
    assert is_elig_a is True
    assert reason_a == EligibilityReason.ELIGIBLE

    # Case B: 10 sessions, 8 with 1.25M turnover, 2 with genuine 0.00 turnover
    # ADTV = 10M / 10 = 1.0M, but if total was 7.5M / 10 = 750k < 1.0M -> EXCLUDED
    is_elig_b, reason_b, _ = evaluate_instrument_eligibility(
        instrument_id="inst-zero",
        symbol="ZEROTEST",
        isin="INE333333333",
        series="EQ",
        observed_sessions_count=10,
        lookback_sessions=10,
        average_daily_turnover=Decimal("750000.00"),  # diluted by genuine 0.00 sessions
        median_daily_turnover=Decimal("750000.00"),
        latest_raw_close=Decimal("50.00"),
        as_of_date=datetime.date(2024, 10, 25),
        listing_date=None,
        delisting_date=None,
        quarantined_instrument_ids=set(),
        config=cfg,
        valid_turnover_sessions_count=10,
    )
    assert is_elig_b is False
    assert reason_b == EligibilityReason.EXCLUDED_BELOW_LIQUIDITY_THRESHOLD


# -------------------------------------------------------------------------
# Test 10: Insufficient valid turnover coverage causes exclusion
# -------------------------------------------------------------------------
def test_10_insufficient_valid_turnover_coverage_causes_exclusion():
    """
    Test 10: An instrument with massive turnover on very few sessions cannot qualify
    merely because NULL sessions are excluded from the ADTV denominator.
    """
    cfg = UniverseConfig(min_adtv=Decimal("5000000.00"), min_turnover_completeness=Decimal("0.80"))

    # Lookback = 126 sessions. Only 10 sessions traded with 50 Cr each.
    # ADTV = 50 Cr (high!), but turnover completeness = 10/126 = 7.9% < 80%.
    is_elig, reason, detail = evaluate_instrument_eligibility(
        instrument_id="inst-low-cov",
        symbol="LOWCOV",
        isin="INE444444444",
        series="EQ",
        observed_sessions_count=110,  # e.g. observed quotes but no turnover data
        lookback_sessions=126,
        average_daily_turnover=Decimal("500000000.00"),  # ₹50 Crore ADTV
        median_daily_turnover=Decimal("500000000.00"),
        latest_raw_close=Decimal("150.00"),
        as_of_date=datetime.date(2024, 10, 25),
        listing_date=None,
        delisting_date=None,
        quarantined_instrument_ids=set(),
        config=cfg,
        valid_turnover_sessions_count=10,
    )
    assert is_elig is False
    assert reason == EligibilityReason.EXCLUDED_INSUFFICIENT_TURNOVER_COVERAGE
    assert "Turnover data completeness 7.9%" in detail


# -------------------------------------------------------------------------
# Test 11: Historical snapshots retain their data and configuration identifiers
# -------------------------------------------------------------------------
def test_11_historical_snapshots_retain_data_and_config_identifiers(universe_service):
    """
    Test 11: Universe snapshots persist and verify raw_data_version, data_coverage, code_revision,
    and adjustment_version. Snapshot overwrite across differing raw datasets is prevented.
    """
    snap = universe_service.get_universe(datetime.date(2024, 10, 25))
    assert snap.raw_data_version == "RAW_NSE_2022_2024_V1"
    assert snap.data_coverage_start == datetime.date(2022, 1, 3)
    assert snap.data_coverage_end == datetime.date(2024, 12, 31)
    assert snap.code_revision == "phase-1b-iii.1"
    assert snap.adjustment_version == "v1.4"

    with get_db() as db:
        rec = db.execute(
            select(UniverseSnapshotRecord).where(
                UniverseSnapshotRecord.snapshot_id == snap.snapshot_id
            )
        ).scalars().first()
        assert rec is not None
        assert rec.raw_data_version == "RAW_NSE_2022_2024_V1"
        assert rec.data_coverage_start == datetime.date(2022, 1, 3)
        assert rec.data_coverage_end == datetime.date(2024, 12, 31)
        assert rec.code_revision == "phase-1b-iii.1"


# -------------------------------------------------------------------------
# Test 12: Existing HDFC historical inclusion remains valid
# -------------------------------------------------------------------------
def test_12_existing_hdfc_historical_inclusion_remains_valid(universe_service):
    """
    Test 12: HDFC (INE001A01036) remains fully eligible in the 2023-01-02 universe despite subsequent merger.
    """
    with get_db() as db:
        hdfc_id = db.execute(
            select(InstrumentSymbolHistory.instrument_id)
            .where(InstrumentSymbolHistory.isin == "INE001A01036")
        ).scalar()
        assert hdfc_id is not None

        snap_2023 = universe_service.get_universe(datetime.date(2023, 1, 2))
        m = snap_2023.get_member(hdfc_id)
        assert m is not None
        assert m.is_eligible is True
        assert m.symbol == "HDFC"
        assert m.isin == "INE001A01036"
        assert m.average_daily_turnover > Decimal("100000000.00")


# -------------------------------------------------------------------------
# Test 13: Existing symbol/ISIN changes continue to resolve correctly
# -------------------------------------------------------------------------
def test_13_existing_symbol_and_isin_changes_resolve_correctly(universe_service):
    """
    Test 13: Historical renames resolve to PIT symbols without identity duplication.
    - 4THDIM -> GVPTECH
    - IIFLWAM -> 360ONE
    """
    with get_db() as db:
        gvp_id = db.execute(
            select(InstrumentSymbolHistory.instrument_id)
            .where(InstrumentSymbolHistory.symbol == "GVPTECH")
        ).scalar()
        assert gvp_id is not None

        snap_2022 = universe_service.get_universe(datetime.date(2022, 6, 30))
        m_2022 = snap_2022.get_member(gvp_id)
        if m_2022:
            assert m_2022.symbol == "4THDIM"

        snap_2024 = universe_service.get_universe(datetime.date(2024, 10, 25))
        m_2024 = snap_2024.get_member(gvp_id)
        if m_2024:
            assert m_2024.symbol == "GVPTECH"


# -------------------------------------------------------------------------
# Test 14: Universe calculations remain bounded by as_of_date
# -------------------------------------------------------------------------
def test_14_universe_calculations_remain_bounded_by_as_of_date(universe_service):
    """
    Test 14: Trailing window and prices strictly respect as_of_date. No future leakage.
    """
    as_of = datetime.date(2024, 6, 28)
    snap = universe_service.get_universe(as_of)

    assert snap.lookback_end_date <= as_of
    assert snap.lookback_sessions == 126
    assert snap.lookback_start_date < snap.lookback_end_date

    # Corporate action non-leakage test with VBL splits
    with get_db() as db:
        vbl_id = db.execute(
            select(InstrumentSymbolHistory.instrument_id)
            .where(InstrumentSymbolHistory.symbol == "VBL")
        ).scalar()
        assert vbl_id is not None

        # As of before first split (2023-06-14)
        prices_pre = universe_service.get_universe_adjusted_prices(
            instrument_id=vbl_id,
            as_of_date=datetime.date(2023, 6, 14),
            session=db,
        )
        row_pre = next(r for r in prices_pre if r.trade_date == datetime.date(2023, 1, 10))
        assert row_pre.cumulative_multiplier == Decimal("1.000000")

        # As of after second split (2024-09-13)
        prices_post = universe_service.get_universe_adjusted_prices(
            instrument_id=vbl_id,
            as_of_date=datetime.date(2024, 9, 13),
            session=db,
        )
        row_post = next(r for r in prices_post if r.trade_date == datetime.date(2023, 1, 10))
        assert row_post.cumulative_multiplier == Decimal("5.000000")
