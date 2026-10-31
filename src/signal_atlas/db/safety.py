"""
Safety guards for database connections and test environment isolation.
Ensures application and production databases can never be targeted, dropped, or
mutated by automated test suites or misconfigured services.
"""
import os
from typing import Optional
from sqlalchemy.engine import make_url, URL


def normalize_host(host: Optional[str]) -> str:
    """Normalize localhost and loopback IPv4 addresses."""
    if not host or host in ("localhost", "127.0.0.1"):
        return "127.0.0.1"
    return host.lower()


def normalize_port(port: Optional[int]) -> int:
    """Normalize PostgreSQL port, defaulting to 5432 if omitted."""
    return port if port is not None else 5432


def validate_test_database_isolation(
    app_url_str: Optional[str],
    test_url_str: Optional[str],
) -> bool:
    """
    Strictly validates that both DATABASE_URL (used by application services via get_db())
    and TEST_DATABASE_URL (used by test fixtures) identify the EXACT same isolated test database,
    and that the target database ends with '_test'.

    Raises RuntimeError immediately if:
    1. Either URL is missing or empty.
    2. The test database name does NOT end with '_test'.
    3. The application database name does NOT end with '_test'.
    4. The application and test database names do not match.
    5. The hosts or ports do not match.
    6. Any URL attempts to target the application database (e.g. 'signal_atlas').

    NOTE: ALLOW_DESTRUCTIVE_TESTS=1 cannot bypass the requirement that the database end with '_test'.
    """
    if not test_url_str:
        raise RuntimeError(
            "CRITICAL SAFETY ABORT: TEST_DATABASE_URL environment variable is not configured. "
            "Automated tests must be pointed to an isolated test database ending with '_test'."
        )

    if not app_url_str:
        raise RuntimeError(
            "CRITICAL SAFETY ABORT: DATABASE_URL environment variable is not configured. "
            "Both DATABASE_URL and TEST_DATABASE_URL must be configured to the same isolated test database."
        )

    try:
        test_url = make_url(test_url_str)
    except Exception as e:
        raise RuntimeError(f"CRITICAL SAFETY ABORT: Malformed TEST_DATABASE_URL: {e}") from e

    try:
        app_url = make_url(app_url_str)
    except Exception as e:
        raise RuntimeError(f"CRITICAL SAFETY ABORT: Malformed DATABASE_URL: {e}") from e

    test_db = test_url.database or ""
    app_db = app_url.database or ""

    # 1. Reject SQLite in non-memory mode if path doesn't indicate test
    if test_url.drivername.startswith("sqlite"):
        if test_db and test_db != ":memory:" and not test_db.endswith("_test.db"):
            raise RuntimeError(
                f"CRITICAL SAFETY ABORT: SQLite test database '{test_db}' must be ':memory:' or end with '_test.db'."
            )
        return True

    # 2. Require test database name to end with '_test' (ALLOW_DESTRUCTIVE_TESTS cannot bypass this)
    if not test_db.endswith("_test"):
        raise RuntimeError(
            f"CRITICAL SAFETY ABORT: TEST_DATABASE_URL target database '{test_db}' does not end with '_test'. "
            f"Automated test suites are strictly prohibited from targeting non-test databases. "
            f"ALLOW_DESTRUCTIVE_TESTS cannot bypass this requirement."
        )

    # 3. Require application database name to end with '_test' during test execution
    if not app_db.endswith("_test"):
        raise RuntimeError(
            f"CRITICAL SAFETY ABORT: DATABASE_URL target database '{app_db}' does not end with '_test'. "
            f"Application services calling get_db() without an explicit session would connect to "
            f"the development/production database '{app_db}'. "
            f"To protect development data, DATABASE_URL must match TEST_DATABASE_URL and end with '_test'."
        )

    # 4. Require exact database name match between DATABASE_URL and TEST_DATABASE_URL
    if test_db != app_db:
        raise RuntimeError(
            f"CRITICAL SAFETY ABORT: Database configuration mismatch! "
            f"DATABASE_URL targets '{app_db}' while TEST_DATABASE_URL targets '{test_db}'. "
            f"All tests and service-level get_db() calls must use the identical isolated test database."
        )

    # 5. Require host and port match
    app_host = normalize_host(app_url.host)
    test_host = normalize_host(test_url.host)
    if app_host != test_host:
        raise RuntimeError(
            f"CRITICAL SAFETY ABORT: Host mismatch between DATABASE_URL ('{app_url.host}') "
            f"and TEST_DATABASE_URL ('{test_url.host}'). Both must target the same PostgreSQL host."
        )

    app_port = normalize_port(app_url.port)
    test_port = normalize_port(test_url.port)
    if app_port != test_port:
        raise RuntimeError(
            f"CRITICAL SAFETY ABORT: Port mismatch between DATABASE_URL ({app_url.port}) "
            f"and TEST_DATABASE_URL ({test_url.port}). Both must target the same PostgreSQL port."
        )

    return True
