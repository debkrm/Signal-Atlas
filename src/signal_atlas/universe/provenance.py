import datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session


def get_code_revision() -> str:
    """
    Captures the exact verifiable code revision:
    1. GITHUB_SHA environment variable in CI environments.
    2. Local Git HEAD commit SHA.
    3. If working tree has modified tracked source files, appends '-dirty-{diff_hash}'.
    4. Deterministic SHA-256 source-tree fingerprint fallback if git is unavailable.
    """
    # 1. Check CI environment variable
    ci_sha = os.environ.get("GITHUB_SHA")
    if ci_sha:
        return ci_sha.strip()

    # 2. Query local git repository
    repo_root = Path(__file__).resolve().parents[3]
    try:
        head_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(repo_root),
        )
        head_sha = head_proc.stdout.strip()

        # Check for uncommitted modifications in tracked source and migration files
        diff_proc = subprocess.run(
            ["git", "diff", "HEAD", "--", "src/", "alembic/"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(repo_root),
        )
        diff_output = diff_proc.stdout
        if diff_output:
            diff_hash = hashlib.sha256(diff_output.encode("utf-8")).hexdigest()[:12]
            return f"{head_sha}-dirty-{diff_hash}"
        return head_sha
    except Exception:
        # Fallback: compute deterministic hash of source tree
        try:
            h = hashlib.sha256()
            src_dir = repo_root / "src"
            for p in sorted(src_dir.rglob("*.py")):
                h.update(p.relative_to(repo_root).as_posix().encode("utf-8"))
                h.update(p.read_bytes())
            return f"source-hash-{h.hexdigest()[:40]}"
        except Exception:
            return "phase-1b-iii.1-untracked"


class RawDataManifest(BaseModel):
    """
    Deterministic cryptographic manifest of the raw data contents used in universe construction.
    Covers daily_prices_raw, instruments, instrument_symbol_history, trading_calendar,
    quarantine records, and ingestion runs.
    """
    model_config = ConfigDict(frozen=True)

    prices_row_count: int
    prices_min_date: Optional[datetime.date] = None
    prices_max_date: Optional[datetime.date] = None
    prices_sum_volume: Optional[int] = None
    prices_sum_traded_value: Optional[Decimal] = None
    prices_sum_close: Optional[Decimal] = None
    prices_null_turnover_count: int = 0
    instruments_count: int = 0
    instruments_hash: Optional[str] = None
    symbol_history_count: int = 0
    symbol_history_hash: Optional[str] = None
    quarantine_records_count: int = 0
    quarantine_hash: Optional[str] = None
    calendar_trading_days_count: int = 0
    calendar_min_date: Optional[datetime.date] = None
    calendar_max_date: Optional[datetime.date] = None
    ingestion_runs_count: int = 0
    ingestion_archive_hashes_digest: Optional[str] = None
    manifest_fingerprint: str

    def canonical_dict(self) -> Dict[str, Any]:
        def _ser(v: Any) -> Any:
            if isinstance(v, Decimal):
                return f"{v:f}"
            if isinstance(v, (datetime.date, datetime.datetime)):
                return v.isoformat()
            return v

        return {
            "calendar_max_date": _ser(self.calendar_max_date),
            "calendar_min_date": _ser(self.calendar_min_date),
            "calendar_trading_days_count": self.calendar_trading_days_count,
            "ingestion_archive_hashes_digest": self.ingestion_archive_hashes_digest,
            "ingestion_runs_count": self.ingestion_runs_count,
            "instruments_count": self.instruments_count,
            "instruments_hash": self.instruments_hash,
            "prices_max_date": _ser(self.prices_max_date),
            "prices_min_date": _ser(self.prices_min_date),
            "prices_null_turnover_count": self.prices_null_turnover_count,
            "prices_row_count": self.prices_row_count,
            "prices_sum_close": _ser(self.prices_sum_close),
            "prices_sum_traded_value": _ser(self.prices_sum_traded_value),
            "prices_sum_volume": self.prices_sum_volume,
            "quarantine_hash": self.quarantine_hash,
            "quarantine_records_count": self.quarantine_records_count,
            "symbol_history_count": self.symbol_history_count,
            "symbol_history_hash": self.symbol_history_hash,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))


def compute_raw_data_manifest(session: Session) -> RawDataManifest:
    """
    Scans the database and computes a verifiable cryptographic manifest of all raw data.
    Any modification to a traded value, close price, volume, instrument, symbol history,
    calendar day, or archive hash alters the manifest_fingerprint.
    """
    bind = session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Daily Prices Raw
    p_row = session.execute(text("""
        SELECT
            count(*) as count,
            min(trade_date) as min_date,
            max(trade_date) as max_date,
            sum(volume) as total_volume,
            sum(traded_value) as total_value,
            count(*) FILTER (WHERE traded_value IS NULL) as null_value_count,
            sum(close) as sum_close
        FROM daily_prices_raw
    """)).mappings().one()

    p_count = int(p_row["count"] or 0)
    p_min_date = p_row["min_date"]
    if isinstance(p_min_date, str):
        p_min_date = datetime.date.fromisoformat(p_min_date)
    p_max_date = p_row["max_date"]
    if isinstance(p_max_date, str):
        p_max_date = datetime.date.fromisoformat(p_max_date)
    p_vol = int(p_row["total_volume"] or 0) if p_count > 0 else 0
    p_val = Decimal(str(p_row["total_value"])) if p_row["total_value"] is not None else None
    p_close = Decimal(str(p_row["sum_close"])) if p_row["sum_close"] is not None else None
    p_null_cnt = int(p_row["null_value_count"] or 0)

    # 2. Instruments
    if is_postgres:
        inst_row = session.execute(text("""
            SELECT
                count(*) as count,
                md5(string_agg(concat_ws(':', instrument_id, status, coalesce(first_observed_trade_date::text, 'N'), coalesce(listing_date::text, 'N')), ';' ORDER BY instrument_id)) as hash
            FROM instruments
        """)).mappings().one()
        inst_count = int(inst_row["count"] or 0)
        inst_hash = inst_row["hash"]
    else:
        inst_rows = session.execute(text("SELECT instrument_id, status, first_observed_trade_date, listing_date FROM instruments ORDER BY instrument_id")).mappings().all()
        inst_count = len(inst_rows)
        inst_content = ";".join(f"{r['instrument_id']}:{r['status']}:{r['first_observed_trade_date']}:{r['listing_date']}" for r in inst_rows)
        inst_hash = hashlib.md5(inst_content.encode("utf-8")).hexdigest() if inst_rows else None

    # 3. Instrument Symbol History
    if is_postgres:
        sym_row = session.execute(text("""
            SELECT
                count(*) as count,
                md5(string_agg(concat_ws(':', instrument_id, symbol, series, isin, valid_from::text, coalesce(valid_to::text, 'N')), ';' ORDER BY instrument_id, valid_from, series)) as hash
            FROM instrument_symbol_history
        """)).mappings().one()
        sym_count = int(sym_row["count"] or 0)
        sym_hash = sym_row["hash"]
    else:
        sym_rows = session.execute(text("SELECT instrument_id, symbol, series, isin, valid_from, valid_to FROM instrument_symbol_history ORDER BY instrument_id, valid_from, series")).mappings().all()
        sym_count = len(sym_rows)
        sym_content = ";".join(f"{r['instrument_id']}:{r['symbol']}:{r['series']}:{r['isin']}:{r['valid_from']}:{r['valid_to']}" for r in sym_rows)
        sym_hash = hashlib.md5(sym_content.encode("utf-8")).hexdigest() if sym_rows else None

    # 4. Quarantine Records
    if is_postgres:
        q_row = session.execute(text("""
            SELECT
                count(*) as count,
                md5(string_agg(concat_ws(':', coalesce(instrument_id, 'N'), trade_date::text, validation_rule, validation_message), ';' ORDER BY id)) as hash
            FROM daily_price_quarantine
        """)).mappings().one()
        q_count = int(q_row["count"] or 0)
        q_hash = q_row["hash"]
    else:
        q_rows = session.execute(text("SELECT instrument_id, trade_date, validation_rule, validation_message FROM daily_price_quarantine ORDER BY id")).mappings().all()
        q_count = len(q_rows)
        q_content = ";".join(f"{r['instrument_id']}:{r['trade_date']}:{r['validation_rule']}:{r['validation_message']}" for r in q_rows)
        q_hash = hashlib.md5(q_content.encode("utf-8")).hexdigest() if q_rows else None

    # 5. Trading Calendar
    cal_row = session.execute(text("""
        SELECT
            count(*) as count,
            min(trade_date) as min_date,
            max(trade_date) as max_date
        FROM trading_calendar
        WHERE is_trading_day = true
    """)).mappings().one()
    cal_count = int(cal_row["count"] or 0)
    cal_min = cal_row["min_date"]
    if isinstance(cal_min, str):
        cal_min = datetime.date.fromisoformat(cal_min)
    cal_max = cal_row["max_date"]
    if isinstance(cal_max, str):
        cal_max = datetime.date.fromisoformat(cal_max)

    # 6. Ingestion Runs & Archive Hashes
    if is_postgres:
        run_row = session.execute(text("""
            SELECT
                count(*) as count,
                md5(string_agg(file_hash, ',' ORDER BY file_hash)) as hash
            FROM ingestion_runs
        """)).mappings().one()
        run_count = int(run_row["count"] or 0)
        run_hash = run_row["hash"]
    else:
        run_rows = session.execute(text("SELECT file_hash FROM ingestion_runs ORDER BY file_hash")).mappings().all()
        run_count = len(run_rows)
        run_content = ",".join(str(r["file_hash"]) for r in run_rows)
        run_hash = hashlib.md5(run_content.encode("utf-8")).hexdigest() if run_rows else None

    # Build intermediate dictionary to compute overall SHA-256 fingerprint
    intermediate = {
        "calendar_max_date": cal_max.isoformat() if cal_max else None,
        "calendar_min_date": cal_min.isoformat() if cal_min else None,
        "calendar_trading_days_count": cal_count,
        "ingestion_archive_hashes_digest": run_hash,
        "ingestion_runs_count": run_count,
        "instruments_count": inst_count,
        "instruments_hash": inst_hash,
        "prices_max_date": p_max_date.isoformat() if p_max_date else None,
        "prices_min_date": p_min_date.isoformat() if p_min_date else None,
        "prices_null_turnover_count": p_null_cnt,
        "prices_row_count": p_count,
        "prices_sum_close": f"{p_close:f}" if p_close is not None else None,
        "prices_sum_traded_value": f"{p_val:f}" if p_val is not None else None,
        "prices_sum_volume": p_vol,
        "quarantine_hash": q_hash,
        "quarantine_records_count": q_count,
        "symbol_history_count": sym_count,
        "symbol_history_hash": sym_hash,
    }
    canonical_bytes = json.dumps(intermediate, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest_fingerprint = hashlib.sha256(canonical_bytes).hexdigest()

    return RawDataManifest(
        prices_row_count=p_count,
        prices_min_date=p_min_date,
        prices_max_date=p_max_date,
        prices_sum_volume=p_vol,
        prices_sum_traded_value=p_val,
        prices_sum_close=p_close,
        prices_null_turnover_count=p_null_cnt,
        instruments_count=inst_count,
        instruments_hash=inst_hash,
        symbol_history_count=sym_count,
        symbol_history_hash=sym_hash,
        quarantine_records_count=q_count,
        quarantine_hash=q_hash,
        calendar_trading_days_count=cal_count,
        calendar_min_date=cal_min,
        calendar_max_date=cal_max,
        ingestion_runs_count=run_count,
        ingestion_archive_hashes_digest=run_hash,
        manifest_fingerprint=manifest_fingerprint,
    )
