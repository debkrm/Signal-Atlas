import datetime
from pathlib import Path
from sqlalchemy import select, delete

from signal_atlas.db.session import get_db
from signal_atlas.db.models import IngestionRun, DailyPriceQuarantine
from signal_atlas.providers.nse.legacy_parser import LegacyBhavcopyParser
from signal_atlas.providers.nse.udiff_parser import UDiFFParser
from signal_atlas.ingestion.normalizer import RecordNormalizer
from signal_atlas.quality.validation import BatchValidator

def backfill():
    legacy_parser = LegacyBhavcopyParser()
    udiff_parser = UDiFFParser()
    normalizer = RecordNormalizer()
    validator = BatchValidator()

    with get_db() as db:
        # Clear existing quarantine table to prevent duplicates
        db.execute(delete(DailyPriceQuarantine))
        db.flush()

        runs = db.execute(
            select(IngestionRun)
            .where(IngestionRun.status == "QUARANTINED")
            .order_by(IngestionRun.trade_date)
        ).scalars().all()

        print(f"Found {len(runs)} quarantined sessions to backfill.")
        total_quarantined_inserted = 0

        for r in runs:
            dt = r.trade_date
            is_udiff = dt >= datetime.date(2024, 7, 8)
            parser = udiff_parser if is_udiff else legacy_parser

            year_str = str(dt.year)
            raw_path = Path("data/raw") / year_str / r.file_name
            if not raw_path.exists():
                raw_path = Path("data/raw") / r.file_name

            if not raw_path.exists():
                print(f"Error: Archive not found for {dt}: {raw_path}")
                continue

            raw_bytes = raw_path.read_bytes()
            raw_records = parser.parse_archive(raw_bytes)
            normalized = normalizer.normalize_batch(raw_records)
            valid, val_result = validator.validate_batch(normalized, expected_date=dt)

            print(f"Date: {dt} | Total parsed: {len(raw_records)} | Valid: {len(valid)} | Quarantined: {len(val_result.quarantined_records)}")

            for q in val_result.quarantined_records:
                q_entry = DailyPriceQuarantine(
                    trade_date=dt,
                    symbol=q.record.symbol,
                    series=q.record.series,
                    isin=q.record.isin,
                    row_number=q.row_number,
                    raw_payload=q.raw_payload or {},
                    validation_rule=q.rule,
                    validation_message=q.message,
                    source_file=r.file_name,
                    source_file_hash=r.file_hash,
                    ingestion_run_id=r.run_id,
                )
                db.add(q_entry)
                total_quarantined_inserted += 1

        db.flush()
        print(f"\nSuccessfully backfilled {total_quarantined_inserted} quarantined records across {len(runs)} sessions into daily_price_quarantine.")

if __name__ == "__main__":
    backfill()
