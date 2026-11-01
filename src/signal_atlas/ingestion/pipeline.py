import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional, Set
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from signal_atlas.config import settings
from signal_atlas.db.models import (
    DailyPriceQuarantine,
    DailyPriceRaw,
    IngestionRun,
    Instrument,
    InstrumentSymbolHistory,
    TradingCalendar,
)
from signal_atlas.db.session import get_db
from signal_atlas.ingestion.archiver import RawArchiver
from signal_atlas.ingestion.normalizer import NormalizedRecord, RecordNormalizer
from signal_atlas.providers.nse.calendar import (
    NSETradingCalendar,
    SPECIAL_WEEKEND_SESSIONS,
)
from signal_atlas.providers.nse.downloader import (
    ConfirmedHolidayError,
    DownloaderError,
    ExpectedDataMissingError,
    NonTradingDayError,
    NSEDownloader,
)
from signal_atlas.providers.nse.legacy_parser import (
    LEGACY_PARSER_VERSION,
    LegacyBhavcopyParser,
)
from signal_atlas.providers.nse.udiff_parser import (
    PARSER_VERSION as UDIFF_PARSER_VERSION,
    UDiFFParser,
)
from signal_atlas.quality.validation import BatchValidator, ValidationResult

logger = logging.getLogger(__name__)

UDIFF_TRANSITION_DATE = datetime.date(2024, 7, 8)


class PipelineError(Exception):
    pass


class IngestionPipeline:
    """
    Production ingestion pipeline for NSE Bhavcopy files (Legacy and CM-UDiFF):
    1. Idempotency checking & authoritative trading calendar verification
    2. File download with caching, weekend detection, and HTML guards
    3. Non-destructive bit-level raw archiving & SHA-256 conflict preservation
    4. Format-specific archive extraction and parsing (Legacy vs UDiFF)
    5. Financial Decimal normalization
    6. Batch validation & quarantine
    7. Atomic database persistence of reference instruments and raw prices
    """

    def __init__(
        self,
        downloader: Optional[NSEDownloader] = None,
        archiver: Optional[RawArchiver] = None,
        udiff_parser: Optional[UDiFFParser] = None,
        legacy_parser: Optional[LegacyBhavcopyParser] = None,
        normalizer: Optional[RecordNormalizer] = None,
        validator: Optional[BatchValidator] = None,
    ):
        self.downloader = downloader or NSEDownloader()
        self.archiver = archiver or RawArchiver()
        self.udiff_parser = udiff_parser or UDiFFParser()
        self.legacy_parser = legacy_parser or LegacyBhavcopyParser()
        self.normalizer = normalizer or RecordNormalizer()
        self.validator = validator or BatchValidator()

    def ingest_date(
        self,
        trade_date: datetime.date,
        force: bool = False,
        session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        Run the end-to-end ingestion pipeline for trade_date.

        Args:
            trade_date: Target trading date.
            force: If True, re-ingests even if a successful run already exists.
            session: Optional SQLAlchemy session.

        Returns:
            Dictionary summary of ingestion execution.
        """
        logger.info("Starting ingestion pipeline for date: %s (force=%s)", trade_date, force)

        is_udiff = trade_date >= UDIFF_TRANSITION_DATE
        source = "NSE_CM_UDIFF" if is_udiff else "NSE_LEGACY"
        parser_version = UDIFF_PARSER_VERSION if is_udiff else LEGACY_PARSER_VERSION
        parser = self.udiff_parser if is_udiff else self.legacy_parser

        with get_db(session) as db:
            # 1. Idempotency check
            existing_run = db.execute(
                select(IngestionRun).where(
                    IngestionRun.trade_date == trade_date,
                    IngestionRun.status.in_(["SUCCESS", "QUARANTINED"]),
                )
            ).scalars().first()

            if existing_run and not force:
                logger.info("Date %s already ingested in run %s. Skipping.", trade_date, existing_run.run_id)
                return {
                    "status": "ALREADY_INGESTED",
                    "trade_date": str(trade_date),
                    "run_id": existing_run.run_id,
                    "file_name": existing_run.file_name,
                    "file_hash": existing_run.file_hash,
                    "row_count": existing_run.row_count,
                    "source": existing_run.source,
                    "message": "Date already ingested. Use --force to reprocess.",
                }

            # 2. Authoritative Holiday Check
            is_hol, hol_name = NSETradingCalendar.is_confirmed_holiday(trade_date)
            if is_hol and not force:
                logger.info("Date %s is a confirmed NSE holiday: %s", trade_date, hol_name)
                cal = db.get(TradingCalendar, trade_date)
                if not cal:
                    db.add(TradingCalendar(trade_date=trade_date, is_trading_day=False, holiday_name=hol_name))
                    db.flush()
                return {
                    "status": "CONFIRMED_HOLIDAY",
                    "trade_date": str(trade_date),
                    "message": f"Confirmed holiday: {hol_name}",
                    "row_count": 0,
                }

            # 3. Weekend Check (unless special live weekend session)
            if trade_date.weekday() >= 5 and trade_date not in SPECIAL_WEEKEND_SESSIONS and not force:
                day_name = trade_date.strftime("%A")
                cal = db.get(TradingCalendar, trade_date)
                if not cal:
                    db.add(TradingCalendar(trade_date=trade_date, is_trading_day=False, holiday_name="WEEKEND"))
                    db.flush()
                return {
                    "status": "NON_TRADING_DAY",
                    "trade_date": str(trade_date),
                    "message": f"Weekend ({day_name})",
                    "row_count": 0,
                }

            # 4. Download raw file
            try:
                filename, raw_bytes, source_url = self.downloader.download(trade_date)
            except ConfirmedHolidayError as e:
                logger.info("Confirmed holiday during download for %s: %s", trade_date, e)
                cal = db.get(TradingCalendar, trade_date)
                if not cal:
                    db.add(TradingCalendar(trade_date=trade_date, is_trading_day=False, holiday_name=str(e)))
                    db.flush()
                return {
                    "status": "CONFIRMED_HOLIDAY",
                    "trade_date": str(trade_date),
                    "message": str(e),
                    "row_count": 0,
                }
            except NonTradingDayError as e:
                logger.info("Non-trading day for %s: %s", trade_date, e)
                cal = db.get(TradingCalendar, trade_date)
                if not cal:
                    db.add(TradingCalendar(trade_date=trade_date, is_trading_day=False, holiday_name="WEEKEND"))
                    db.flush()
                return {
                    "status": "NON_TRADING_DAY",
                    "trade_date": str(trade_date),
                    "message": str(e),
                    "row_count": 0,
                }
            except ExpectedDataMissingError as e:
                # CRITICAL RULE: Weekday 404 does NOT automatically become a holiday.
                # Record as EXPECTED_DATA_MISSING so it remains eligible for retry.
                logger.warning("Expected trading session data missing for %s: %s", trade_date, e)
                missing_run = IngestionRun(
                    run_id=str(uuid.uuid4()),
                    source=source,
                    trade_date=trade_date,
                    file_name="N/A",
                    file_hash="N/A",
                    parser_version=parser_version,
                    status="EXPECTED_DATA_MISSING",
                    row_count=0,
                    validation_issues={"error": str(e)},
                )
                db.add(missing_run)
                db.flush()
                return {
                    "status": "EXPECTED_DATA_MISSING",
                    "trade_date": str(trade_date),
                    "message": str(e),
                    "row_count": 0,
                }
            except DownloaderError as e:
                logger.error("Download failed for %s: %s", trade_date, e)
                raise PipelineError(f"Download failed: {e}") from e

            # 5. Archive raw bytes and calculate SHA-256
            saved_path, file_hash = self.archiver.archive(
                filename=filename,
                content=raw_bytes,
                trade_date=trade_date,
            )
            logger.info("Raw archive saved to %s (SHA256=%s)", saved_path, file_hash)

            # 6. Parse archive
            try:
                raw_records = parser.parse_archive(raw_bytes)
            except Exception as e:
                logger.error("Parser failed for %s (%s): %s", filename, parser_version, e)
                fail_run = IngestionRun(
                    run_id=str(uuid.uuid4()),
                    source=source,
                    trade_date=trade_date,
                    file_name=filename,
                    file_hash=file_hash,
                    parser_version=parser_version,
                    status="FAILED",
                    row_count=0,
                    validation_issues={"error": str(e)},
                )
                db.add(fail_run)
                db.flush()
                raise PipelineError(f"Parse error: {e}") from e

            # 7. Normalize records
            normalized_records = self.normalizer.normalize_batch(raw_records)

            # 8. Validate batch
            valid_records, val_result = self.validator.validate_batch(
                records=normalized_records,
                expected_date=trade_date,
            )

            if val_result.is_fatal:
                fail_run = IngestionRun(
                    run_id=str(uuid.uuid4()),
                    source=source,
                    trade_date=trade_date,
                    file_name=filename,
                    file_hash=file_hash,
                    parser_version=parser_version,
                    status="FATAL",
                    row_count=0,
                    validation_issues=val_result.to_summary_dict(),
                )
                db.add(fail_run)
                db.flush()
                raise PipelineError(f"Fatal validation error: {val_result.fatal_error}")

            # 9. Atomic persistence
            if force and existing_run:
                logger.info("Force mode: clearing existing prices for date %s", trade_date)
                db.execute(delete(DailyPriceRaw).where(DailyPriceRaw.trade_date == trade_date))
                db.execute(delete(DailyPriceQuarantine).where(DailyPriceQuarantine.trade_date == trade_date))
                db.execute(delete(IngestionRun).where(IngestionRun.trade_date == trade_date))
                db.flush()

            run_id = str(uuid.uuid4())
            ingestion_run = IngestionRun(
                run_id=run_id,
                source=source,
                trade_date=trade_date,
                file_name=filename,
                file_hash=file_hash,
                parser_version=parser_version,
                status="QUARANTINED" if val_result.quarantine_count > 0 else "SUCCESS",
                row_count=len(valid_records),
                validation_issues=val_result.to_summary_dict(),
            )
            db.add(ingestion_run)
            db.flush()

            # Persist any quarantined records to dedicated quarantine table
            if val_result.quarantined_records:
                for q in val_result.quarantined_records:
                    q_entry = DailyPriceQuarantine(
                        trade_date=trade_date,
                        symbol=q.record.symbol,
                        series=q.record.series,
                        isin=q.record.isin,
                        row_number=q.row_number,
                        raw_payload=q.raw_payload or {},
                        validation_rule=q.rule,
                        validation_message=q.message,
                        source_file=filename,
                        source_file_hash=file_hash,
                        ingestion_run_id=run_id,
                    )
                    db.add(q_entry)
                db.flush()

            # Reference data resolution & upsert
            self._persist_instruments_and_prices(
                db=db,
                records=valid_records,
                run_id=run_id,
                trade_date=trade_date,
                source=source,
            )

            # Mark calendar as verified trading day
            cal_record = db.get(TradingCalendar, trade_date)
            if not cal_record:
                db.add(TradingCalendar(trade_date=trade_date, is_trading_day=True))
            else:
                cal_record.is_trading_day = True
                cal_record.holiday_name = None
            db.flush()

            logger.info(
                "Ingestion complete: %d records persisted (Run ID: %s, Status: %s, Source: %s)",
                len(valid_records),
                run_id,
                ingestion_run.status,
                source,
            )

            return {
                "status": ingestion_run.status,
                "trade_date": str(trade_date),
                "run_id": run_id,
                "file_name": filename,
                "file_hash": file_hash,
                "row_count": len(valid_records),
                "quarantine_count": val_result.quarantine_count,
                "warning_count": val_result.warning_count,
                "source": source,
                "saved_archive": str(saved_path),
            }

    def _persist_instruments_and_prices(
        self,
        db: Session,
        records: List[NormalizedRecord],
        run_id: str,
        trade_date: datetime.date,
        source: str = "NSE_CM_UDIFF",
    ) -> None:
        """
        Resolve instrument identities and persist raw price records.
        Preserves concurrent multi-series records (e.g. EQ and BL/BO) without collision.
        """
        isins = {r.isin for r in records if r.isin}
        symbols = {r.symbol for r in records if r.symbol}

        hist_stmt = select(InstrumentSymbolHistory).where(
            (InstrumentSymbolHistory.isin.in_(isins)) | (InstrumentSymbolHistory.symbol.in_(symbols))
        )
        existing_histories = db.execute(hist_stmt).scalars().all()

        isin_to_instrument_id: Dict[str, str] = {}
        symbol_series_to_inst_id: Dict[tuple, str] = {}
        existing_history_tuples = set()

        for h in existing_histories:
            isin_to_instrument_id[h.isin] = h.instrument_id
            symbol_series_to_inst_id[(h.symbol, h.series)] = h.instrument_id
            existing_history_tuples.add((h.instrument_id, h.symbol, h.series, h.isin))

        prices_to_insert: List[DailyPriceRaw] = []

        for rec in records:
            # Identity resolution:
            # 1. Exact ISIN match (ISIN uniquely identifies the instrument across series shifts e.g. EQ->BE)
            # 2. Exact (Symbol, Series) match as fallback if ISIN is unmapped
            # 3. New Instrument creation
            inst_id = isin_to_instrument_id.get(rec.isin)
            if not inst_id and rec.symbol and rec.series:
                inst_id = symbol_series_to_inst_id.get((rec.symbol, rec.series))

            if not inst_id:
                inst_id = str(uuid.uuid4())
                # Pre-existing instruments prior to dataset start have unknown listing date
                is_dataset_start = (trade_date <= datetime.date(2022, 1, 3))
                new_inst = Instrument(
                    instrument_id=inst_id,
                    name=rec.name,
                    status="ACTIVE",
                    listing_date=None if is_dataset_start else trade_date,
                    first_observed_trade_date=trade_date,
                )
                db.add(new_inst)
                if rec.isin:
                    isin_to_instrument_id[rec.isin] = inst_id
                if rec.symbol and rec.series:
                    symbol_series_to_inst_id[(rec.symbol, rec.series)] = inst_id

            hist_key = (inst_id, rec.symbol, rec.series, rec.isin)
            if hist_key not in existing_history_tuples:
                new_hist = InstrumentSymbolHistory(
                    instrument_id=inst_id,
                    exchange="NSE",
                    symbol=rec.symbol,
                    isin=rec.isin,
                    series=rec.series,
                    valid_from=trade_date,
                    source=source,
                )
                db.add(new_hist)
                existing_history_tuples.add(hist_key)

            price_row = DailyPriceRaw(
                instrument_id=inst_id,
                trade_date=trade_date,
                open=rec.open,
                high=rec.high,
                low=rec.low,
                close=rec.close,
                last=rec.last,
                prev_close=rec.prev_close,
                volume=rec.volume,
                traded_value=rec.traded_value,
                trades_count=rec.trades_count,
                series=rec.series,
                source=source,
                ingestion_run_id=run_id,
            )
            prices_to_insert.append(price_row)

        db.flush()
        db.add_all(prices_to_insert)
        db.flush()

    def ingest_range(
        self,
        start_date: datetime.date,
        end_date: datetime.date,
        force: bool = False,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """
        Ingest a continuous date range [start_date, end_date] inclusive.
        Pre-filters regular weekends and skips already-ingested dates safely.
        """
        if start_date > end_date:
            raise PipelineError(f"Start date {start_date} is after end date {end_date}")

        results: List[Dict[str, Any]] = []
        curr = start_date
        total_days = (end_date - start_date).days + 1
        logger.info("Beginning range ingestion: %s to %s (%d total days)", start_date, end_date, total_days)

        while curr <= end_date:
            # Pre-filter normal weekends unless special live session
            if curr.weekday() >= 5 and curr not in SPECIAL_WEEKEND_SESSIONS:
                curr += datetime.timedelta(days=1)
                continue

            try:
                res = self.ingest_date(curr, force=force, session=session)
                results.append(res)
            except PipelineError as e:
                logger.error("Range ingestion encountered pipeline error on %s: %s", curr, e)
                results.append({
                    "status": "FAILED",
                    "trade_date": str(curr),
                    "error": str(e),
                    "row_count": 0,
                })
            except Exception as e:
                logger.exception("Unexpected error during range ingestion on %s: %s", curr, e)
                results.append({
                    "status": "FAILED",
                    "trade_date": str(curr),
                    "error": str(e),
                    "row_count": 0,
                })

            curr += datetime.timedelta(days=1)

        return results

    def ingest_since_last(
        self,
        start_date: Optional[datetime.date] = None,
        target_date: Optional[datetime.date] = None,
        force: bool = False,
        session: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """
        Gap-Aware Catch-Up Engine:
        Scans all expected trading dates from earliest known date up to target_date.
        Discovers and retries BOTH internal missing gaps (e.g. missing June 5)
        and trailing uningested sessions.
        """
        with get_db(session) as db:
            bounds = db.execute(
                select(
                    func.min(IngestionRun.trade_date),
                    func.max(IngestionRun.trade_date),
                ).where(IngestionRun.status.in_(["SUCCESS", "QUARANTINED"]))
            ).first()

            min_date, max_date = bounds if bounds else (None, None)

            completed_dates: Set[datetime.date] = set(
                db.execute(
                    select(IngestionRun.trade_date).where(
                        IngestionRun.status.in_(["SUCCESS", "QUARANTINED"])
                    )
                ).scalars().all()
            )

            if not min_date or not max_date:
                raise PipelineError(
                    "No previously ingested trading days found in database. Use --from and --to to initialize historical ingestion."
                )

            scan_start = start_date or min_date
            scan_end = target_date or datetime.date.today()

            if scan_start > scan_end:
                logger.info("Database is already up to date as of %s (target=%s)", max_date, scan_end)
                return [
                    {
                        "status": "UP_TO_DATE",
                        "trade_date": str(max_date),
                        "message": f"Database is already up to date. Latest date: {max_date}",
                        "row_count": 0,
                    }
                ]

            # Use authoritative calendar to find ALL missing expected trading days
            missing_dates = NSETradingCalendar.get_missing_trading_days(
                start_date=scan_start,
                end_date=scan_end,
                completed_dates=completed_dates,
            )

            if not missing_dates:
                logger.info("All expected trading sessions between %s and %s are present in database.", scan_start, scan_end)
                return [
                    {
                        "status": "UP_TO_DATE",
                        "trade_date": str(max_date),
                        "message": f"All expected trading sessions between {scan_start} and {scan_end} are present.",
                        "row_count": 0,
                    }
                ]

            logger.info(
                "Found %d missing expected trading sessions (including internal gaps) between %s and %s",
                len(missing_dates),
                scan_start,
                scan_end,
            )

            results = []
            for missing_dt in sorted(missing_dates):
                try:
                    res = self.ingest_date(missing_dt, force=force, session=db)
                    results.append(res)
                except Exception as e:
                    logger.error("Failed to ingest missing session %s: %s", missing_dt, e)
                    results.append({
                        "status": "FAILED",
                        "trade_date": str(missing_dt),
                        "error": str(e),
                        "row_count": 0,
                    })

            return results
