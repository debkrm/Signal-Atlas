"""
Unit tests for database safety guards and test environment isolation.
Verifies that tests and application services cannot silently target, drop, or mutate
the application development or production database.
"""
import os
import subprocess
import sys
import pytest

from signal_atlas.db.safety import validate_test_database_isolation
from signal_atlas.db.session import get_engine


def test_mismatched_database_names_aborts():
    """Verify that differing application and test databases raise a critical safety abort."""
    app_url = "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas"
    test_url = "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas_test"

    with pytest.raises(RuntimeError, match="CRITICAL SAFETY ABORT"):
        validate_test_database_isolation(app_url, test_url)


def test_non_test_database_name_aborts():
    """Verify that databases not ending with '_test' are strictly rejected."""
    # App and test both pointing to prod/dev
    app_url = "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas"
    test_url = "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas"

    with pytest.raises(RuntimeError, match="does not end with '_test'"):
        validate_test_database_isolation(app_url, test_url)


def test_destructive_override_cannot_bypass_test_database_suffix(monkeypatch):
    """Verify that ALLOW_DESTRUCTIVE_TESTS=1 cannot bypass the _test naming requirement."""
    monkeypatch.setenv("ALLOW_DESTRUCTIVE_TESTS", "1")
    app_url = "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas"
    test_url = "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas"

    with pytest.raises(RuntimeError, match="does not end with '_test'"):
        validate_test_database_isolation(app_url, test_url)


def test_host_or_port_mismatch_aborts():
    """Verify that differing host or port configurations abort execution."""
    app_url = "postgresql+psycopg2://postgres:postgres@10.0.0.1:5433/signal_atlas_test"
    test_url = "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas_test"

    with pytest.raises(RuntimeError, match="Host mismatch"):
        validate_test_database_isolation(app_url, test_url)

    app_url2 = "postgresql+psycopg2://postgres:postgres@localhost:5432/signal_atlas_test"
    test_url2 = "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas_test"

    with pytest.raises(RuntimeError, match="Port mismatch"):
        validate_test_database_isolation(app_url2, test_url2)


def test_matching_test_database_urls_succeed():
    """Verify that identical test database URLs with _test suffix pass validation."""
    app_url = "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas_test"
    test_url = "postgresql+psycopg2://postgres:postgres@127.0.0.1:5433/signal_atlas_test"

    assert validate_test_database_isolation(app_url, test_url) is True


def test_get_engine_blocks_non_test_db_during_pytest(monkeypatch):
    """Verify that get_engine refuses to connect to a non-test database while under test."""
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_database_safety.py::test_guard")
    dev_url = "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas"

    with pytest.raises(RuntimeError, match="CRITICAL SAFETY ABORT: Attempted to create database engine for 'signal_atlas'"):
        get_engine(dev_url)


def test_pytest_execution_aborts_immediately_on_mismatched_env_urls():
    """
    Subprocess test: Verify that running pytest with mismatched DATABASE_URL and TEST_DATABASE_URL
    aborts at pytest startup before any database query or test execution can occur.
    """
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas"
    env["TEST_DATABASE_URL"] = "postgresql+psycopg2://postgres:postgres@localhost:5433/signal_atlas_test"

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/test_config.py"],
        env=env,
        capture_output=True,
        text=True,
    )

    assert proc.returncode != 0
    assert "CRITICAL SAFETY ABORT" in (proc.stdout + proc.stderr)
