from contextlib import contextmanager
from typing import Generator, Optional
from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session

from signal_atlas.config import settings
from signal_atlas.db.base import Base

_engine: Optional[Engine] = None
_SessionFactory: Optional[sessionmaker[Session]] = None


def get_engine(database_url: Optional[str] = None) -> Engine:
    global _engine
    import os
    from sqlalchemy.engine import make_url

    url = database_url or settings.database_url
    if not url:
        raise ValueError("No database URL provided or configured in settings.")

    # Guard: During test execution, strictly reject any PostgreSQL database not ending in '_test'
    if "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("TEST_ENVIRONMENT") == "1":
        if not url.startswith("sqlite"):
            parsed = make_url(url)
            db_name = parsed.database or ""
            if not db_name.endswith("_test"):
                raise RuntimeError(
                    f"CRITICAL SAFETY ABORT: Attempted to create database engine for '{db_name}' "
                    f"during test execution! All database connections in tests must target a database ending with '_test'."
                )

    if _engine is None or database_url is not None:
        engine_kwargs = {}
        if url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        else:
            engine_kwargs.update(
                {
                    "pool_size": 5,
                    "max_overflow": 10,
                    "pool_pre_ping": True,
                }
            )
        eng = create_engine(url, **engine_kwargs)
        if database_url is None:
            _engine = eng
        return eng
    return _engine


def get_session_factory(engine: Optional[Engine] = None) -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None or engine is not None:
        eng = engine or get_engine()
        factory = sessionmaker(bind=eng, autoflush=False, autocommit=False)
        if engine is None:
            _SessionFactory = factory
        return factory
    return _SessionFactory


@contextmanager
def get_db(session: Optional[Session] = None) -> Generator[Session, None, None]:
    """
    Context manager providing a transactional database session.
    Automatically commits on success and rolls back on exception.
    """
    if session is not None:
        yield session
        return

    factory = get_session_factory()
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db(engine: Optional[Engine] = None) -> None:
    """Create all tables directly (useful for local dev or in-memory test databases)."""
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)
