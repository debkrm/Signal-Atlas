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


@pytest.fixture(scope="session")
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
        Base.metadata.create_all(bind=engine)
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
        # Clean data between integration test runs to ensure isolation
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
        session.close()
