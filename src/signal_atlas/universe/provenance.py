"""Exact input provenance for point-in-time universe construction.

The manifest deliberately covers source tables read by the universe service. It
does not cover ``daily_prices_adjusted``: that table is derived data and is not
read while a universe snapshot is built.
"""

import datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from signal_atlas.db.models.calendar import TradingCalendar
from signal_atlas.db.models.corporate_actions import CorporateAction
from signal_atlas.db.models.ingestion import IngestionRun
from signal_atlas.db.models.instruments import Instrument, InstrumentSymbolHistory
from signal_atlas.db.models.prices import DailyPriceRaw
from signal_atlas.db.models.quarantine import DailyPriceQuarantine


MANIFEST_FORMAT = "signal-atlas-universe-inputs-v2"
_STREAM_BATCH_SIZE = 5_000


def _git_output(repo_root: Path, args: Sequence[str]) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, cwd=str(repo_root)
    ).stdout


def get_code_revision() -> str:
    """Return HEAD plus a deterministic fingerprint of relevant local changes.

    The dirty fingerprint separately frames staged and unstaged diffs under
    ``src/`` and ``alembic/`` and the path/content of untracked Python files in
    those directories. Other untracked artifacts do not affect executable
    universe code provenance.
    """
    ci_sha = os.environ.get("GITHUB_SHA")
    if ci_sha:
        return ci_sha.strip()

    return _get_code_revision(Path(__file__).resolve().parents[3])


def _get_code_revision(repo_root: Path) -> str:
    """Implementation split out to make isolated repository tests possible."""
    try:
        head_sha = _git_output(repo_root, ["rev-parse", "HEAD"]).strip()
        staged = _git_output(repo_root, ["diff", "--cached", "--", "src/", "alembic/"])
        unstaged = _git_output(repo_root, ["diff", "--", "src/", "alembic/"])
        untracked_paths = sorted(
            path for path in _git_output(
                repo_root, ["ls-files", "--others", "--exclude-standard", "--", "src/", "alembic/"]
            ).splitlines()
            if path.endswith(".py")
        )

        dirty = _dirty_fingerprint(
            staged,
            unstaged,
            [(path, (repo_root / path).read_bytes()) for path in untracked_paths],
        )

        if staged or unstaged or untracked_paths:
            return f"{head_sha}-dirty-{dirty.hexdigest()}"
        return head_sha
    except Exception:
        try:
            source_files = sorted(
                [*repo_root.joinpath("src").rglob("*.py"), *repo_root.joinpath("alembic").rglob("*.py")]
            )
            digest = hashlib.sha256()
            for path in source_files:
                digest.update(path.relative_to(repo_root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(path.read_bytes())
                digest.update(b"\0")
            return f"source-hash-{digest.hexdigest()}"
        except Exception:
            return "untracked-source"


def _dirty_fingerprint(
    staged: str,
    unstaged: str,
    untracked_files: Sequence[Tuple[str, bytes]],
) -> str:
    """Hash separately framed staged, unstaged, and untracked source state."""
    digest = hashlib.sha256()
    for label, value in (("staged", staged), ("unstaged", unstaged)):
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    for relative_path, contents in sorted(untracked_files):
        digest.update(b"untracked\0")
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(contents)
        digest.update(b"\0")
    return digest.hexdigest()


def _canonical_value(value: Any) -> Dict[str, Any]:
    """Encode values with explicit type tags, preserving NULL and empty strings."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": str(value)}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": format(value, "f")}
    if isinstance(value, datetime.datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, datetime.date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, str):
        return {"type": "string", "value": value}
    if isinstance(value, (list, tuple)):
        return {"type": "array", "value": [_canonical_value(item) for item in value]}
    if isinstance(value, dict):
        return {
            "type": "object",
            "value": {str(key): _canonical_value(value[key]) for key in sorted(value, key=str)},
        }
    if isinstance(value, float):
        return {"type": "float", "value": value.hex()}
    raise TypeError(f"Unsupported provenance value type: {type(value)!r}")


def _frame(digest: Any, value: Any) -> None:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def _stream_table(session: Session, table: Any, primary_key_columns: Sequence[Any]) -> Tuple[str, int, Optional[datetime.date], Optional[datetime.date]]:
    """Hash every row in primary-key order without materialising the table."""
    digest = hashlib.sha256()
    _frame(digest, {"table": table.name, "columns": [column.name for column in table.c]})
    statement = select(*table.c).order_by(*primary_key_columns).execution_options(
        stream_results=True, yield_per=_STREAM_BATCH_SIZE
    )
    result = session.execute(statement).mappings().yield_per(_STREAM_BATCH_SIZE)
    count = 0
    min_trade_date: Optional[datetime.date] = None
    max_trade_date: Optional[datetime.date] = None
    for row in result:
        _frame(digest, {column.name: _canonical_value(row[column.name]) for column in table.c})
        count += 1
        if table.name == "daily_prices_raw":
            trade_date = row["trade_date"]
            min_trade_date = trade_date if min_trade_date is None or trade_date < min_trade_date else min_trade_date
            max_trade_date = trade_date if max_trade_date is None or trade_date > max_trade_date else max_trade_date
    return digest.hexdigest(), count, min_trade_date, max_trade_date


class RawDataManifest(BaseModel):
    """Exact, versioned SHA-256 provenance for universe-construction inputs."""
    model_config = ConfigDict(frozen=True)

    format_version: str = MANIFEST_FORMAT
    table_row_counts: Dict[str, int] = Field(default_factory=dict)
    table_hashes: Dict[str, str] = Field(default_factory=dict)
    prices_row_count: int = 0
    prices_min_date: Optional[datetime.date] = None
    prices_max_date: Optional[datetime.date] = None
    instruments_count: int = 0
    symbol_history_count: int = 0
    quarantine_records_count: int = 0
    calendar_trading_days_count: int = 0
    calendar_min_date: Optional[datetime.date] = None
    calendar_max_date: Optional[datetime.date] = None
    ingestion_runs_count: int = 0
    corporate_actions_count: int = 0
    manifest_fingerprint: str

    def canonical_dict(self) -> Dict[str, Any]:
        def serialize(value: Any) -> Any:
            return value.isoformat() if isinstance(value, (datetime.date, datetime.datetime)) else value

        return {
            "format_version": self.format_version,
            "table_row_counts": dict(sorted(self.table_row_counts.items())),
            "table_hashes": dict(sorted(self.table_hashes.items())),
            "prices_row_count": self.prices_row_count,
            "prices_min_date": serialize(self.prices_min_date),
            "prices_max_date": serialize(self.prices_max_date),
            "instruments_count": self.instruments_count,
            "symbol_history_count": self.symbol_history_count,
            "quarantine_records_count": self.quarantine_records_count,
            "calendar_trading_days_count": self.calendar_trading_days_count,
            "calendar_min_date": serialize(self.calendar_min_date),
            "calendar_max_date": serialize(self.calendar_max_date),
            "ingestion_runs_count": self.ingestion_runs_count,
            "corporate_actions_count": self.corporate_actions_count,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))


_cached_manifest: Optional[RawDataManifest] = None
MANIFEST_CACHE_FILE = Path("data/.raw_manifest_cache.json")


def compute_raw_data_manifest(session: Session, force_refresh: bool = False) -> RawDataManifest:
    """Compute an exact streaming manifest of all direct universe inputs.
    Uses memory and disk caching when available for high-throughput evaluation.
    """
    global _cached_manifest
    if not force_refresh:
        if _cached_manifest is not None:
            return _cached_manifest
        if MANIFEST_CACHE_FILE.exists():
            try:
                data = json.loads(MANIFEST_CACHE_FILE.read_text(encoding="utf-8"))
                _cached_manifest = RawDataManifest.model_validate(data)
                return _cached_manifest
            except Exception:
                pass
    table_specs = (
        (DailyPriceRaw.__table__, (DailyPriceRaw.__table__.c.id,)),
        (Instrument.__table__, (Instrument.__table__.c.instrument_id,)),
        (InstrumentSymbolHistory.__table__, (InstrumentSymbolHistory.__table__.c.id,)),
        (TradingCalendar.__table__, (TradingCalendar.__table__.c.trade_date,)),
        (DailyPriceQuarantine.__table__, (DailyPriceQuarantine.__table__.c.id,)),
        (IngestionRun.__table__, (IngestionRun.__table__.c.run_id,)),
        (CorporateAction.__table__, (CorporateAction.__table__.c.action_id,)),
    )
    manifest_digest = hashlib.sha256()
    _frame(manifest_digest, {"format_version": MANIFEST_FORMAT})
    table_hashes: Dict[str, str] = {}
    row_counts: Dict[str, int] = {}
    price_min: Optional[datetime.date] = None
    price_max: Optional[datetime.date] = None

    for table, primary_key_columns in table_specs:
        table_hash, count, min_date, max_date = _stream_table(session, table, primary_key_columns)
        table_hashes[table.name] = table_hash
        row_counts[table.name] = count
        _frame(manifest_digest, {"table": table.name, "row_count": count, "sha256": table_hash})
        if table.name == "daily_prices_raw":
            price_min, price_max = min_date, max_date

    calendar_rows = session.execute(
        select(TradingCalendar.trade_date)
        .where(TradingCalendar.is_trading_day.is_(True))
        .order_by(TradingCalendar.trade_date)
    ).scalars().all()

    manifest = RawDataManifest(
        table_row_counts=row_counts,
        table_hashes=table_hashes,
        prices_row_count=row_counts[DailyPriceRaw.__tablename__],
        prices_min_date=price_min,
        prices_max_date=price_max,
        instruments_count=row_counts[Instrument.__tablename__],
        symbol_history_count=row_counts[InstrumentSymbolHistory.__tablename__],
        quarantine_records_count=row_counts[DailyPriceQuarantine.__tablename__],
        calendar_trading_days_count=len(calendar_rows),
        calendar_min_date=calendar_rows[0] if calendar_rows else None,
        calendar_max_date=calendar_rows[-1] if calendar_rows else None,
        ingestion_runs_count=row_counts[IngestionRun.__tablename__],
        corporate_actions_count=row_counts[CorporateAction.__tablename__],
        manifest_fingerprint=manifest_digest.hexdigest(),
    )
    _cached_manifest = manifest
    try:
        MANIFEST_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_CACHE_FILE.write_text(manifest.model_dump_json(), encoding="utf-8")
    except Exception:
        pass
    return manifest
