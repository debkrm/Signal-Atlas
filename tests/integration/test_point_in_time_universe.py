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


@pytest.fixture(autouse=True)
def require_historical_dataset_for_bulk_tests(request):
    """
    In CI environments without the 2GB uncommitted bulk historical dataset,
    tests inspecting pre-existing historical market symbols are skipped.
    Behavioral tests with inserted fixture rows run and verify functionality.
    """
    historical_tests = {
        "test_1_listing_date_not_inferred_from_first_observed_historical_data",
        "test_2_first_observed_trade_date_correctly_populated",
        "test_4_trading_completeness_never_exceeds_100_percent",
        "test_5_turnover_not_double_counted",
        "test_6_historical_be_series_not_replaced_by_eq",
        "test_11_historical_snapshots_retain_data_and_config_identifiers",
        "test_12_existing_hdfc_historical_inclusion_remains_valid",
        "test_13_existing_symbol_and_isin_changes_resolve_correctly",
        "test_14_universe_calculations_remain_bounded_by_as_of_date",
    }
    if request.node.name in historical_tests:
        with get_db() as db:
            inst_count = db.execute(select(text("count(*) FROM instruments"))).scalar()
            if inst_count is None or inst_count < 500:
                pytest.skip("Bulk historical NSE dataset not present in test database")


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
    Test 3: Behavioral test inserting simulated same-date EQ and BE rows for an instrument.
    observed_sessions_count must strictly count distinct calendar trading dates (COUNT(DISTINCT trade_date))
    and never inflate session counts.
    """
    test_id = "inst-test-dup-session"
    trade_dt = datetime.date(2024, 10, 24)

    with get_db() as db:
        # Clean any prior leftover
        db.execute(text("DELETE FROM daily_prices_raw WHERE instrument_id = :id"), {"id": test_id})
        db.execute(text("DELETE FROM instrument_symbol_history WHERE instrument_id = :id"), {"id": test_id})
        db.execute(text("DELETE FROM instruments WHERE instrument_id = :id"), {"id": test_id})
        db.commit()

        run_id = db.execute(text("SELECT run_id FROM ingestion_runs LIMIT 1")).scalar()
        if not run_id:
            run_id = "test-fixture-run-001"
            db.execute(text("""
                INSERT INTO ingestion_runs (run_id, source, trade_date, file_name, file_hash, parser_version, status, row_count)
                VALUES (:rid, 'NSE', '2022-01-03', 'fixture.zip', 'hash123', 'v1', 'SUCCESS', 0)
                ON CONFLICT (run_id) DO NOTHING
            """), {"rid": run_id})
            db.commit()
        inst = Instrument(
            instrument_id=test_id,
            name="Duplicate Test Corp",
            status="ACTIVE",
            first_observed_trade_date=datetime.date(2022, 1, 3),
        )
        db.add(inst)
        sym_rec = InstrumentSymbolHistory(
            instrument_id=test_id,
            symbol="DUPTEST",
            isin="INE999DUP001",
            series="EQ",
            valid_from=datetime.date(2022, 1, 3),
            valid_to=None,
        )
        db.add(sym_rec)

        # Insert TWO price rows on the exact same date: one EQ, one BE
        p_eq = DailyPriceRaw(
            instrument_id=test_id,
            trade_date=trade_dt,
            series="EQ",
            open=Decimal("100.00"),
            high=Decimal("105.00"),
            low=Decimal("95.00"),
            close=Decimal("102.00"),
            last=Decimal("102.00"),
            prev_close=Decimal("100.00"),
            volume=50000,
            traded_value=Decimal("5100000.00"),
            trades_count=500,
            ingestion_run_id=run_id,
        )
        p_be = DailyPriceRaw(
            instrument_id=test_id,
            trade_date=trade_dt,
            series="BE",
            open=Decimal("100.00"),
            high=Decimal("105.00"),
            low=Decimal("95.00"),
            close=Decimal("102.00"),
            last=Decimal("102.00"),
            prev_close=Decimal("100.00"),
            volume=20000,
            traded_value=Decimal("2040000.00"),
            trades_count=200,
            ingestion_run_id=run_id,
        )
        db.add_all([p_eq, p_be])
        db.commit()

    try:
        snap = universe_service.build_universe(datetime.date(2024, 10, 25), persist=False)
        m = snap.get_member(test_id)
        assert m is not None, "Test member not evaluated in universe snapshot!"
        # Distinct trade date counting must yield exactly 1 session, NOT 2
        assert m.observed_sessions_count == 1, (
            f"Expected observed_sessions_count=1 for single date with duplicate EQ/BE rows, got {m.observed_sessions_count}"
        )
        # Combined turnover on that date is accurately aggregated
        assert m.total_turnover == Decimal("7140000.00")
    finally:
        with get_db() as db:
            db.execute(text("DELETE FROM daily_prices_raw WHERE instrument_id = :id"), {"id": test_id})
            db.execute(text("DELETE FROM instrument_symbol_history WHERE instrument_id = :id"), {"id": test_id})
            db.execute(text("DELETE FROM instruments WHERE instrument_id = :id"), {"id": test_id})
            db.commit()


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
# Test 7: Ambiguous overlapping series are detected and excluded by service
# -------------------------------------------------------------------------
def test_7_ambiguous_overlapping_series_detected(universe_service):
    """
    Test 7: Behavioral test with inserted conflicting records having identical validity boundaries.
    When multiple conflicting symbol/series records exist with identical validity and
    no contemporaneous trade evidence resolves the conflict, build_universe() must identify
    the ambiguity and exclude the instrument with EXCLUDED_AMBIGUOUS_SERIES_HISTORY.
    """
    test_id = "inst-test-ambig-series"

    with get_db() as db:
        # Clean any prior leftover
        db.execute(text("DELETE FROM daily_prices_raw WHERE instrument_id = :id"), {"id": test_id})
        db.execute(text("DELETE FROM instrument_symbol_history WHERE instrument_id = :id"), {"id": test_id})
        db.execute(text("DELETE FROM instruments WHERE instrument_id = :id"), {"id": test_id})
        db.commit()

        inst = Instrument(
            instrument_id=test_id,
            name="Ambiguous Series Corp",
            status="ACTIVE",
            first_observed_trade_date=datetime.date(2022, 1, 3),
        )
        db.add(inst)

        # Insert TWO conflicting series records with IDENTICAL valid_from and valid_to
        # Neither has trading evidence that can disambiguate
        rec_eq = InstrumentSymbolHistory(
            instrument_id=test_id,
            symbol="AMBIGCO",
            isin="INE000000999",
            series="EQ",
            valid_from=datetime.date(2024, 1, 1),
            valid_to=None,
        )
        rec_be = InstrumentSymbolHistory(
            instrument_id=test_id,
            symbol="AMBIGCO",
            isin="INE000000999",
            series="BE",
            valid_from=datetime.date(2024, 1, 1),
            valid_to=None,
        )
        db.add_all([rec_eq, rec_be])
        db.commit()

    try:
        snap = universe_service.build_universe(datetime.date(2024, 10, 25), persist=False)
        m = snap.get_member(test_id)
        assert m is not None, "Ambiguous instrument was not evaluated!"
        assert m.is_eligible is False, "Ambiguous instrument must be excluded from universe!"
        assert m.exclusion_reason == EligibilityReason.EXCLUDED_AMBIGUOUS_SERIES_HISTORY
        assert "Multiple conflicting series records" in m.exclusion_detail
    finally:
        with get_db() as db:
            db.execute(text("DELETE FROM daily_prices_raw WHERE instrument_id = :id"), {"id": test_id})
            db.execute(text("DELETE FROM instrument_symbol_history WHERE instrument_id = :id"), {"id": test_id})
            db.execute(text("DELETE FROM instruments WHERE instrument_id = :id"), {"id": test_id})
            db.commit()


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
    from signal_atlas.universe.provenance import get_code_revision

    snap = universe_service.get_universe(datetime.date(2024, 10, 25))
    assert snap.raw_data_version.startswith("RAW-MANIFEST-") or snap.raw_data_version == "RAW_NSE_2022_2024_V1"
    assert snap.data_coverage_start == datetime.date(2022, 1, 3)
    assert snap.data_coverage_end == datetime.date(2024, 12, 31)
    assert snap.code_revision == get_code_revision()
    assert snap.adjustment_version == "v1.4"
    if snap.raw_data_manifest_hash:
        assert len(snap.raw_data_manifest_hash) == 64

    with get_db() as db:
        rec = db.execute(
            select(UniverseSnapshotRecord).where(
                UniverseSnapshotRecord.snapshot_id == snap.snapshot_id
            )
        ).scalars().first()
        assert rec is not None
        assert rec.raw_data_version == snap.raw_data_version
        assert rec.data_coverage_start == datetime.date(2022, 1, 3)
        assert rec.data_coverage_end == datetime.date(2024, 12, 31)
        assert rec.code_revision == snap.code_revision
        if rec.raw_data_manifest_hash:
            assert rec.raw_data_manifest_hash == snap.raw_data_manifest_hash


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

        snap_2022 = universe_service.get_universe(datetime.date(2022, 12, 30))
        m_2022 = snap_2022.get_member(gvp_id)
        assert m_2022 is not None
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


# -------------------------------------------------------------------------
# Test 15: Canonical configuration fingerprinting and lossless Decimal identity
# -------------------------------------------------------------------------
def test_15_config_fingerprint_uniqueness_and_lossless_decimals():
    """
    Test 15: Config fingerprint incorporates every calculation parameter without lossy integer conversion.
    Changes to max_price, min_median_turnover, raw_data_version, code_revision, or min_price
    must produce distinct stable SHA-256 fingerprints and configuration identifiers.
    """
    base_cfg = UniverseConfig()

    # 1. max_price inclusion
    cfg_max_price = UniverseConfig(max_price=Decimal("500.00"))
    assert base_cfg.config_hash != cfg_max_price.config_hash
    assert base_cfg.config_identifier != cfg_max_price.config_identifier

    # 2. min_median_turnover inclusion
    cfg_med = UniverseConfig(min_median_turnover=Decimal("10000000.00"))
    assert base_cfg.config_hash != cfg_med.config_hash
    assert base_cfg.config_identifier != cfg_med.config_identifier

    # 3. Lossless Decimal precision (min_price 10.00 vs 10.50 vs 10.01)
    cfg_p1 = UniverseConfig(min_price=Decimal("10.00"))
    cfg_p2 = UniverseConfig(min_price=Decimal("10.50"))
    cfg_p3 = UniverseConfig(min_price=Decimal("10.01"))
    assert cfg_p1.config_hash != cfg_p2.config_hash
    assert cfg_p1.config_hash != cfg_p3.config_hash

    # 4. Provenance and code/data revisions
    cfg_raw_v2 = UniverseConfig(raw_data_version="RAW_NSE_2022_2024_V2")
    assert base_cfg.config_hash != cfg_raw_v2.config_hash

    cfg_rev2 = UniverseConfig(code_revision="phase-1b-iii.2")
    assert base_cfg.config_hash != cfg_rev2.config_hash

    # 5. Deterministic reproducibility
    cfg_copy = UniverseConfig()
    assert base_cfg.config_hash == cfg_copy.config_hash
    assert base_cfg.canonical_json() == cfg_copy.canonical_json()


# -------------------------------------------------------------------------
# Test 16: Immutable snapshot coexistence across distinct configurations
# -------------------------------------------------------------------------
def test_16_immutable_snapshots_coexist_without_deletion(universe_service):
    """
    Test 16: Distinct configurations and revisions coexist as separate immutable snapshots
    without overwriting or deleting prior snapshots.
    """
    test_dt = datetime.date(2024, 10, 25)
    cfg1 = UniverseConfig(top_n=50)
    cfg2 = UniverseConfig(top_n=100)

    snap1 = universe_service.build_universe(test_dt, config=cfg1, persist=True)
    snap2 = universe_service.build_universe(test_dt, config=cfg2, persist=True)

    assert snap1.config_identifier != snap2.config_identifier
    assert snap1.snapshot_id != snap2.snapshot_id

    with get_db() as db:
        rec1 = db.get(UniverseSnapshotRecord, snap1.snapshot_id)
        rec2 = db.get(UniverseSnapshotRecord, snap2.snapshot_id)

        assert rec1 is not None, "Snapshot 1 must still exist!"
        assert rec2 is not None, "Snapshot 2 must coexist!"
        assert rec1.config_identifier == snap1.config_identifier
        assert rec2.config_identifier == snap2.config_identifier
        if rec1.eligible_count > 0:
            assert rec1.eligible_count == 50
            assert rec2.eligible_count == 100

        # Retrieve idempotently via get_universe
        retrieved1 = universe_service.get_universe(test_dt, config=cfg1)
        retrieved2 = universe_service.get_universe(test_dt, config=cfg2)

        assert retrieved1.snapshot_id == snap1.snapshot_id
        assert retrieved2.snapshot_id == snap2.snapshot_id


# -------------------------------------------------------------------------
# Test 17: Full lookback completeness enforcement
# -------------------------------------------------------------------------
def test_17_full_lookback_completeness_enforced(universe_service):
    """
    Test 17: The universe builder strictly requires cfg.lookback_sessions (126) completed trading sessions.
    Requesting a universe when fewer sessions exist must raise ValueError explaining the counts,
    rather than silently reducing the denominator.
    Partial lookback requires explicit opt-in via allow_partial_lookback=True.
    """
    # 2022-01-10 is the 6th trading session in the historical dataset (starts 2022-01-03)
    early_dt = datetime.date(2022, 1, 10)

    # 1. Standard config must reject incomplete history
    with pytest.raises(ValueError, match="Insufficient completed trading sessions|Incomplete lookback window"):
        universe_service.build_universe(early_dt, config=UniverseConfig(), persist=False)

    # 2. Explicit opt-in supports documented partial lookback
    partial_cfg = UniverseConfig(allow_partial_lookback=True)
    partial_snap = universe_service.build_universe(early_dt, config=partial_cfg, persist=False)
    assert partial_snap.lookback_sessions == 6
    assert partial_snap.as_of_date == early_dt
    assert partial_snap.config_identifier == partial_snap.config.config_identifier


# -------------------------------------------------------------------------
# Test 18: Date coverage and trading calendar boundary validation
# -------------------------------------------------------------------------
def test_18_date_coverage_and_future_date_rejection(universe_service):
    """
    Test 18: Validates that as_of_date is not beyond data coverage end, before data coverage start,
    or beyond the trading calendar. Past historical sessions are never silently substituted for future dates.
    """
    # Future date beyond 2024-12-31
    future_dt = datetime.date(2025, 6, 1)
    with pytest.raises(ValueError, match="exceeds data coverage boundary"):
        universe_service.build_universe(future_dt, persist=False)

    # Date prior to 2022-01-03
    past_dt = datetime.date(2021, 12, 1)
    with pytest.raises(ValueError, match="prior to data coverage start"):
        universe_service.build_universe(past_dt, persist=False)


# -------------------------------------------------------------------------
# Test 19: PIT series transition boundary handling without stale evidence
# -------------------------------------------------------------------------
# Test 19: PIT series transition boundary handling without stale evidence
# -------------------------------------------------------------------------
def test_19_pit_series_transition_boundary_handling(universe_service):
    """
    Test 19: Comprehensive behavioral tests for Point-in-Time series resolution at transition boundaries:
    1. EQ -> BE transition:
       - No trade on effective date (stale EQ trade rejected, fallback to valid_from).
       - Contemporaneous trade in BE on effective date (uses BE trade evidence).
    2. BE -> EQ transition:
       - No trade on effective date (stale BE trade rejected, fallback to valid_from).
       - Contemporaneous trade in EQ on effective date (uses EQ trade evidence).
    3. Stale old-series trade after transition (old-series trade cannot override new series).
    4. Unresolved overlapping series records (flagged as ambiguous and excluded).
    """
    eq_be_id = "inst-test-trans-eq-be"
    be_eq_id = "inst-test-trans-be-eq"
    ambig_id = "inst-test-trans-ambig"
    all_ids = [eq_be_id, be_eq_id, ambig_id]

    with get_db() as db:
        # Cleanup any previous runs
        for tid in all_ids:
            db.execute(text("DELETE FROM daily_prices_raw WHERE instrument_id = :id"), {"id": tid})
            db.execute(text("DELETE FROM instrument_symbol_history WHERE instrument_id = :id"), {"id": tid})
            db.execute(text("DELETE FROM instruments WHERE instrument_id = :id"), {"id": tid})
        db.commit()

        run_id = db.execute(text("SELECT run_id FROM ingestion_runs LIMIT 1")).scalar()
        if not run_id:
            run_id = "test-fixture-run-001"
            db.execute(text("""
                INSERT INTO ingestion_runs (run_id, source, trade_date, file_name, file_hash, parser_version, status, row_count)
                VALUES (:rid, 'NSE', '2022-01-03', 'fixture.zip', 'hash123', 'v1', 'SUCCESS', 0)
                ON CONFLICT (run_id) DO NOTHING
            """), {"rid": run_id})
            db.commit()

        # 1. EQ -> BE Instrument
        db.add(Instrument(
            instrument_id=eq_be_id,
            name="EQ to BE Transition Corp",
            status="ACTIVE",
            first_observed_trade_date=datetime.date(2022, 1, 3),
        ))
        db.add_all([
            InstrumentSymbolHistory(
                instrument_id=eq_be_id,
                symbol="TRANS_EQBE",
                isin="INE999EQBE01",
                series="EQ",
                valid_from=datetime.date(2022, 1, 3),
                valid_to=datetime.date(2024, 7, 21),
            ),
            InstrumentSymbolHistory(
                instrument_id=eq_be_id,
                symbol="TRANS_EQBE",
                isin="INE999EQBE01",
                series="BE",
                valid_from=datetime.date(2024, 7, 21),
                valid_to=None,
            ),
        ])

        # Trade in EQ on 2024-07-19 (prior to 2024-07-21 transition)
        db.add(DailyPriceRaw(
            instrument_id=eq_be_id,
            trade_date=datetime.date(2024, 7, 19),
            series="EQ",
            open=Decimal("100.00"),
            high=Decimal("105.00"),
            low=Decimal("95.00"),
            close=Decimal("102.00"),
            last=Decimal("102.00"),
            prev_close=Decimal("100.00"),
            volume=50000,
            traded_value=Decimal("5100000.00"),
            trades_count=500,
            ingestion_run_id=run_id,
        ))

        # 2. BE -> EQ Instrument
        db.add(Instrument(
            instrument_id=be_eq_id,
            name="BE to EQ Transition Corp",
            status="ACTIVE",
            first_observed_trade_date=datetime.date(2022, 1, 3),
        ))
        db.add_all([
            InstrumentSymbolHistory(
                instrument_id=be_eq_id,
                symbol="TRANS_BEEQ",
                isin="INE999BEEQ01",
                series="BE",
                valid_from=datetime.date(2022, 1, 3),
                valid_to=datetime.date(2024, 8, 15),
            ),
            InstrumentSymbolHistory(
                instrument_id=be_eq_id,
                symbol="TRANS_BEEQ",
                isin="INE999BEEQ01",
                series="EQ",
                valid_from=datetime.date(2024, 8, 15),
                valid_to=None,
            ),
        ])

        # Trade in BE on 2024-08-14 (prior to 2024-08-15 transition)
        db.add(DailyPriceRaw(
            instrument_id=be_eq_id,
            trade_date=datetime.date(2024, 8, 14),
            series="BE",
            open=Decimal("200.00"),
            high=Decimal("205.00"),
            low=Decimal("195.00"),
            close=Decimal("202.00"),
            last=Decimal("202.00"),
            prev_close=Decimal("200.00"),
            volume=40000,
            traded_value=Decimal("8080000.00"),
            trades_count=400,
            ingestion_run_id=run_id,
        ))

        # 3. Ambiguous Overlapping Instrument (Conflicting EQ and BE valid from same date with no trades)
        db.add(Instrument(
            instrument_id=ambig_id,
            name="Ambiguous Series Corp",
            status="ACTIVE",
            first_observed_trade_date=datetime.date(2022, 1, 3),
        ))
        db.add_all([
            InstrumentSymbolHistory(
                instrument_id=ambig_id,
                symbol="TRANS_AMBIG",
                isin="INE999AMBIG1",
                series="EQ",
                valid_from=datetime.date(2024, 7, 1),
                valid_to=None,
            ),
            InstrumentSymbolHistory(
                instrument_id=ambig_id,
                symbol="TRANS_AMBIG",
                isin="INE999AMBIG1",
                series="BE",
                valid_from=datetime.date(2024, 7, 1),
                valid_to=None,
            ),
        ])

        db.commit()

    try:
        # Scenario 1A: EQ -> BE without trade on effective date (2024-07-22)
        # Stale EQ trade from July 19 must NOT override the BE interval effective July 21
        snap_1a = universe_service.build_universe(datetime.date(2024, 7, 22), persist=False)
        m_1a = snap_1a.get_member(eq_be_id)
        assert m_1a is not None
        assert m_1a.series == "BE", f"EQ->BE without trade: expected 'BE', got '{m_1a.series}'"

        # Scenario 1B: EQ -> BE with contemporaneous trade in BE on effective date
        with get_db() as db:
            db.add(DailyPriceRaw(
                instrument_id=eq_be_id,
                trade_date=datetime.date(2024, 7, 22),
                series="BE",
                open=Decimal("102.00"),
                high=Decimal("103.00"),
                low=Decimal("101.00"),
                close=Decimal("102.50"),
                last=Decimal("102.50"),
                prev_close=Decimal("102.00"),
                volume=30000,
                traded_value=Decimal("3075000.00"),
                trades_count=300,
                ingestion_run_id=run_id,
            ))
            db.commit()

        snap_1b = universe_service.build_universe(datetime.date(2024, 7, 22), persist=False)
        m_1b = snap_1b.get_member(eq_be_id)
        assert m_1b is not None
        assert m_1b.series == "BE", f"EQ->BE with BE trade: expected 'BE', got '{m_1b.series}'"

        # Scenario 2A: BE -> EQ without trade on effective date (2024-08-16)
        # Stale BE trade from August 14 must NOT override EQ interval effective August 15
        snap_2a = universe_service.build_universe(datetime.date(2024, 8, 16), persist=False)
        m_2a = snap_2a.get_member(be_eq_id)
        assert m_2a is not None
        assert m_2a.series == "EQ", f"BE->EQ without trade: expected 'EQ', got '{m_2a.series}'"

        # Scenario 2B: BE -> EQ with contemporaneous trade in EQ on effective date
        with get_db() as db:
            db.add(DailyPriceRaw(
                instrument_id=be_eq_id,
                trade_date=datetime.date(2024, 8, 16),
                series="EQ",
                open=Decimal("203.00"),
                high=Decimal("206.00"),
                low=Decimal("201.00"),
                close=Decimal("204.00"),
                last=Decimal("204.00"),
                prev_close=Decimal("202.00"),
                volume=35000,
                traded_value=Decimal("7140000.00"),
                trades_count=350,
                ingestion_run_id=run_id,
            ))
            db.commit()

        snap_2b = universe_service.build_universe(datetime.date(2024, 8, 16), persist=False)
        m_2b = snap_2b.get_member(be_eq_id)
        assert m_2b is not None
        assert m_2b.series == "EQ", f"BE->EQ with EQ trade: expected 'EQ', got '{m_2b.series}'"

        # Scenario 3: Unresolved overlapping records (ambiguous history)
        # Must be excluded with EXCLUDED_AMBIGUOUS_SERIES_HISTORY
        snap_3 = universe_service.build_universe(datetime.date(2024, 7, 22), persist=False)
        m_3 = snap_3.get_member(ambig_id)
        assert m_3 is not None
        assert m_3.is_eligible is False
        assert m_3.exclusion_reason == EligibilityReason.EXCLUDED_AMBIGUOUS_SERIES_HISTORY

    finally:
        with get_db() as db:
            for tid in all_ids:
                db.execute(text("DELETE FROM daily_prices_raw WHERE instrument_id = :id"), {"id": tid})
                db.execute(text("DELETE FROM instrument_symbol_history WHERE instrument_id = :id"), {"id": tid})
                db.execute(text("DELETE FROM instruments WHERE instrument_id = :id"), {"id": tid})
            db.commit()


# -------------------------------------------------------------------------
# Test 20: Deterministic ranking tie-break (ADTV descending, symbol ascending)
# -------------------------------------------------------------------------
def test_20_deterministic_ranking_tie_break(universe_service):
    """
    Test 20: Verifies deterministic ranking order:
    1. Primary sort: ADTV descending.
    2. Secondary tie-break: Symbol ascending (A-Z) for instruments with equal ADTV.
    """
    rank_test_ids = [
        ("inst-rank-a", "ZETA", Decimal("888000000000.00")),
        ("inst-rank-b", "DELTA", Decimal("999000000000.00")),
        ("inst-rank-c", "ALPHA", Decimal("888000000000.00")),
        ("inst-rank-d", "BETA", Decimal("888000000000.00")),
    ]

    as_of = datetime.date(2024, 7, 22)

    with get_db() as db:
        for tid, sym, _ in rank_test_ids:
            db.execute(text("DELETE FROM daily_prices_raw WHERE instrument_id = :id"), {"id": tid})
            db.execute(text("DELETE FROM instrument_symbol_history WHERE instrument_id = :id"), {"id": tid})
            db.execute(text("DELETE FROM instruments WHERE instrument_id = :id"), {"id": tid})
        db.commit()

        run_id = db.execute(text("SELECT run_id FROM ingestion_runs LIMIT 1")).scalar()
        if not run_id:
            run_id = "test-fixture-run-001"
            db.execute(text("""
                INSERT INTO ingestion_runs (run_id, source, trade_date, file_name, file_hash, parser_version, status, row_count)
                VALUES (:rid, 'NSE', '2022-01-03', 'fixture.zip', 'hash123', 'v1', 'SUCCESS', 0)
                ON CONFLICT (run_id) DO NOTHING
            """), {"rid": run_id})
            db.commit()

        # Insert instruments, history, and single trade with known traded value on as_of
        for tid, sym, tv in rank_test_ids:
            db.add(Instrument(
                instrument_id=tid,
                name=f"Rank Test {sym}",
                status="ACTIVE",
                first_observed_trade_date=datetime.date(2022, 1, 3),
            ))
            db.add(InstrumentSymbolHistory(
                instrument_id=tid,
                symbol=sym,
                isin=f"INE{sym.ljust(8, '0')}1",
                series="EQ",
                valid_from=datetime.date(2022, 1, 3),
                valid_to=None,
            ))
            db.add(DailyPriceRaw(
                instrument_id=tid,
                trade_date=as_of,
                series="EQ",
                open=Decimal("100.00"),
                high=Decimal("105.00"),
                low=Decimal("95.00"),
                close=Decimal("100.00"),
                last=Decimal("100.00"),
                prev_close=Decimal("100.00"),
                volume=10000,
                traded_value=tv,
                trades_count=100,
                ingestion_run_id=run_id,
            ))
        db.commit()

    try:
        # Build universe with partial lookback allowed and top_n=None to keep all eligible
        cfg = UniverseConfig(
            min_trading_completeness=Decimal("0.0"),
            min_turnover_completeness=Decimal("0.0"),
            min_adtv=Decimal("1000000.00"),
            allow_partial_lookback=True,
            top_n=None,
        )
        snap = universe_service.build_universe(as_of, config=cfg, persist=False)

        # Filter to our 4 test members
        test_members = [
            m for m in snap.eligible_members
            if m.instrument_id in [t[0] for t in rank_test_ids]
        ]
        assert len(test_members) == 4

        # Expected order:
        # Rank 1: DELTA (ADTV 999B)
        # Equal ADTV (888B) resolved alphabetically ascending:
        # Rank 2: ALPHA
        # Rank 3: BETA
        # Rank 4: ZETA
        sorted_symbols = [m.symbol for m in test_members]
        expected_symbols = ["DELTA", "ALPHA", "BETA", "ZETA"]
        assert sorted_symbols == expected_symbols, (
            f"Deterministic ranking tie-break failed! Expected {expected_symbols}, got {sorted_symbols}"
        )

        # Check relative ranks
        ranks = {m.symbol: m.rank for m in test_members}
        assert ranks["DELTA"] < ranks["ALPHA"] < ranks["BETA"] < ranks["ZETA"]

    finally:
        with get_db() as db:
            for tid, sym, _ in rank_test_ids:
                db.execute(text("DELETE FROM daily_prices_raw WHERE instrument_id = :id"), {"id": tid})
                db.execute(text("DELETE FROM instrument_symbol_history WHERE instrument_id = :id"), {"id": tid})
                db.execute(text("DELETE FROM instruments WHERE instrument_id = :id"), {"id": tid})
            db.commit()


# -------------------------------------------------------------------------
# Test 21: Raw-data manifest and code revision provenance verification
# -------------------------------------------------------------------------
def test_21_raw_data_manifest_and_code_revision_provenance(universe_service):
    """
    Test 21: Verifies that universe provenance is backed by cryptographic fingerprints:
    1. Raw data manifest computes a deterministic 64-character SHA-256 fingerprint.
    2. Modifying a single traded value alters the manifest fingerprint even if row counts match.
    3. Code revision accurately captures git revision (or dirty source hash).
    4. Universe snapshot embeds the manifest hash and code revision.
    """
    from signal_atlas.universe.provenance import compute_raw_data_manifest, get_code_revision

    with get_db() as db:
        m1 = compute_raw_data_manifest(db)

        assert len(m1.manifest_fingerprint) == 64, (
            f"Manifest fingerprint must be 64-char full SHA-256, got {len(m1.manifest_fingerprint)}"
        )
        assert m1.prices_row_count >= 0

        # Check code revision resolution
        rev = get_code_revision()
        assert len(rev) >= 7

        # Insert an instrument, symbol history, and synthetic price record
        run_id = db.execute(text("SELECT run_id FROM ingestion_runs LIMIT 1")).scalar() or "test-prov-run"
        db.add(Instrument(
            instrument_id="inst-prov-test",
            name="Provenance Test Corp",
            status="ACTIVE",
            first_observed_trade_date=datetime.date(2022, 1, 3),
        ))
        db.add(InstrumentSymbolHistory(
            instrument_id="inst-prov-test",
            symbol="PROVTEST",
            isin="INE999PROV01",
            series="EQ",
            valid_from=datetime.date(2022, 1, 3),
            valid_to=None,
        ))
        db.add(DailyPriceRaw(
            instrument_id="inst-prov-test",
            trade_date=datetime.date(2024, 7, 22),
            series="EQ",
            open=Decimal("100.00"),
            high=Decimal("105.00"),
            low=Decimal("95.00"),
            close=Decimal("102.00"),
            last=Decimal("102.00"),
            prev_close=Decimal("100.00"),
            volume=1000,
            traded_value=Decimal("102000.00"),
            trades_count=10,
            ingestion_run_id=run_id,
        ))
        db.commit()

        try:
            m2 = compute_raw_data_manifest(db)
            assert m2.manifest_fingerprint != m1.manifest_fingerprint
            assert m2.prices_row_count == m1.prices_row_count + 1

            # Modify traded value without changing row count
            db.execute(text("""
                UPDATE daily_prices_raw
                SET traded_value = :tv
                WHERE instrument_id = 'inst-prov-test'
            """), {"tv": Decimal("999999.00")})
            db.commit()

            m3 = compute_raw_data_manifest(db)
            # Row counts between m2 and m3 are identical
            assert m3.prices_row_count == m2.prices_row_count
            # But the fingerprint MUST change because data changed!
            assert m3.manifest_fingerprint != m2.manifest_fingerprint, (
                "Data manifest fingerprint must change when underlying values change, even if row count is unchanged!"
            )

            # Build universe and verify snapshot provenance fields
            snap = universe_service.build_universe(datetime.date(2024, 7, 22), persist=False)
            assert snap.raw_data_manifest_hash == m3.manifest_fingerprint
            assert snap.code_revision == rev
            assert len(snap.config.config_hash) == 64

        finally:
            db.execute(text("DELETE FROM daily_prices_raw WHERE instrument_id = 'inst-prov-test'"))
            db.execute(text("DELETE FROM instrument_symbol_history WHERE instrument_id = 'inst-prov-test'"))
            db.execute(text("DELETE FROM instruments WHERE instrument_id = 'inst-prov-test'"))
            db.commit()
