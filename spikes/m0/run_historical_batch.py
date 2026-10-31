import argparse
import datetime
import json
import logging
from pathlib import Path
from typing import Dict, List, Any
from sqlalchemy import select, func

from signal_atlas.ingestion.pipeline import IngestionPipeline
from signal_atlas.providers.nse.calendar import (
    NSETradingCalendar,
    NSE_CONFIRMED_HOLIDAYS,
    SPECIAL_WEEKEND_SESSIONS,
)
from signal_atlas.db.session import get_db
from signal_atlas.db.models import DailyPriceRaw, IngestionRun

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_historical_batch")

QUARTERS = {
    "2024-Q4": (datetime.date(2024, 10, 1), datetime.date(2024, 12, 31)),
    "2024-Q3": (datetime.date(2024, 7, 1), datetime.date(2024, 9, 30)),
    "2024-Q2": (datetime.date(2024, 4, 1), datetime.date(2024, 6, 30)),
    "2024-Q1": (datetime.date(2024, 1, 1), datetime.date(2024, 3, 31)),
    "2023-Q4": (datetime.date(2023, 10, 1), datetime.date(2023, 12, 31)),
    "2023-Q3": (datetime.date(2023, 7, 1), datetime.date(2023, 9, 30)),
    "2023-Q2": (datetime.date(2023, 4, 1), datetime.date(2023, 6, 30)),
    "2023-Q1": (datetime.date(2023, 1, 1), datetime.date(2023, 3, 31)),
    "2022-Q4": (datetime.date(2022, 10, 1), datetime.date(2022, 12, 31)),
    "2022-Q3": (datetime.date(2022, 7, 1), datetime.date(2022, 9, 30)),
    "2022-Q2": (datetime.date(2022, 4, 1), datetime.date(2022, 6, 30)),
    "2022-Q1": (datetime.date(2022, 1, 1), datetime.date(2022, 3, 31)),
}


def run_batch(batch_name: str, start_date: datetime.date, end_date: datetime.date, force: bool = False) -> Dict[str, Any]:
    logger.info("==================================================")
    logger.info("Starting Batch [%s]: %s to %s", batch_name, start_date, end_date)
    logger.info("==================================================")

    pipeline = IngestionPipeline()
    expected_days = NSETradingCalendar.get_expected_trading_days(start_date, end_date)
    logger.info("Expected trading sessions in %s: %d", batch_name, len(expected_days))

    # Also capture confirmed holidays falling within range for completeness
    holidays_in_range = [
        d for d, name in sorted(NSE_CONFIRMED_HOLIDAYS.items())
        if start_date <= d <= end_date
    ]

    results_by_date = []
    success_count = 0
    quarantined_session_count = 0
    holiday_count = 0
    missing_count = 0
    failed_count = 0
    total_batch_rows = 0

    curr = start_date
    while curr <= end_date:
        if curr.weekday() >= 5 and curr not in SPECIAL_WEEKEND_SESSIONS:
            curr += datetime.timedelta(days=1)
            continue

        try:
            res = pipeline.ingest_date(curr, force=force)
            status = res.get("status")
            rows = res.get("row_count", 0)
            total_batch_rows += rows

            # Query DB for volume & value aggregate if success, already ingested, or quarantined
            vol_sum = 0
            val_sum = 0
            if status in ("SUCCESS", "ALREADY_INGESTED", "QUARANTINED"):
                success_count += 1
                if status == "QUARANTINED":
                    quarantined_session_count += 1
                with get_db() as db:
                    agg = db.execute(
                        select(
                            func.sum(DailyPriceRaw.volume),
                            func.sum(DailyPriceRaw.traded_value),
                        ).where(DailyPriceRaw.trade_date == curr)
                    ).first()
                    if agg and agg[0]:
                        vol_sum = int(agg[0])
                        val_sum = float(agg[1]) if agg[1] else 0.0
            elif status == "CONFIRMED_HOLIDAY":
                holiday_count += 1
            elif status == "EXPECTED_DATA_MISSING":
                missing_count += 1
            else:
                failed_count += 1

            results_by_date.append({
                "trade_date": str(curr),
                "status": status,
                "row_count": rows,
                "quarantine_count": res.get("quarantine_count", 0),
                "source": res.get("source", "N/A"),
                "file_hash": res.get("file_hash", "N/A"),
                "volume": vol_sum,
                "total_traded_value": val_sum,
                "message": res.get("message", ""),
            })

        except Exception as e:
            logger.error("Exception processing %s: %s", curr, e)
            failed_count += 1
            results_by_date.append({
                "trade_date": str(curr),
                "status": "FAILED",
                "row_count": 0,
                "error": str(e),
            })

        curr += datetime.timedelta(days=1)

    checkpoint_data = {
        "batch_name": batch_name,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "summary": {
            "expected_sessions": len(expected_days),
            "confirmed_holidays": holiday_count,
            "successful_sessions": success_count,
            "quarantined_sessions": quarantined_session_count,
            "missing_or_unresolved": missing_count,
            "failed_sessions": failed_count,
            "total_rows_persisted": total_batch_rows,
        },
        "details": results_by_date,
    }

    # Save checkpoint JSON
    checkpoint_dir = Path("data/checkpoints")
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = checkpoint_dir / f"checkpoint_{batch_name}.json"
    with open(checkpoint_file, "w", encoding="utf-8") as f:
        json.dump(checkpoint_data, f, indent=2)

    logger.info("Saved batch checkpoint to %s", checkpoint_file)
    logger.info("Batch [%s] Summary: Expected=%d, Success=%d, Holidays=%d, Missing=%d, Failed=%d, Rows=%d",
                batch_name, len(expected_days), success_count, holiday_count, missing_count, failed_count, total_batch_rows)

    return checkpoint_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Signal Atlas historical batch ingestion with checkpoints")
    parser.add_argument("--quarter", choices=list(QUARTERS.keys()), help="Quarter to ingest (e.g. 2024-Q4)")
    parser.add_argument("--all-2024", action="store_true", help="Ingest all 2024 quarters (Q4, Q3, Q2, Q1)")
    parser.add_argument("--all-2023", action="store_true", help="Ingest all 2023 quarters (Q4, Q3, Q2, Q1)")
    parser.add_argument("--all-2022", action="store_true", help="Ingest all 2022 quarters (Q4, Q3, Q2, Q1)")
    parser.add_argument("--from-date", help="Custom start date (YYYY-MM-DD)")
    parser.add_argument("--to-date", help="Custom end date (YYYY-MM-DD)")
    parser.add_argument("--batch-name", default="custom", help="Batch name for custom range")
    parser.add_argument("--force", action="store_true", help="Force re-ingestion of already processed dates")
    args = parser.parse_args()

    if args.quarter:
        s, e = QUARTERS[args.quarter]
        run_batch(args.quarter, s, e, force=args.force)
    elif args.all_2024:
        for q in ["2024-Q4", "2024-Q3", "2024-Q2", "2024-Q1"]:
            s, e = QUARTERS[q]
            run_batch(q, s, e, force=args.force)
    elif args.all_2023:
        for q in ["2023-Q4", "2023-Q3", "2023-Q2", "2023-Q1"]:
            s, e = QUARTERS[q]
            run_batch(q, s, e, force=args.force)
    elif args.all_2022:
        for q in ["2022-Q4", "2022-Q3", "2022-Q2", "2022-Q1"]:
            s, e = QUARTERS[q]
            run_batch(q, s, e, force=args.force)
    elif args.from_date and args.to_date:
        s = datetime.datetime.strptime(args.from_date, "%Y-%m-%d").date()
        e = datetime.datetime.strptime(args.to_date, "%Y-%m-%d").date()
        run_batch(args.batch_name, s, e, force=args.force)
    else:
        parser.print_help()
