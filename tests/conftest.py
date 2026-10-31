import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from signal_atlas.config import settings
from signal_atlas.db.base import Base

PG_TEST_URL = os.environ.get(
    "TEST_DATABASE_URL",
    settings.database_url.rsplit("/", 1)[0] + "/signal_atlas_test"
    if settings.database_url
    else "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas_test",
)


@pytest.fixture
def test_engine():
    """Create an isolated in-memory SQLite database for fast unit tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def test_db(test_engine):
    """Provide a transactional session bound to the in-memory SQLite database."""
    SessionFactory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="session", autouse=True)
def pg_engine():
    """
    Create a connection engine to the local PostgreSQL test database with strict safety guards.
    Ensures that test teardowns and table cleanups can NEVER target the application database.
    """
    test_url = make_url(PG_TEST_URL)
    app_url = make_url(settings.database_url) if settings.database_url else None

    test_db = test_url.database or ""
    app_db = app_url.database if app_url else ""

    # 1. Refuse to run against the configured application database
    if app_db and test_db == app_db and os.environ.get("ALLOW_DESTRUCTIVE_TESTS") != "1":
        raise RuntimeError(
            f"CRITICAL SAFETY ABORT: Test database '{test_db}' matches configured application database! "
            f"Tests would drop and truncate application tables. "
            f"Configure a dedicated test database (e.g. 'signal_atlas_test') or set ALLOW_DESTRUCTIVE_TESTS=1."
        )

    # 2. Require test database name to end with '_test' unless explicitly overridden
    if not test_db.endswith("_test") and os.environ.get("ALLOW_DESTRUCTIVE_TESTS") != "1":
        raise RuntimeError(
            f"CRITICAL SAFETY ABORT: Test database name '{test_db}' must end with '_test' to prevent "
            f"accidental destruction of production or development data. Override with ALLOW_DESTRUCTIVE_TESTS=1."
        )

    print(f"\n[TEST SUITE TARGET] Isolated integration test database: '{test_db}' on host '{test_url.host}:{test_url.port}'")

    try:
        engine = create_engine(PG_TEST_URL, pool_pre_ping=True)
        # Test connection
        with engine.connect() as conn:
            pass
        import signal_atlas.db.models
        from signal_atlas.providers.nse.calendar import NSETradingCalendar
        from signal_atlas.db.models.calendar import TradingCalendar
        from signal_atlas.db.models.ingestion import IngestionRun
        from sqlalchemy import func, select
        import datetime

        Base.metadata.create_all(bind=engine)

        # Seed static trading calendar and base ingestion run if empty
        SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        with SessionFactory() as init_session:
            cal_count = init_session.execute(select(func.count(TradingCalendar.trade_date))).scalar()
            if cal_count == 0:
                trading_days = NSETradingCalendar.get_expected_trading_days(
                    datetime.date(2022, 1, 1), datetime.date(2024, 12, 31)
                )
                records = [
                    TradingCalendar(trade_date=d, is_trading_day=True)
                    for d in trading_days
                ]
                init_session.add_all(records)

            run_count = init_session.execute(select(func.count(IngestionRun.run_id))).scalar()
            if run_count == 0:
                init_session.add(
                    IngestionRun(
                        run_id="ci-test-run-001",
                        source="NSE",
                        trade_date=datetime.date(2022, 1, 3),
                        file_name="ci_test.zip",
                        file_hash="ci_test_hash",
                        parser_version="v1",
                        status="SUCCESS",
                        row_count=0,
                    )
                )
            init_session.commit()

        yield engine
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
    except Exception as e:
        pytest.skip(f"PostgreSQL test database not available: {e}")


@pytest.fixture
def pg_db(pg_engine):
    """Provide an isolated transactional session for PostgreSQL integration tests."""
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.rollback()
        # Clean data between integration test runs to ensure isolation (preserve static calendar and seed run)
        for table in reversed(Base.metadata.sorted_tables):
            if table.name == "trading_calendar":
                continue
            elif table.name == "ingestion_runs":
                session.execute(table.delete().where(table.c.run_id != "ci-test-run-001"))
            else:
                session.execute(table.delete())
        session.commit()
        session.close()


@pytest.fixture(autouse=True)
def skip_if_missing_bulk_dataset(request):
    """
    Automatically skips integration tests that depend on the uncommitted 2-year bulk
    historical NSE dataset (1.85M raw prices, 20k corporate actions) when running in an
    isolated CI environment where the bulk dataset has not been ingested.
    """
    bulk_test_modules = {
        "test_adjustment_math",
        "test_bulk_adjusted_prices",
        "test_candidate_identity_reconciliation",
        "test_corporate_action_identity_consistency",
        "test_corporate_actions",
        "test_kaushalya_reverse_split",
        "test_v1_3_financial_closure",
    }
    bulk_test_names = {
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

    mod_name = request.module.__name__.split(".")[-1]
    test_name = request.node.name

    if mod_name in bulk_test_modules or test_name in bulk_test_names:
        with sessionmaker(bind=create_engine(settings.database_url))() as session:
            try:
                from signal_atlas.db.models.prices import DailyPriceRaw
                from sqlalchemy import func, select
                count = session.execute(select(func.count(DailyPriceRaw.id))).scalar()
                if count == 0:
                    pytest.skip("Bulk 2-year historical NSE dataset not loaded in isolated test database")
            except Exception:
                pytest.skip("Test database not initialized with bulk historical dataset")
