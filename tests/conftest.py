import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from signal_atlas.db.base import Base

PG_TEST_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas_test",
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
    """Create a connection engine to the local PostgreSQL test database."""
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
