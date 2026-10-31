import datetime
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import sessionmaker

from signal_atlas.db.models.calendar import TradingCalendar
from signal_atlas.db.models.instruments import Instrument
from signal_atlas.db.models.universe import UniverseMemberRecord, UniverseSnapshotRecord
from signal_atlas.db.session import get_db
from signal_atlas.universe.models import (
    UniverseConfig,
    UniverseMember,
    UniverseSnapshot,
)
from signal_atlas.universe.provenance import RawDataManifest
from signal_atlas.universe.service import PointInTimeUniverseService


def test_postgres_idle_session_establishes_repeatable_read(pg_engine):
    """
    1. Idle session: Entering PointInTimeUniverseService._consistent_snapshot_transaction(session)
    establishes the actual PostgreSQL connection isolation level as REPEATABLE READ.
    Verified via SQLAlchemy Connection.get_isolation_level() and direct engine SQL query.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    session = SessionFactory()
    try:
        assert not session.in_transaction()

        with PointInTimeUniverseService._consistent_snapshot_transaction(session):
            assert session.in_transaction()
            conn = session.connection()
            isolation_level = conn.get_isolation_level().upper().replace("_", " ")
            assert isolation_level == "REPEATABLE READ"

            # Directly verify from PostgreSQL server session setting
            pg_isolation = session.execute(text("SHOW transaction_isolation")).scalar()
            assert pg_isolation.lower() == "repeatable read"

        # Exiting context manager must not close the caller-owned session
        assert session.is_active
    finally:
        session.rollback()
        session.close()


def test_postgres_already_active_read_committed_is_rejected(pg_engine):
    """
    2. Already-active READ COMMITTED: If the caller session already has an active
    transaction at READ COMMITTED isolation level, _consistent_snapshot_transaction
    must reject it with RuntimeError.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    session = SessionFactory()
    try:
        # Activate default transaction with a harmless statement
        session.execute(text("SELECT 1"))
        assert session.in_transaction()
        assert session.connection().get_isolation_level().upper().replace("_", " ") == "READ COMMITTED"

        with pytest.raises(
            RuntimeError,
            match="Universe construction requires a PostgreSQL REPEATABLE READ transaction",
        ):
            with PointInTimeUniverseService._consistent_snapshot_transaction(session):
                pass
    finally:
        session.rollback()
        session.close()


def test_postgres_already_active_repeatable_read_is_accepted(pg_engine):
    """
    3. Already-active REPEATABLE READ: If the caller session already has an active
    transaction at REPEATABLE READ, _consistent_snapshot_transaction accepts it.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    session = SessionFactory()
    try:
        conn = session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        session.execute(text("SELECT 1"))
        assert session.in_transaction()
        assert conn.get_isolation_level().upper().replace("_", " ") == "REPEATABLE READ"

        # Must succeed without raising
        with PointInTimeUniverseService._consistent_snapshot_transaction(session):
            assert session.in_transaction()
    finally:
        session.rollback()
        session.close()


def test_postgres_caller_ownership_preserved_not_committed_or_closed(pg_engine):
    """
    4. Caller ownership: Verify that leaving _consistent_snapshot_transaction
    does not commit or close a caller-owned session/transaction.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    session = SessionFactory()
    try:
        with PointInTimeUniverseService._consistent_snapshot_transaction(session):
            session.execute(text("SELECT 1"))
            assert session.in_transaction()

        # Session remains open, active, and in transaction
        assert session.is_active
        assert session.in_transaction()
    finally:
        session.rollback()
        session.close()


def test_postgres_deterministic_snapshot_consistency_across_two_sessions(pg_engine):
    """
    5. Snapshot consistency: Deterministic two-session test:
    - Transaction A establishes repeatable-read snapshot and reads a manifest-relevant row.
    - Transaction B modifies that row and commits.
    - Transaction A must continue to observe the original value until A ends.
    - A new transaction (Transaction C) must observe the changed value.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    synthetic_date = datetime.date(2099, 12, 31)

    # Initial setup with synthetic row
    with SessionFactory() as setup_session:
        setup_session.execute(delete(TradingCalendar).where(TradingCalendar.trade_date == synthetic_date))
        setup_session.add(
            TradingCalendar(
                trade_date=synthetic_date,
                is_trading_day=True,
                holiday_name="INITIAL_SNAPSHOT_VALUE",
            )
        )
        setup_session.commit()

    session_a = SessionFactory()
    session_b = SessionFactory()
    try:
        # Step 1: Transaction A establishes repeatable-read snapshot and queries row
        with PointInTimeUniverseService._consistent_snapshot_transaction(session_a):
            val_a_initial = session_a.execute(
                select(TradingCalendar.holiday_name).where(TradingCalendar.trade_date == synthetic_date)
            ).scalar()
            assert val_a_initial == "INITIAL_SNAPSHOT_VALUE"

            # Step 2: Transaction B modifies the row and commits
            session_b.execute(
                update(TradingCalendar)
                .where(TradingCalendar.trade_date == synthetic_date)
                .values(holiday_name="COMMITTED_BY_TRANSACTION_B")
            )
            session_b.commit()

            # Step 3: Transaction A must continue to observe the original snapshot value
            val_a_repeat = session_a.execute(
                select(TradingCalendar.holiday_name).where(TradingCalendar.trade_date == synthetic_date)
            ).scalar()
            assert val_a_repeat == "INITIAL_SNAPSHOT_VALUE", (
                "Repeatable Read violation: Transaction A observed committed changes from Transaction B!"
            )

        # Step 4: Transaction A ends
        session_a.rollback()

        # Step 5: A new transaction observes the updated committed value
        with SessionFactory() as session_c:
            val_c = session_c.execute(
                select(TradingCalendar.holiday_name).where(TradingCalendar.trade_date == synthetic_date)
            ).scalar()
            assert val_c == "COMMITTED_BY_TRANSACTION_B"
    finally:
        session_a.close()
        session_b.close()
        with SessionFactory() as cleanup_session:
            cleanup_session.execute(delete(TradingCalendar).where(TradingCalendar.trade_date == synthetic_date))
            cleanup_session.commit()


def test_postgres_cache_persistence_across_commit_and_separate_session(pg_engine, monkeypatch):
    """
    Section 4.2: Prove cache persistence across a commit and a new session.
    1. Create a session from isolated PostgreSQL test engine.
    2. Call get_universe() with that externally supplied session. Exercises real
       _persist_snapshot_record() and real database persistence.
    3. Verify the service has NOT committed the externally supplied session.
       A separate observer session must NOT see the uncommitted snapshot.
    4. Explicitly commit in the caller, then close the first session.
    5. Open a completely new session.
    6. Call get_universe() again with same as_of_date, config, code_revision, and manifest.
    7. Assert the returned snapshot is loaded from cache and builder is not called second time.
    8. Assert the same snapshot identity and relevant metadata/member values are returned.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    as_of_date = datetime.date(2024, 6, 14)
    test_suffix = uuid.uuid4().hex[:8]
    test_inst_id = f"inst-cross-{test_suffix}"
    test_code_revision = f"rev-{test_suffix}"
    synthetic_snap_id = f"SNAP-TEST-{test_suffix}"

    # Ensure synthetic instrument exists for foreign key constraint in universe_members
    with SessionFactory() as init_session:
        init_session.add(
            Instrument(
                instrument_id=test_inst_id,
                name=f"TEST INSTRUMENT {test_suffix}",
                status="ACTIVE",
            )
        )
        init_session.commit()

    build_invocations = []
    service = PointInTimeUniverseService()

    fixed_manifest = RawDataManifest(
        manifest_fingerprint=f"m-{test_suffix}" + "0" * (64 - len(test_suffix) - 2),
        table_fingerprints={},
        counts={},
        date_ranges={},
        aggregates={},
    )
    monkeypatch.setattr(
        "signal_atlas.universe.service.compute_raw_data_manifest",
        lambda _session: fixed_manifest,
    )

    def test_builder(as_of_date, config, persist, session, raw_manifest):
        build_invocations.append((as_of_date, config.config_identifier))
        member = UniverseMember(
            instrument_id=test_inst_id,
            symbol="TESTCROSS",
            isin="INE000X01099",
            series="EQ",
            observed_sessions_count=126,
            missing_sessions_count=0,
            trading_completeness=Decimal("1.0000"),
            expected_lookback_sessions=126,
            valid_turnover_sessions_count=126,
            turnover_data_completeness=Decimal("1.0000"),
            total_turnover=Decimal("12600000.00"),
            average_daily_turnover=Decimal("100000.00"),
            median_daily_turnover=Decimal("100000.00"),
            null_turnover_count=0,
            zero_turnover_count=0,
            positive_turnover_count=126,
            latest_raw_close=Decimal("150.00"),
            is_eligible=True,
            rank=1,
            exclusion_reason=None,
            exclusion_detail=None,
        )
        snapshot = UniverseSnapshot(
            snapshot_id=synthetic_snap_id,
            as_of_date=as_of_date,
            lookback_sessions=126,
            lookback_start_date=as_of_date - datetime.timedelta(days=180),
            lookback_end_date=as_of_date,
            config=config,
            config_identifier=config.config_identifier,
            adjustment_version=config.adjustment_version,
            raw_data_version=config.raw_data_version,
            raw_data_manifest_hash=raw_manifest.manifest_fingerprint,
            raw_data_manifest=raw_manifest.canonical_dict(),
            data_coverage_start=config.data_coverage_start,
            data_coverage_end=config.data_coverage_end,
            code_revision=config.code_revision,
            total_instruments_evaluated=1,
            eligible_count=1,
            excluded_count=0,
            eligible_members=[member],
            excluded_members=[],
        )
        if persist:
            service._persist_snapshot_record(snapshot, session)
        return snapshot

    monkeypatch.setattr(service, "_build_universe", test_builder)
    cfg = UniverseConfig(code_revision=test_code_revision)

    session_1 = SessionFactory()
    session_observer = SessionFactory()
    try:
        # Step 2: Call get_universe() with externally supplied session
        snap_1 = service.get_universe(as_of_date, config=cfg, session=session_1)
        assert len(build_invocations) == 1
        assert snap_1.snapshot_id == synthetic_snap_id

        # Step 3: Verify the service has NOT committed the externally supplied session.
        # An observer session must not see the uncommitted snapshot in PostgreSQL.
        uncommitted_check = session_observer.execute(
            select(UniverseSnapshotRecord).where(UniverseSnapshotRecord.snapshot_id == synthetic_snap_id)
        ).scalars().first()
        assert uncommitted_check is None, (
            "Service prematurely committed caller-owned session! Observer should not see uncommitted snapshot."
        )

        # Step 4: Explicitly commit in caller, then close session 1
        session_1.commit()
        session_1.close()

        # Step 5: Open completely new session
        session_2 = SessionFactory()

        # Step 6: Call get_universe() again with same params
        snap_2 = service.get_universe(as_of_date, config=cfg, session=session_2)

        # Step 7: Assert loaded from cache and builder is not called a second time
        assert len(build_invocations) == 1, (
            f"Expected cache hit but builder was called {len(build_invocations)} times!"
        )

        # Step 8: Assert same snapshot identity and relevant metadata/member values
        assert snap_2.snapshot_id == snap_1.snapshot_id
        assert snap_2.as_of_date == snap_1.as_of_date
        assert snap_2.config_identifier == snap_1.config_identifier
        assert snap_2.raw_data_manifest_hash == snap_1.raw_data_manifest_hash
        assert snap_2.code_revision == snap_1.code_revision
        assert snap_2.eligible_count == 1
        assert len(snap_2.eligible_members) == 1
        m2 = snap_2.eligible_members[0]
        assert m2.instrument_id == test_inst_id
        assert m2.symbol == "TESTCROSS"
        assert m2.average_daily_turnover == Decimal("100000.00")
        assert m2.latest_raw_close == Decimal("150.00")
        assert m2.rank == 1
        assert m2.is_eligible is True

        session_2.close()
    finally:
        # Cleanup test-generated rows
        with SessionFactory() as cleanup_session:
            cleanup_session.execute(
                delete(UniverseMemberRecord).where(UniverseMemberRecord.snapshot_id == synthetic_snap_id)
            )
            cleanup_session.execute(
                delete(UniverseSnapshotRecord).where(UniverseSnapshotRecord.snapshot_id == synthetic_snap_id)
            )
            cleanup_session.execute(
                delete(Instrument).where(Instrument.instrument_id == test_inst_id)
            )
            cleanup_session.commit()
        session_observer.close()


def test_postgres_internally_managed_get_db_lifecycle(pg_engine):
    """
    Verify internally managed get_db() lifecycle against PostgreSQL:
    - Automatically commits on successful block completion.
    - Automatically rolls back on exception.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    test_date = datetime.date(2098, 5, 20)

    # 1. Successful block commits automatically
    with get_db() as db:
        db.add(TradingCalendar(trade_date=test_date, is_trading_day=False, holiday_name="INTERNAL_COMMIT_TEST"))

    # Verify committed in separate session
    with SessionFactory() as check_session:
        row = check_session.execute(
            select(TradingCalendar).where(TradingCalendar.trade_date == test_date)
        ).scalars().first()
        assert row is not None
        assert row.holiday_name == "INTERNAL_COMMIT_TEST"

    # 2. Exceptional block rolls back automatically
    try:
        with get_db() as db:
            db.execute(
                update(TradingCalendar)
                .where(TradingCalendar.trade_date == test_date)
                .values(holiday_name="SHOULD_ROLLBACK")
            )
            raise ValueError("Simulated failure inside internally managed get_db()")
    except ValueError:
        pass

    # Verify rolled back in separate session (holiday_name unchanged)
    with SessionFactory() as check_session:
        row = check_session.execute(
            select(TradingCalendar).where(TradingCalendar.trade_date == test_date)
        ).scalars().first()
        assert row is not None
        assert row.holiday_name == "INTERNAL_COMMIT_TEST"

    # Cleanup
    with SessionFactory() as cleanup_session:
        cleanup_session.execute(delete(TradingCalendar).where(TradingCalendar.trade_date == test_date))
        cleanup_session.commit()
