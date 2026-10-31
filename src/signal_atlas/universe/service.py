import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from sqlalchemy import delete, desc, func, select, text
from sqlalchemy.orm import Session

from signal_atlas.db.models.calendar import TradingCalendar
from signal_atlas.db.models.instruments import Instrument, InstrumentSymbolHistory
from signal_atlas.db.models.prices import DailyPriceRaw
from signal_atlas.db.models.universe import UniverseMemberRecord, UniverseSnapshotRecord
from signal_atlas.db.session import get_db
from signal_atlas.quality.adjustment import AdjustedPriceRecord, get_point_in_time_adjusted_history
from signal_atlas.quality.bulk_adjustment import get_quarantined_unresolved_instruments
from signal_atlas.universe.models import (
    EligibilityReason,
    UniverseConfig,
    UniverseMember,
    UniverseSnapshot,
)
from signal_atlas.universe.policy import evaluate_instrument_eligibility


class PointInTimeUniverseService:
    """
    Deterministic Point-in-Time Liquidity Universe Service for NSE cash equities.
    Evaluates securities strictly based on information available on or before as_of_date.
    Zero future leakage, zero survivorship bias.
    """

    def __init__(self, db: Optional[Session] = None):
        self._external_db = db

    def get_completed_trading_sessions(
        self,
        as_of_date: datetime.date,
        lookback_sessions: int,
        session: Session,
    ) -> List[datetime.date]:
        """
        Retrieves the exact trailing N completed market trading sessions
        from the trading calendar up to and including as_of_date.
        Excludes weekends and declared exchange holidays.
        """
        query = (
            select(TradingCalendar.trade_date)
            .where(
                TradingCalendar.is_trading_day == True,
                TradingCalendar.trade_date <= as_of_date,
            )
            .order_by(TradingCalendar.trade_date.desc())
            .limit(lookback_sessions)
        )
        dates = session.execute(query).scalars().all()
        # Return in ascending chronological order
        return sorted(dates)

    def build_universe(
        self,
        as_of_date: datetime.date,
        config: Optional[UniverseConfig] = None,
        persist: bool = True,
        session: Optional[Session] = None,
    ) -> UniverseSnapshot:
        """
        Computes the complete, deterministic Point-in-Time Universe for as_of_date.
        """
        cfg = config or UniverseConfig()
        db_cm = get_db(session or self._external_db)

        with db_cm as db:
            # 1. Determine exact trading session window
            sessions = self.get_completed_trading_sessions(as_of_date, cfg.lookback_sessions, db)
            if not sessions:
                raise ValueError(f"No completed trading sessions found on or before {as_of_date}")

            actual_lookback_count = len(sessions)
            start_date = sessions[0]
            end_date = sessions[-1]

            # 2. Identify quarantined instruments
            quarantined = get_quarantined_unresolved_instruments(db)
            quarantined_ids = set(quarantined.keys())

            # 3. Resolve Point-in-Time Symbol and ISIN for all instruments
            # An instrument's symbol/ISIN as of as_of_date is resolved through instrument_symbol_history
            sym_sql = text("""
                SELECT
                    instrument_id, symbol, isin, series, valid_from, valid_to
                FROM instrument_symbol_history
                WHERE valid_from <= :as_of_date
                  AND (valid_to IS NULL OR valid_to >= :as_of_date)
                ORDER BY instrument_id, valid_from DESC
            """)
            sym_rows = db.execute(sym_sql, {"as_of_date": as_of_date}).mappings().all()
            sym_by_inst: Dict[str, List[Dict[str, Any]]] = {}
            for r in sym_rows:
                sym_by_inst.setdefault(r["instrument_id"], []).append(dict(r))

            # Also load instrument master metadata (listing_date, first_observed_trade_date, delisting_date)
            inst_sql = text("""
                SELECT instrument_id, listing_date, first_observed_trade_date, delisting_date, status
                FROM instruments
            """)
            inst_rows = db.execute(inst_sql).mappings().all()
            inst_meta: Dict[str, Dict[str, Any]] = {
                r["instrument_id"]: dict(r) for r in inst_rows
            }

            # 4. Aggregate Trailing Traded Value and Observation Counts in Lookback Window
            # Permitted series check in the raw trade data query
            series_list = list(cfg.permitted_series)
            if cfg.include_sme and "SM" not in series_list:
                series_list.append("SM")

            agg_sql = text("""
                WITH stats AS (
                    SELECT
                        instrument_id,
                        count(DISTINCT trade_date) as observed_sessions,
                        sum(traded_value) as total_turnover,
                        count(traded_value) as valid_turnover_sessions,
                        count(*) FILTER (WHERE traded_value IS NULL) as null_turnover_count,
                        count(*) FILTER (WHERE traded_value = 0) as zero_turnover_count,
                        count(*) FILTER (WHERE traded_value > 0) as positive_turnover_count,
                        percentile_cont(0.5) WITHIN GROUP (ORDER BY traded_value) as median_turnover
                    FROM daily_prices_raw
                    WHERE trade_date >= :start_date AND trade_date <= :end_date
                      AND series = ANY(:series_list)
                    GROUP BY instrument_id
                ),
                latest_prices AS (
                    SELECT DISTINCT ON (instrument_id)
                        instrument_id,
                        close as latest_raw_close,
                        trade_date as latest_observed_date,
                        series as latest_series
                    FROM daily_prices_raw
                    WHERE trade_date >= :start_date AND trade_date <= :end_date
                      AND series = ANY(:series_list)
                    ORDER BY instrument_id, trade_date DESC
                )
                SELECT
                    s.*,
                    lp.latest_raw_close,
                    lp.latest_observed_date,
                    lp.latest_series
                FROM stats s
                JOIN latest_prices lp ON s.instrument_id = lp.instrument_id
            """)
            trade_rows = db.execute(
                agg_sql,
                {
                    "start_date": start_date,
                    "end_date": end_date,
                    "series_list": series_list,
                },
            ).mappings().all()

            trade_stats: Dict[str, Dict[str, Any]] = {
                r["instrument_id"]: dict(r) for r in trade_rows
            }

            # Resolve PIT identity deterministically backed by trade evidence or latest valid_from
            pit_symbols: Dict[str, Dict[str, Any]] = {}
            ambiguous_instruments: Set[str] = set()

            for iid, records in sym_by_inst.items():
                if len(records) == 1:
                    pit_symbols[iid] = records[0]
                else:
                    # Multiple valid records exist on as_of_date (e.g. overlapping EQ and BE intervals).
                    # Check exchange trade evidence from the lookback window.
                    t_info = trade_stats.get(iid)
                    chosen = None
                    if t_info and t_info.get("latest_series"):
                        # Match with the actual traded series on the exchange
                        for rec in records:
                            if rec["series"] == t_info["latest_series"]:
                                chosen = rec
                                break

                    if chosen is None:
                        # Fallback to the most recent effective valid_from date
                        max_vf = records[0]["valid_from"]
                        top_records = [r for r in records if r["valid_from"] == max_vf]
                        if len(top_records) == 1:
                            chosen = top_records[0]
                        else:
                            # Conflicting records with identical valid_from and no trading evidence
                            ambiguous_instruments.add(iid)
                            chosen = top_records[0]

                    pit_symbols[iid] = chosen

            # 5. Evaluate All Available Instruments
            evaluated_members: List[UniverseMember] = []
            all_candidate_ids = set(pit_symbols.keys()) | set(trade_stats.keys())

            for iid in sorted(all_candidate_ids):
                sym_info = pit_symbols.get(iid)
                t_info = trade_stats.get(iid)
                meta = inst_meta.get(iid, {})

                if sym_info:
                    symbol = sym_info["symbol"]
                    isin = sym_info["isin"]
                    series = sym_info["series"]
                elif t_info:
                    symbol = t_info["latest_series"]
                    isin = ""
                    series = t_info["latest_series"]
                else:
                    continue

                listing_date = meta.get("listing_date")
                first_observed_date = meta.get("first_observed_trade_date")
                delisting_date = meta.get("delisting_date")

                if t_info:
                    obs_count = t_info["observed_sessions"]
                    missing_count = max(0, actual_lookback_count - obs_count)
                    completeness = min(
                        Decimal("1.0000"),
                        (Decimal(obs_count) / Decimal(actual_lookback_count)).quantize(Decimal("0.0001"))
                    )
                    tot_turnover = (
                        Decimal(str(t_info["total_turnover"]))
                        if t_info["total_turnover"] is not None
                        else None
                    )
                    valid_sessions = t_info["valid_turnover_sessions"]
                    turnover_completeness = min(
                        Decimal("1.0000"),
                        (Decimal(valid_sessions) / Decimal(actual_lookback_count)).quantize(Decimal("0.0001"))
                    )
                    # Average Daily Traded Value = total valid turnover / observed valid sessions
                    if tot_turnover is not None and valid_sessions > 0:
                        adtv = (tot_turnover / Decimal(valid_sessions)).quantize(
                            Decimal("0.01")
                        )
                    else:
                        adtv = None

                    median_turnover = (
                        Decimal(str(t_info["median_turnover"])).quantize(Decimal("0.01"))
                        if t_info["median_turnover"] is not None
                        else None
                    )
                    null_cnt = t_info["null_turnover_count"]
                    zero_cnt = t_info["zero_turnover_count"]
                    pos_cnt = t_info["positive_turnover_count"]
                    latest_close = (
                        Decimal(str(t_info["latest_raw_close"])).quantize(Decimal("0.01"))
                        if t_info["latest_raw_close"] is not None
                        else None
                    )
                else:
                    obs_count = 0
                    missing_count = actual_lookback_count
                    completeness = Decimal("0.0000")
                    valid_sessions = 0
                    turnover_completeness = Decimal("0.0000")
                    tot_turnover = None
                    adtv = None
                    median_turnover = None
                    null_cnt = 0
                    zero_cnt = 0
                    pos_cnt = 0
                    latest_close = None

                if iid in ambiguous_instruments:
                    is_elig = False
                    reason = EligibilityReason.EXCLUDED_AMBIGUOUS_SERIES_HISTORY
                    detail = "Multiple conflicting series records valid on as-of date cannot be resolved unambiguously"
                else:
                    is_elig, reason, detail = evaluate_instrument_eligibility(
                        instrument_id=iid,
                        symbol=symbol,
                        isin=isin,
                        series=series,
                        observed_sessions_count=obs_count,
                        lookback_sessions=actual_lookback_count,
                        average_daily_turnover=adtv,
                        median_daily_turnover=median_turnover,
                        latest_raw_close=latest_close,
                        as_of_date=as_of_date,
                        listing_date=listing_date,
                        delisting_date=delisting_date,
                        quarantined_instrument_ids=quarantined_ids,
                        config=cfg,
                        first_observed_trade_date=first_observed_date,
                        valid_turnover_sessions_count=valid_sessions,
                    )

                member = UniverseMember(
                    instrument_id=iid,
                    symbol=symbol,
                    isin=isin,
                    series=series,
                    observed_sessions_count=obs_count,
                    missing_sessions_count=missing_count,
                    trading_completeness=completeness,
                    expected_lookback_sessions=actual_lookback_count,
                    valid_turnover_sessions_count=valid_sessions,
                    turnover_data_completeness=turnover_completeness,
                    total_turnover=tot_turnover,
                    average_daily_turnover=adtv,
                    median_daily_turnover=median_turnover,
                    null_turnover_count=null_cnt,
                    zero_turnover_count=zero_cnt,
                    positive_turnover_count=pos_cnt,
                    latest_raw_close=latest_close,
                    is_eligible=is_elig,
                    exclusion_reason=reason if not is_elig else None,
                    exclusion_detail=detail if not is_elig else None,
                )
                evaluated_members.append(member)

            # 6. Rank Eligible Members by ADTV (Descending) & Apply Optional Top-N Cutoff
            eligible_candidates = [m for m in evaluated_members if m.is_eligible]
            excluded_candidates = [m for m in evaluated_members if not m.is_eligible]

            # Sort eligible candidates deterministically by ADTV desc, then symbol asc
            eligible_candidates.sort(
                key=lambda m: (m.average_daily_turnover or Decimal("0"), m.symbol),
                reverse=True,
            )

            final_eligible: List[UniverseMember] = []
            for rank_idx, m in enumerate(eligible_candidates, start=1):
                if cfg.top_n is not None and rank_idx > cfg.top_n:
                    m.is_eligible = False
                    m.exclusion_reason = EligibilityReason.EXCLUDED_RANK_CUTOFF
                    m.exclusion_detail = f"Rank {rank_idx} exceeds top_n cap of {cfg.top_n}"
                    m.rank = None
                    excluded_candidates.append(m)
                else:
                    m.rank = rank_idx
                    final_eligible.append(m)

            # Deterministic snapshot ID
            snap_id = f"SNAP-{as_of_date.isoformat()}-{cfg.config_identifier}"

            snapshot = UniverseSnapshot(
                snapshot_id=snap_id,
                as_of_date=as_of_date,
                lookback_sessions=actual_lookback_count,
                lookback_start_date=start_date,
                lookback_end_date=end_date,
                config=cfg,
                config_identifier=cfg.config_identifier,
                adjustment_version=cfg.adjustment_version,
                raw_data_version=cfg.raw_data_version,
                data_coverage_start=cfg.data_coverage_start,
                data_coverage_end=cfg.data_coverage_end,
                code_revision=cfg.code_revision,
                total_instruments_evaluated=len(evaluated_members),
                eligible_count=len(final_eligible),
                excluded_count=len(excluded_candidates),
                eligible_members=final_eligible,
                excluded_members=excluded_candidates,
            )

            # 7. Persist Snapshot to Database if requested
            if persist:
                self._persist_snapshot_record(snapshot, db)

            return snapshot

    def _persist_snapshot_record(self, snapshot: UniverseSnapshot, session: Session) -> None:
        """
        Stores snapshot and member records in PostgreSQL with transactional idempotency.
        Enforces raw_data_version check to prevent silent overwrites across differing data versions.
        """
        existing = session.execute(
            select(UniverseSnapshotRecord).where(
                UniverseSnapshotRecord.as_of_date == snapshot.as_of_date,
                UniverseSnapshotRecord.config_identifier == snapshot.config_identifier,
                UniverseSnapshotRecord.adjustment_version == snapshot.adjustment_version,
            )
        ).scalars().first()

        if existing is not None:
            if existing.raw_data_version != snapshot.raw_data_version:
                raise ValueError(
                    f"Cannot overwrite snapshot for date {snapshot.as_of_date} and config {snapshot.config_identifier}: "
                    f"existing raw_data_version='{existing.raw_data_version}' differs from "
                    f"new raw_data_version='{snapshot.raw_data_version}'."
                )
            session.delete(existing)
            session.flush()

        cfg = snapshot.config
        snap_rec = UniverseSnapshotRecord(
            snapshot_id=snapshot.snapshot_id,
            as_of_date=snapshot.as_of_date,
            config_version=cfg.config_version,
            config_identifier=snapshot.config_identifier,
            lookback_sessions=snapshot.lookback_sessions,
            lookback_start_date=snapshot.lookback_start_date,
            lookback_end_date=snapshot.lookback_end_date,
            min_adtv=cfg.min_adtv,
            min_trading_completeness=cfg.min_trading_completeness,
            min_price=cfg.min_price,
            permitted_series=",".join(cfg.permitted_series),
            adjustment_version=snapshot.adjustment_version,
            raw_data_version=snapshot.raw_data_version,
            data_coverage_start=snapshot.data_coverage_start,
            data_coverage_end=snapshot.data_coverage_end,
            code_revision=snapshot.code_revision,
            total_instruments_evaluated=snapshot.total_instruments_evaluated,
            eligible_count=snapshot.eligible_count,
            excluded_count=snapshot.excluded_count,
        )
        session.add(snap_rec)

        all_members = snapshot.eligible_members + snapshot.excluded_members
        member_records = [
            UniverseMemberRecord(
                snapshot_id=snapshot.snapshot_id,
                instrument_id=m.instrument_id,
                symbol=m.symbol,
                isin=m.isin,
                series=m.series,
                observed_sessions_count=m.observed_sessions_count,
                missing_sessions_count=m.missing_sessions_count,
                trading_completeness=m.trading_completeness,
                expected_lookback_sessions=m.expected_lookback_sessions,
                valid_turnover_sessions_count=m.valid_turnover_sessions_count,
                turnover_data_completeness=m.turnover_data_completeness,
                total_turnover=m.total_turnover,
                average_daily_turnover=m.average_daily_turnover,
                median_daily_turnover=m.median_daily_turnover,
                null_turnover_count=m.null_turnover_count,
                zero_turnover_count=m.zero_turnover_count,
                positive_turnover_count=m.positive_turnover_count,
                latest_raw_close=m.latest_raw_close,
                is_eligible=m.is_eligible,
                rank=m.rank,
                exclusion_reason=m.exclusion_reason.value if m.exclusion_reason else None,
                exclusion_detail=m.exclusion_detail,
            )
            for m in all_members
        ]
        session.add_all(member_records)
        session.commit()

    def get_universe(
        self,
        as_of_date: datetime.date,
        config: Optional[UniverseConfig] = None,
        session: Optional[Session] = None,
    ) -> UniverseSnapshot:
        """
        Loads an existing universe snapshot from PostgreSQL if present,
        or dynamically computes and persists it.
        """
        cfg = config or UniverseConfig()
        db_cm = get_db(session or self._external_db)

        with db_cm as db:
            snap_rec = db.execute(
                select(UniverseSnapshotRecord).where(
                    UniverseSnapshotRecord.as_of_date == as_of_date,
                    UniverseSnapshotRecord.config_identifier == cfg.config_identifier,
                    UniverseSnapshotRecord.adjustment_version == cfg.adjustment_version,
                    UniverseSnapshotRecord.raw_data_version == cfg.raw_data_version,
                )
            ).scalars().first()

            if snap_rec is not None:
                members_recs = db.execute(
                    select(UniverseMemberRecord)
                    .where(UniverseMemberRecord.snapshot_id == snap_rec.snapshot_id)
                    .order_by(UniverseMemberRecord.rank.nullslast(), UniverseMemberRecord.symbol)
                ).scalars().all()

                eligible_members = []
                excluded_members = []
                for mr in members_recs:
                    mem = UniverseMember(
                        instrument_id=mr.instrument_id,
                        symbol=mr.symbol,
                        isin=mr.isin,
                        series=mr.series,
                        observed_sessions_count=mr.observed_sessions_count,
                        missing_sessions_count=mr.missing_sessions_count,
                        trading_completeness=Decimal(str(mr.trading_completeness)),
                        expected_lookback_sessions=mr.expected_lookback_sessions,
                        valid_turnover_sessions_count=mr.valid_turnover_sessions_count,
                        turnover_data_completeness=Decimal(str(mr.turnover_data_completeness)),
                        total_turnover=Decimal(str(mr.total_turnover)) if mr.total_turnover is not None else None,
                        average_daily_turnover=Decimal(str(mr.average_daily_turnover)) if mr.average_daily_turnover is not None else None,
                        median_daily_turnover=Decimal(str(mr.median_daily_turnover)) if mr.median_daily_turnover is not None else None,
                        null_turnover_count=mr.null_turnover_count,
                        zero_turnover_count=mr.zero_turnover_count,
                        positive_turnover_count=mr.positive_turnover_count,
                        latest_raw_close=Decimal(str(mr.latest_raw_close)) if mr.latest_raw_close is not None else None,
                        is_eligible=mr.is_eligible,
                        rank=mr.rank,
                        exclusion_reason=EligibilityReason(mr.exclusion_reason) if mr.exclusion_reason else None,
                        exclusion_detail=mr.exclusion_detail,
                    )
                    if mr.is_eligible:
                        eligible_members.append(mem)
                    else:
                        excluded_members.append(mem)

                return UniverseSnapshot(
                    snapshot_id=snap_rec.snapshot_id,
                    as_of_date=snap_rec.as_of_date,
                    lookback_sessions=snap_rec.lookback_sessions,
                    lookback_start_date=snap_rec.lookback_start_date,
                    lookback_end_date=snap_rec.lookback_end_date,
                    config=cfg,
                    config_identifier=snap_rec.config_identifier,
                    adjustment_version=snap_rec.adjustment_version,
                    raw_data_version=snap_rec.raw_data_version,
                    data_coverage_start=snap_rec.data_coverage_start,
                    data_coverage_end=snap_rec.data_coverage_end,
                    code_revision=snap_rec.code_revision,
                    total_instruments_evaluated=snap_rec.total_instruments_evaluated,
                    eligible_count=snap_rec.eligible_count,
                    excluded_count=snap_rec.excluded_count,
                    eligible_members=eligible_members,
                    excluded_members=excluded_members,
                )

            # If not yet persisted, compute and persist
            return self.build_universe(as_of_date, config=cfg, persist=True, session=db)

    def get_universe_adjusted_prices(
        self,
        instrument_id: str,
        as_of_date: datetime.date,
        series: str = "EQ",
        session: Optional[Session] = None,
    ) -> List[AdjustedPriceRecord]:
        """
        Retrieves dynamically adjusted historical price records for an instrument
        using candidate dataset version v1.4, strictly bounded by as_of_date.
        Corporate actions with ex_date > as_of_date are strictly excluded.
        """
        db_cm = get_db(session or self._external_db)
        with db_cm as db:
            return get_point_in_time_adjusted_history(
                instrument_id=instrument_id,
                as_of_date=as_of_date,
                series=series,
                adjustment_version="v1.4",
                db=db,
            )

    @staticmethod
    def export_snapshot_checkpoint(
        snapshot: UniverseSnapshot,
        output_dir: Path = Path("data/checkpoints/universe"),
    ) -> Tuple[Path, Path]:
        """
        Exports universe snapshot to JSON and CSV checkpoints for offline review and audit.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"universe_{snapshot.as_of_date.isoformat()}_{snapshot.config.config_identifier}.json"
        csv_path = output_dir / f"universe_{snapshot.as_of_date.isoformat()}_{snapshot.config.config_identifier}.csv"

        # 1. JSON Export
        snapshot_dict = {
            "snapshot_id": snapshot.snapshot_id,
            "as_of_date": snapshot.as_of_date.isoformat(),
            "lookback_sessions": snapshot.lookback_sessions,
            "lookback_start_date": snapshot.lookback_start_date.isoformat(),
            "lookback_end_date": snapshot.lookback_end_date.isoformat(),
            "config_identifier": snapshot.config_identifier,
            "adjustment_version": snapshot.adjustment_version,
            "total_instruments_evaluated": snapshot.total_instruments_evaluated,
            "eligible_count": snapshot.eligible_count,
            "excluded_count": snapshot.excluded_count,
            "eligible_members": [
                {
                    "rank": m.rank,
                    "instrument_id": m.instrument_id,
                    "symbol": m.symbol,
                    "isin": m.isin,
                    "series": m.series,
                    "average_daily_turnover": float(m.average_daily_turnover) if m.average_daily_turnover else None,
                    "median_daily_turnover": float(m.median_daily_turnover) if m.median_daily_turnover else None,
                    "observed_sessions_count": m.observed_sessions_count,
                    "trading_completeness": float(m.trading_completeness),
                    "latest_raw_close": float(m.latest_raw_close) if m.latest_raw_close else None,
                }
                for m in snapshot.eligible_members
            ],
            "sample_excluded_members": [
                {
                    "instrument_id": m.instrument_id,
                    "symbol": m.symbol,
                    "isin": m.isin,
                    "series": m.series,
                    "exclusion_reason": m.exclusion_reason.value if m.exclusion_reason else None,
                    "exclusion_detail": m.exclusion_detail,
                    "average_daily_turnover": float(m.average_daily_turnover) if m.average_daily_turnover else None,
                    "observed_sessions_count": m.observed_sessions_count,
                }
                for m in snapshot.excluded_members[:50]
            ],
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(snapshot_dict, f, indent=2)

        # 2. CSV Export of Eligible Members
        import csv

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "rank",
                "instrument_id",
                "symbol",
                "isin",
                "series",
                "average_daily_turnover",
                "median_daily_turnover",
                "observed_sessions",
                "lookback_sessions",
                "trading_completeness",
                "latest_raw_close",
                "null_turnover_count",
                "zero_turnover_count",
                "positive_turnover_count",
            ])
            for m in snapshot.eligible_members:
                writer.writerow([
                    m.rank,
                    m.instrument_id,
                    m.symbol,
                    m.isin,
                    m.series,
                    f"{m.average_daily_turnover:.2f}" if m.average_daily_turnover else "",
                    f"{m.median_daily_turnover:.2f}" if m.median_daily_turnover else "",
                    m.observed_sessions_count,
                    snapshot.lookback_sessions,
                    f"{m.trading_completeness:.4f}",
                    f"{m.latest_raw_close:.2f}" if m.latest_raw_close else "",
                    m.null_turnover_count,
                    m.zero_turnover_count,
                    m.positive_turnover_count,
                ])

        return json_path, csv_path


def get_point_in_time_universe(
    as_of_date: datetime.date,
    config: Optional[UniverseConfig] = None,
    db: Optional[Session] = None,
    persist: bool = True,
) -> UniverseSnapshot:
    """Convenience functional interface to PointInTimeUniverseService."""
    service = PointInTimeUniverseService(db=db)
    if persist:
        return service.get_universe(as_of_date, config=config)
    else:
        return service.build_universe(as_of_date, config=config, persist=False)
