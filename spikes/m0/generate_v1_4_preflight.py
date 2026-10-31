"""
Phase 1B-iii Preflight: All-Column Reconciliation between v1.3 and v1.4.

Compares every financial and analytical column on (instrument_id, trade_date, series):
  - open
  - high
  - low
  - close
  - last
  - prev_close
  - raw_prev_close
  - adjusted_vwap (vwap)
  - raw_vwap
  - volume
  - raw_volume
  - traded_value
  - raw_traded_value
  - cumulative_multiplier
  - applied_action_ids

Outputs exact mismatch counts and verification metrics.
"""

import json
from pathlib import Path
from sqlalchemy import text
from signal_atlas.db.session import get_db


def run_v1_4_all_column_preflight():
    print("=== Running Phase 1B-iii Part A: v1.4 Final Preflight Reconciliation ===")
    with get_db() as db:
        # 1. Total row count check
        count_v1_3 = db.execute(
            text("SELECT count(*) FROM daily_prices_adjusted WHERE adjustment_version = 'v1.3'")
        ).scalar()
        count_v1_4 = db.execute(
            text("SELECT count(*) FROM daily_prices_adjusted WHERE adjustment_version = 'v1.4'")
        ).scalar()

        print(f"v1.3 Total rows: {count_v1_3}")
        print(f"v1.4 Total rows: {count_v1_4}")
        assert count_v1_3 == 1848718, f"Expected 1,848,718 for v1.3, got {count_v1_3}"
        assert count_v1_4 == 1848718, f"Expected 1,848,718 for v1.4, got {count_v1_4}"

        # 2. Key matching check: ensure exactly matching (instrument_id, trade_date, series)
        unmatched_keys = db.execute(
            text("""
            SELECT count(*)
            FROM (
                SELECT instrument_id, trade_date, series FROM daily_prices_adjusted WHERE adjustment_version = 'v1.3'
                EXCEPT
                SELECT instrument_id, trade_date, series FROM daily_prices_adjusted WHERE adjustment_version = 'v1.4'
            ) diff
            """)
        ).scalar()
        print(f"Unmatched keys (v1.3 EXCEPT v1.4): {unmatched_keys}")
        assert unmatched_keys == 0, "Keys between v1.3 and v1.4 must be identical!"

        # 3. Column-by-column equality check
        cols_to_check = [
            ("open", "a.open IS DISTINCT FROM b.open"),
            ("high", "a.high IS DISTINCT FROM b.high"),
            ("low", "a.low IS DISTINCT FROM b.low"),
            ("close", "a.close IS DISTINCT FROM b.close"),
            ("last", "a.last IS DISTINCT FROM b.last"),
            ("prev_close", "a.prev_close IS DISTINCT FROM b.prev_close"),
            ("raw_prev_close", "a.raw_prev_close IS DISTINCT FROM b.raw_prev_close"),
            ("volume", "a.volume IS DISTINCT FROM b.volume"),
            ("raw_volume", "a.raw_volume IS DISTINCT FROM b.raw_volume"),
            ("traded_value", "a.traded_value IS DISTINCT FROM b.traded_value"),
            ("raw_traded_value", "a.raw_traded_value IS DISTINCT FROM b.raw_traded_value"),
            ("raw_vwap", "a.raw_vwap IS DISTINCT FROM b.raw_vwap"),
            ("adjusted_vwap", "a.adjusted_vwap IS DISTINCT FROM b.adjusted_vwap"),
            ("cumulative_multiplier", "a.cumulative_multiplier IS DISTINCT FROM b.cumulative_multiplier"),
            ("applied_action_ids", "a.applied_action_ids IS DISTINCT FROM b.applied_action_ids"),
        ]

        # Build single aggregation query for performance
        select_clauses = [
            f"COUNT(*) FILTER (WHERE {cond}) AS {col}_mismatches"
            for col, cond in cols_to_check
        ]
        agg_sql = f"""
        SELECT
            {', '.join(select_clauses)}
        FROM daily_prices_adjusted a
        JOIN daily_prices_adjusted b
          ON a.instrument_id = b.instrument_id
         AND a.trade_date = b.trade_date
         AND a.series = b.series
        WHERE a.adjustment_version = 'v1.3'
          AND b.adjustment_version = 'v1.4'
        """

        print("Executing full all-column SQL comparison...")
        result = db.execute(text(agg_sql)).mappings().first()

        mismatch_report = {}
        for col, _ in cols_to_check:
            cnt = result[f"{col}_mismatches"]
            mismatch_report[col] = cnt
            print(f"  - {col}: {cnt} mismatches")

        # 4. Detailed audit of the 1,028 applied_action_ids differences
        diff_detail_sql = """
        SELECT
            a.instrument_id,
            count(*) as row_count,
            min(a.trade_date) as min_date,
            max(a.trade_date) as max_date,
            a.applied_action_ids as v1_3_actions,
            b.applied_action_ids as v1_4_actions
        FROM daily_prices_adjusted a
        JOIN daily_prices_adjusted b
          ON a.instrument_id = b.instrument_id
         AND a.trade_date = b.trade_date
         AND a.series = b.series
        WHERE a.adjustment_version = 'v1.3'
          AND b.adjustment_version = 'v1.4'
          AND a.applied_action_ids IS DISTINCT FROM b.applied_action_ids
        GROUP BY a.instrument_id, a.applied_action_ids, b.applied_action_ids
        ORDER BY a.instrument_id
        """
        diff_details = db.execute(text(diff_detail_sql)).mappings().all()
        print("\nMetadata differences breakdown:")
        metadata_breakdown = []
        for row in diff_details:
            inst_id = row["instrument_id"]
            # Look up symbol
            sym_row = db.execute(
                text("SELECT symbol FROM instrument_symbol_history WHERE instrument_id = :iid ORDER BY valid_from DESC LIMIT 1"),
                {"iid": inst_id}
            ).mappings().first()
            sym = sym_row["symbol"] if sym_row else inst_id

            entry = {
                "instrument_id": inst_id,
                "symbol": sym,
                "row_count": row["row_count"],
                "min_date": str(row["min_date"]),
                "max_date": str(row["max_date"]),
                "v1_3_applied_action_ids": row["v1_3_actions"],
                "v1_4_applied_action_ids": row["v1_4_actions"],
            }
            metadata_breakdown.append(entry)
            print(f"  * {sym} ({inst_id}): {row['row_count']} rows [{row['min_date']} to {row['max_date']}]")
            print(f"      v1.3: {row['v1_3_actions']}")
            print(f"      v1.4: {row['v1_4_actions']}")

        total_metadata_diffs = sum(e["row_count"] for e in metadata_breakdown)
        print(f"\nTotal metadata rows changed: {total_metadata_diffs}")
        assert total_metadata_diffs == 1028, f"Expected exactly 1,028 metadata rows, got {total_metadata_diffs}"

        # 5. Check raw prices immutability
        raw_count = db.execute(text("SELECT count(*) FROM daily_prices_raw")).scalar()
        print(f"\nDailyPriceRaw total count: {raw_count} (strictly 1,855,370 immutable rows)")
        assert raw_count == 1855370

        # Export deliverable
        out_path = Path("data/checkpoints/v1_4_preflight_all_column_reconciliation.json")
        out_data = {
            "preflight_name": "Phase 1B-iii Part A: v1.4 Final Preflight All-Column Reconciliation",
            "v1_3_row_count": count_v1_3,
            "v1_4_row_count": count_v1_4,
            "raw_row_count": raw_count,
            "column_mismatch_counts": mismatch_report,
            "financial_columns_perfect_equality": all(
                cnt == 0 for col, cnt in mismatch_report.items() if col != "applied_action_ids"
            ),
            "total_metadata_action_id_changes": total_metadata_diffs,
            "metadata_change_breakdown": metadata_breakdown,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out_data, f, indent=2)
        print(f"Exported preflight report to {out_path}")


if __name__ == "__main__":
    run_v1_4_all_column_preflight()
