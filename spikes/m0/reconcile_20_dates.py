import datetime
import io
import json
import logging
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import List, Dict, Any
import pandas as pd
from sqlalchemy import select, func

from signal_atlas.db.session import get_db
from signal_atlas.db.models import DailyPriceRaw, IngestionRun, Instrument
from signal_atlas.providers.nse.legacy_parser import LegacyBhavcopyParser
from signal_atlas.providers.nse.udiff_parser import UDiFFParser
from signal_atlas.ingestion.normalizer import RecordNormalizer
from signal_atlas.quality.validation import BatchValidator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reconcile_20_dates")

SAMPLE_DATES = [
    # 2022 Legacy
    datetime.date(2022, 1, 3),    # First session of 2022
    datetime.date(2022, 3, 22),   # Legacy regular session
    datetime.date(2022, 6, 15),   # Mid-2022 session
    datetime.date(2022, 9, 8),    # Corporate action: TATASTEEL 10:1 split ex-date
    datetime.date(2022, 10, 24),  # Muhurat Trading session
    datetime.date(2022, 12, 30),  # Last session of 2022
    # 2023 Legacy
    datetime.date(2023, 1, 2),    # First session of 2023
    datetime.date(2023, 4, 20),   # Corporate action: NESTLEIND 10:1 split ex-date
    datetime.date(2023, 6, 15),   # Institutional block deal day
    datetime.date(2023, 6, 28),   # Bakri Id pre-shift session
    datetime.date(2023, 9, 28),   # Phase 1B-i sample date
    datetime.date(2023, 11, 3),   # Phase 1B-i sample date
    datetime.date(2023, 11, 12),  # Sunday Muhurat Trading session
    datetime.date(2023, 12, 29),  # Last session of 2023
    # 2024 Legacy Era (pre-July 8)
    datetime.date(2024, 1, 1),    # First session of 2024
    datetime.date(2024, 1, 20),   # Saturday live session
    datetime.date(2024, 3, 2),    # Saturday DR live session
    datetime.date(2024, 5, 18),   # Saturday DR live session
    datetime.date(2024, 6, 3),    # Election exit poll rally
    datetime.date(2024, 7, 5),    # Final Legacy Bhavcopy before UDiFF
    # 2024 UDiFF Era (post-July 8)
    datetime.date(2024, 7, 8),    # First CM-UDiFF session
    datetime.date(2024, 7, 15),   # Phase 1B-i transition benchmark
    datetime.date(2024, 8, 19),   # Session with quarantined T0 outlier
    datetime.date(2024, 10, 25),  # Phase 1A/1A.1 audited date
    datetime.date(2024, 11, 1),   # Diwali Muhurat Trading UDiFF session
    datetime.date(2024, 12, 31),  # Final session of 2024
]


def run_reconciliation() -> List[Dict[str, Any]]:
    legacy_parser = LegacyBhavcopyParser()
    udiff_parser = UDiFFParser()
    normalizer = RecordNormalizer()
    validator = BatchValidator()

    reconciliation_results = []

    for dt in SAMPLE_DATES:
        logger.info("Reconciling %s ...", dt)
        is_udiff = dt >= datetime.date(2024, 7, 8)
        era = "UDiFF" if is_udiff else "Legacy"
        parser = udiff_parser if is_udiff else legacy_parser

        # 1. Fetch DB run & stats
        with get_db() as db:
            run = db.execute(
                select(IngestionRun).where(
                    IngestionRun.trade_date == dt,
                    IngestionRun.status.in_(["SUCCESS", "QUARANTINED"]),
                )
            ).scalars().first()

            if not run:
                logger.error("No successful IngestionRun found in DB for %s", dt)
                continue

            file_name = run.file_name
            db_status = run.status
            db_run_id = run.run_id

            db_stats = db.execute(
                select(
                    func.count(DailyPriceRaw.id),
                    func.sum(DailyPriceRaw.volume),
                    func.sum(DailyPriceRaw.traded_value),
                    func.count(func.distinct(DailyPriceRaw.instrument_id)),
                ).where(DailyPriceRaw.trade_date == dt)
            ).first()

            db_row_count = int(db_stats[0]) if db_stats and db_stats[0] else 0
            db_volume = int(db_stats[1]) if db_stats and db_stats[1] else 0
            db_traded_value = Decimal(str(db_stats[2])) if db_stats and db_stats[2] else Decimal("0.00")
            db_distinct_instruments = int(db_stats[3]) if db_stats and db_stats[3] else 0

            # Check duplicate (instrument_id, trade_date, series)
            dup_check = db.execute(
                select(DailyPriceRaw.instrument_id, DailyPriceRaw.series, func.count())
                .where(DailyPriceRaw.trade_date == dt)
                .group_by(DailyPriceRaw.instrument_id, DailyPriceRaw.series)
                .having(func.count() > 1)
            ).all()
            db_has_duplicates = len(dup_check) > 0

        # 2. Locate and parse raw archive file
        year_str = str(dt.year)
        raw_path = Path("data/raw") / year_str / file_name
        if not raw_path.exists():
            # Check root raw dir
            raw_path = Path("data/raw") / file_name

        if not raw_path.exists():
            logger.error("Raw archive file %s not found on disk!", raw_path)
            continue

        raw_bytes = raw_path.read_bytes()
        raw_records = parser.parse_archive(raw_bytes)
        normalized_records = normalizer.normalize_batch(raw_records)
        valid_records, val_result = validator.validate_batch(normalized_records, expected_date=dt)

        source_total_rows = len(raw_records)
        source_valid_rows = len(valid_records)
        source_quarantine_rows = val_result.quarantine_count

        source_volume = sum(r.volume for r in valid_records)
        source_traded_value = sum(r.traded_value for r in valid_records)

        # Check reconciliation criteria
        row_count_match = (db_row_count == source_valid_rows)
        volume_match = (db_volume == source_volume)
        value_diff = abs(db_traded_value - source_traded_value)
        value_match = (value_diff < Decimal("0.01"))
        reconciled = row_count_match and volume_match and value_match and not db_has_duplicates

        result = {
            "trade_date": str(dt),
            "format_era": era,
            "status": db_status,
            "archive_file": file_name,
            "source_raw_rows": source_total_rows,
            "source_valid_rows": source_valid_rows,
            "source_quarantine_rows": source_quarantine_rows,
            "db_persisted_rows": db_row_count,
            "row_count_match": row_count_match,
            "source_volume": source_volume,
            "db_volume": db_volume,
            "volume_match": volume_match,
            "source_traded_value": float(source_traded_value),
            "db_traded_value": float(db_traded_value),
            "value_match": value_match,
            "db_distinct_instruments": db_distinct_instruments,
            "db_has_duplicates": db_has_duplicates,
            "reconciled": reconciled,
        }
        reconciliation_results.append(result)
        logger.info(
            "[%s] %s: Reconciled=%s (Rows: %d/%d, Vol: %d/%d, Val: %.2f/%.2f)",
            era,
            dt,
            reconciled,
            db_row_count,
            source_valid_rows,
            db_volume,
            source_volume,
            db_traded_value,
            source_traded_value,
        )

    out_file = Path("data/checkpoints/reconciliation_26_dates.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(reconciliation_results, f, indent=2)
    logger.info("Saved 26-date reconciliation report to %s", out_file)

    # Print summary
    all_passed = all(r["reconciled"] for r in reconciliation_results)
    print("\n" + "=" * 80)
    print(f"RECONCILIATION SUMMARY: {len(reconciliation_results)} / {len(SAMPLE_DATES)} Dates Tested")
    print(f"Overall Status: {'PASSED (100%)' if all_passed else 'FAILED'}")
    print("=" * 80)
    return reconciliation_results


if __name__ == "__main__":
    run_reconciliation()
