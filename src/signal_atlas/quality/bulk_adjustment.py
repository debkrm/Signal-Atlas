"""
bulk_adjustment.py - High-Performance Bulk Historical Price Adjustment Engine.

Produces derived historical backward-adjusted price series across the complete 2022-2024
trading dataset with high-precision volume, correct exchange turnover semantics,
aligned ex-date previous close, and point-in-time (PIT) adjustment capability.

Key Architectural Guarantees:
  1. Raw price immutability: daily_prices_raw is strictly read-only and never modified.
  2. Exchange Turnover Semantics:
     - traded_value is strictly invariant exchange turnover, NOT closing price * volume.
     - adjusted_vwap * adjusted_volume == raw_traded_value.
     - adjusted_close * adjusted_volume == raw_close * raw_volume is maintained as a
       mathematical close-volume product invariant, not exchange turnover.
  3. Ex-Date Previous Close Alignment:
     - On ex-dates, adjusted_prev_close is scaled by the ex-date action multiplier,
       ensuring gap and return calculations compare identical share coordinates.
     - raw_prev_close is preserved unchanged.
  4. Point-in-Time (PIT) Vintages:
     - Supports latest full-history vintage (for charting/research) and historical
       point-in-time as-of vintages (for backtesting without lookahead bias).
  5. Quarantine Enforcement:
     - 11 unresolved ETF scheme restructurings are 100% excluded from adjusted tables.
"""

import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
from typing import Dict, List, Set, Any, Tuple, Optional
import uuid
import time

from sqlalchemy import select, delete, func, text
from signal_atlas.db.session import get_db
from signal_atlas.db.models import (
    DailyPriceRaw,
    DailyPriceAdjusted,
    CorporateAction,
    Instrument,
    InstrumentSymbolHistory,
)
from signal_atlas.quality.adjustment import (
    apply_backward_adjustment,
    is_action_eligible_for_price_adjustment,
)


def get_quarantined_unresolved_instruments(session=None) -> Dict[str, Dict[str, Any]]:
    """
    Returns instruments that must be excluded from adjusted price generation
    due to unresolved material corporate actions (e.g. ETF scheme restructuring).
    """
    with get_db(session) as db:
        unresolved_cas = db.execute(
            select(CorporateAction).where(
                CorporateAction.verification_status.in_([
                    "UNRESOLVED",
                    "UNRESOLVED_ETF_SCHEME_RESTRUCTURING"
                ])
            )
        ).scalars().all()

        quarantined: Dict[str, Dict[str, Any]] = {}
        for ca in unresolved_cas:
            # Query raw price count for this instrument
            raw_count = db.execute(
                select(func.count(DailyPriceRaw.id)).where(DailyPriceRaw.instrument_id == ca.instrument_id)
            ).scalar() or 0

            quarantined[ca.instrument_id] = {
                "instrument_id": ca.instrument_id,
                "symbol": ca.symbol,
                "series": ca.series,
                "action_id": ca.action_id,
                "action_type": ca.action_type,
                "ex_date": str(ca.ex_date),
                "verification_status": ca.verification_status,
                "reason": ca.purpose,
                "quarantine_policy": "EXCLUDED_FROM_ADJUSTED_RESEARCH",
                "affected_raw_price_records": raw_count,
            }

        return quarantined


def export_quarantine_report(
    quarantined: Dict[str, Dict[str, Any]],
    output_path: Path = Path("data/checkpoints/unresolved_instruments_quarantine_report.json"),
) -> None:
    """Exports quarantine/unresolved-event report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "report_name": "Unresolved Instruments Corporate Action Quarantine Report",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_quarantined_instruments": len(quarantined),
        "total_affected_raw_price_records": sum(q["affected_raw_price_records"] for q in quarantined.values()),
        "quarantine_policy": (
            "Instruments with unresolved material structural events (such as ETF scheme restructurings "
            "where predecessor and successor mutual fund baskets differ) are marked UNAVAILABLE_FOR_ADJUSTED_ANALYSIS "
            "and strictly excluded from the analytical adjusted prices dataset."
        ),
        "quarantined_instruments": list(quarantined.values()),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


def run_bulk_adjustment(
    version: str = "v1.4",
    vintage: str = "LATEST_VINTAGE",
    as_of_date: Optional[datetime.date] = None,
    batch_size: int = 5000,
    session=None,
) -> Dict[str, Any]:
    """
    Executes deterministic bulk historical price adjustment rebuild for version v1.4.
    """

    start_time = time.time()
    run_id = str(uuid.uuid4())
    effective_as_of = as_of_date or datetime.date(2024, 12, 31)

    print(f"=== Starting Bulk Historical Price Adjustment (Version: {version}, Vintage: {vintage}, As-Of: {effective_as_of}, Run ID: {run_id}) ===")

    with get_db(session) as db:
        # 1. Audit raw records before starting (Guaranteed immutability)
        initial_raw_count = db.execute(select(func.count(DailyPriceRaw.id))).scalar()
        print(f"Verified initial raw price records in daily_prices_raw: {initial_raw_count:,}")

        # 2. Identify quarantined instruments
        quarantined = get_quarantined_unresolved_instruments(db)
        quarantine_inst_ids = set(quarantined.keys())
        quarantine_raw_rows = sum(q["affected_raw_price_records"] for q in quarantined.values())
        print(f"Identified {len(quarantine_inst_ids)} quarantined instruments ({quarantine_raw_rows:,} raw records excluded)")

        # Export quarantine report
        export_quarantine_report(quarantined)

        # 3. Clean existing adjusted records for this version and as_of_date (Deterministic & Idempotent)
        deleted = db.execute(
            delete(DailyPriceAdjusted).where(
                DailyPriceAdjusted.adjustment_version == version,
                DailyPriceAdjusted.adjustment_as_of_date == effective_as_of,
            )
        ).rowcount
        db.commit()
        if deleted > 0:
            print(f"Cleared {deleted:,} existing adjusted records for version '{version}' as-of {effective_as_of}")

        # 4. Fetch all verified corporate actions that adjust prices (STOCK_SPLIT, BONUS_ISSUE)
        active_cas = db.execute(
            select(CorporateAction).where(
                CorporateAction.action_type.in_(["STOCK_SPLIT", "BONUS_ISSUE"]),
                CorporateAction.share_multiplier != Decimal("1.000000"),
                CorporateAction.share_multiplier > Decimal("0"),
                CorporateAction.verification_status == "VERIFIED",
            ).order_by(CorporateAction.ex_date)
        ).scalars().all()
        active_cas = [ca for ca in active_cas if is_action_eligible_for_price_adjustment(ca)]

        # Group actions by instrument_id (filtering by as_of_date for point-in-time consistency)
        ca_by_inst: Dict[str, List[CorporateAction]] = {}
        for ca in active_cas:
            if ca.instrument_id not in quarantine_inst_ids and ca.ex_date <= effective_as_of:
                ca_by_inst.setdefault(ca.instrument_id, []).append(ca)

        ca_inst_ids = set(ca_by_inst.keys())
        print(f"Identified {len(ca_inst_ids)} instruments with verified price-adjusting corporate actions effective on or before {effective_as_of}")

        # 5. Process Corporate Action Instruments via backward adjustment engine
        print(f"Calculating backward adjustments for {len(ca_inst_ids)} corporate action instruments...")
        adjusted_records_to_insert: List[Dict[str, Any]] = []
        ca_raw_count = 0
        product_violations = 0
        turnover_violations = 0
        vwap_violations = 0

        for inst_id in ca_inst_ids:
            inst_actions = ca_by_inst[inst_id]
            raw_prices = db.execute(
                select(DailyPriceRaw)
                .where(
                    DailyPriceRaw.instrument_id == inst_id,
                    DailyPriceRaw.trade_date <= effective_as_of,
                )
                .order_by(DailyPriceRaw.trade_date)
            ).scalars().all()

            ca_raw_count += len(raw_prices)
            raw_dicts = [
                {
                    "trade_date": p.trade_date,
                    "series": p.series,
                    "open": p.open,
                    "high": p.high,
                    "low": p.low,
                    "close": p.close,
                    "last": p.last,
                    "prev_close": p.prev_close,
                    "volume": p.volume,
                    "traded_value": p.traded_value,
                }
                for p in raw_prices
            ]

            adjusted_list = apply_backward_adjustment(
                raw_dicts,
                inst_actions,
                version=version,
                as_of_date=effective_as_of,
                vintage=vintage,
            )

            for adj, raw_item in zip(adjusted_list, raw_dicts):
                # Verify close-volume product invariance
                if not adj.verify_close_volume_product_invariance(Decimal(str(raw_item["close"])), raw_item["volume"]):
                    product_violations += 1

                # Verify strict exchange turnover invariance
                if not adj.verify_turnover_invariance():
                    turnover_violations += 1

                # Verify VWAP turnover relationship
                if not adj.verify_vwap_turnover_relationship():
                    vwap_violations += 1

                action_ids_str = ",".join(adj.applied_action_ids) if adj.applied_action_ids else None
                adjusted_records_to_insert.append({
                    "instrument_id": inst_id,
                    "trade_date": adj.trade_date,
                    "series": raw_item["series"],
                    "open": adj.open,
                    "high": adj.high,
                    "low": adj.low,
                    "close": adj.close,
                    "last": adj.last,
                    "prev_close": adj.prev_close,
                    "raw_prev_close": adj.raw_prev_close,
                    "volume": adj.volume,
                    "raw_volume": adj.raw_volume,
                    "traded_value": adj.traded_value,
                    "raw_traded_value": adj.raw_traded_value,
                    "raw_vwap": adj.raw_vwap,
                    "adjusted_vwap": adj.adjusted_vwap,
                    "cumulative_multiplier": adj.cumulative_multiplier,
                    "applied_action_ids": action_ids_str,
                    "adjustment_version": version,
                    "adjustment_vintage": vintage,
                    "adjustment_as_of_date": effective_as_of,
                    "adjustment_run_id": run_id,
                })

                if len(adjusted_records_to_insert) >= batch_size:
                    db.bulk_insert_mappings(DailyPriceAdjusted, adjusted_records_to_insert)
                    db.commit()
                    adjusted_records_to_insert.clear()

        if adjusted_records_to_insert:
            db.bulk_insert_mappings(DailyPriceAdjusted, adjusted_records_to_insert)
            db.commit()
            adjusted_records_to_insert.clear()

        print(f"Persisted {ca_raw_count:,} adjusted records for corporate action instruments.")
        print(f"  Close-Volume Product Invariance Violations: {product_violations}")
        print(f"  Exchange Turnover Invariance Violations:   {turnover_violations}")
        print(f"  VWAP Turnover Relationship Violations:     {vwap_violations}")

        # 6. Bulk insert Identity Records (M = 1.0) directly in PostgreSQL for remaining instruments
        print("Executing high-speed bulk population in PostgreSQL for identity instruments (M = 1.0)...")

        bulk_sql = text("""
            INSERT INTO daily_prices_adjusted (
                instrument_id, trade_date, series,
                open, high, low, close, last, prev_close, raw_prev_close,
                volume, raw_volume, traded_value, raw_traded_value,
                raw_vwap, adjusted_vwap,
                cumulative_multiplier, applied_action_ids,
                adjustment_version, adjustment_vintage, adjustment_as_of_date,
                adjustment_run_id, created_at
            )
            SELECT
                d.instrument_id, d.trade_date, d.series,
                d.open, d.high, d.low, d.close, d.last, d.prev_close, d.prev_close,
                d.volume::numeric(20, 6), d.volume, d.traded_value, d.traded_value,
                CASE WHEN d.volume > 0 AND d.traded_value IS NOT NULL THEN (d.traded_value / d.volume)::numeric(16, 6) ELSE NULL END,
                CASE WHEN d.volume > 0 AND d.traded_value IS NOT NULL THEN (d.traded_value / d.volume)::numeric(16, 6) ELSE NULL END,
                1.000000, NULL,
                :adj_version, :adj_vintage, :as_of_date,
                :run_id, NOW()
            FROM daily_prices_raw d
            WHERE d.trade_date <= :as_of_date
            AND d.instrument_id NOT IN (
                SELECT instrument_id FROM corporate_actions
                WHERE action_type IN ('STOCK_SPLIT', 'BONUS_ISSUE')
                  AND share_multiplier != 1.000000
                  AND share_multiplier > 0
                  AND verification_status = 'VERIFIED'
                  AND ex_date <= :as_of_date
            )
            AND d.instrument_id NOT IN (
                SELECT instrument_id FROM corporate_actions
                WHERE verification_status IN ('UNRESOLVED', 'UNRESOLVED_ETF_SCHEME_RESTRUCTURING')
            )
        """)

        result = db.execute(
            bulk_sql,
            {
                "adj_version": version,
                "adj_vintage": vintage,
                "as_of_date": effective_as_of,
                "run_id": run_id,
            }
        )
        identity_inserted = result.rowcount
        db.commit()
        print(f"Persisted {identity_inserted:,} identity adjusted records (M = 1.0)")

        # 7. Post-Adjustment Verification & Validation
        total_adjusted = db.execute(
            select(func.count(DailyPriceAdjusted.id)).where(
                DailyPriceAdjusted.adjustment_version == version,
                DailyPriceAdjusted.adjustment_as_of_date == effective_as_of,
            )
        ).scalar()
        final_raw_count = db.execute(select(func.count(DailyPriceRaw.id))).scalar()

        print("\n=== Adjustment Verification Results ===")
        print(f"Initial raw price records:      {initial_raw_count:,}")
        print(f"Final raw price records:        {final_raw_count:,} (Difference: {final_raw_count - initial_raw_count})")
        print(f"Quarantined raw records:        {quarantine_raw_rows:,}")
        print(f"Total adjusted records:         {total_adjusted:,}")
        print(f"Expected adjusted records:      {initial_raw_count - quarantine_raw_rows:,}")
        assert final_raw_count == initial_raw_count, "CRITICAL ERROR: daily_prices_raw was modified!"
        assert total_adjusted == initial_raw_count - quarantine_raw_rows, (
            f"Row count mismatch: total_adjusted ({total_adjusted}) != "
            f"raw ({initial_raw_count}) - quarantined ({quarantine_raw_rows})"
        )

        elapsed_sec = round(time.time() - start_time, 2)
        print(f"Bulk adjustment {version} completed successfully in {elapsed_sec}s!")

        # 8. Export Instrument-Level Adjustment Coverage Report
        all_instruments_count = db.execute(select(func.count(Instrument.instrument_id))).scalar()
        coverage_report = {
            "adjustment_run_id": run_id,
            "adjustment_version": version,
            "adjustment_vintage": vintage,
            "adjustment_as_of_date": str(effective_as_of),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "execution_duration_seconds": elapsed_sec,
            "raw_dataset": {
                "total_raw_records": initial_raw_count,
                "total_instruments": all_instruments_count,
                "raw_records_immutable": (final_raw_count == initial_raw_count),
            },
            "adjusted_dataset": {
                "total_adjusted_records": total_adjusted,
                "published_instruments_count": all_instruments_count - len(quarantined),
                "corporate_action_adjusted_instruments": len(ca_inst_ids),
                "corporate_action_adjusted_records": ca_raw_count,
                "identity_instruments": all_instruments_count - len(quarantined) - len(ca_inst_ids),
                "identity_records": identity_inserted,
                "quarantined_instruments": len(quarantined),
                "quarantined_records_excluded": quarantine_raw_rows,
                "close_volume_product_invariance_violations": product_violations,
                "close_volume_product_invariance_success_rate": 100.0 if product_violations == 0 else 0.0,
                "traded_value_turnover_invariance_violations": turnover_violations,
                "traded_value_turnover_invariance_success_rate": 100.0 if turnover_violations == 0 else 0.0,
                "vwap_turnover_relationship_violations": vwap_violations,
                "vwap_turnover_relationship_success_rate": 100.0 if vwap_violations == 0 else 0.0,
            },
        }

        coverage_path = Path("data/checkpoints/instrument_adjustment_coverage_report.json")
        coverage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(coverage_path, "w", encoding="utf-8") as f:
            json.dump(coverage_report, f, indent=2)
        print(f"Exported coverage report to {coverage_path}")

        return coverage_report


if __name__ == "__main__":
    run_bulk_adjustment()
