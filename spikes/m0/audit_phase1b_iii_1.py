import datetime
from sqlalchemy import text
from signal_atlas.db.session import get_db

def run_audit():
    with get_db() as db:
        # 1. Audit listing_date
        print("=== 1. Instruments Listing Date Audit ===")
        total_inst = db.execute(text("SELECT count(*) FROM instruments")).scalar()
        non_null_listing = db.execute(text("SELECT count(*) FROM instruments WHERE listing_date IS NOT NULL")).scalar()
        print(f"Total instruments: {total_inst}, with listing_date: {non_null_listing}")

        # Check earliest trade date in DailyPriceRaw vs listing_date
        diff_dates = db.execute(text("""
            SELECT count(*)
            FROM instruments i
            JOIN (
                SELECT instrument_id, min(trade_date) as min_td
                FROM daily_prices_raw
                GROUP BY instrument_id
            ) r ON i.instrument_id = r.instrument_id
            WHERE i.listing_date != r.min_td
        """)).scalar()
        print(f"Instruments where listing_date != min(daily_prices_raw.trade_date): {diff_dates}")

        # 2. Audit DailyPriceRaw for multiple series on same (instrument_id, trade_date)
        print("\n=== 2. DailyPriceRaw Multiple Series Audit ===")
        multi_series_sql = """
            SELECT count(*) as total_groups, count(distinct instrument_id) as affected_instruments
            FROM (
                SELECT instrument_id, trade_date
                FROM daily_prices_raw
                WHERE series IN ('EQ', 'BE')
                GROUP BY instrument_id, trade_date
                HAVING count(*) > 1
            ) sub
        """
        ms_res = db.execute(text(multi_series_sql)).mappings().first()
        print(f"Duplicate (instrument_id, trade_date) in EQ/BE: {ms_res['total_groups']} groups across {ms_res['affected_instruments']} instruments")

        if ms_res['total_groups'] > 0:
            samples = db.execute(text("""
                SELECT r.instrument_id, r.trade_date, r.series, r.close, r.volume, r.traded_value
                FROM daily_prices_raw r
                JOIN (
                    SELECT instrument_id, trade_date
                    FROM daily_prices_raw
                    WHERE series IN ('EQ', 'BE')
                    GROUP BY instrument_id, trade_date
                    HAVING count(*) > 1
                    LIMIT 5
                ) s ON r.instrument_id = s.instrument_id AND r.trade_date = s.trade_date
                ORDER BY r.instrument_id, r.trade_date, r.series
            """)).mappings().all()
            print("Samples of EQ/BE same-date pairs:")
            for s in samples:
                print("  ", dict(s))

        # Check all series multiple rows
        all_multi_sql = """
            SELECT count(*) as total_groups, count(distinct instrument_id) as affected_instruments
            FROM (
                SELECT instrument_id, trade_date
                FROM daily_prices_raw
                GROUP BY instrument_id, trade_date
                HAVING count(*) > 1
            ) sub
        """
        all_ms_res = db.execute(text(all_multi_sql)).mappings().first()
        print(f"Multiple series across ALL series: {all_ms_res['total_groups']} groups across {all_ms_res['affected_instruments']} instruments")

        if all_ms_res['total_groups'] > 0:
            all_samples = db.execute(text("""
                SELECT r.instrument_id, r.trade_date, r.series, r.close, r.volume, r.traded_value
                FROM daily_prices_raw r
                JOIN (
                    SELECT instrument_id, trade_date
                    FROM daily_prices_raw
                    GROUP BY instrument_id, trade_date
                    HAVING count(*) > 1
                    LIMIT 10
                ) s ON r.instrument_id = s.instrument_id AND r.trade_date = s.trade_date
                ORDER BY r.instrument_id, r.trade_date, r.series
            """)).mappings().all()
            print("Samples of all-series same-date pairs:")
            for s in all_samples:
                print("  ", dict(s))

        # 3. Audit InstrumentSymbolHistory for overlapping intervals
        print("\n=== 3. InstrumentSymbolHistory Overlap Audit ===")
        overlap_sql = """
            SELECT count(*) as overlap_count, count(distinct a.instrument_id) as affected_instruments
            FROM instrument_symbol_history a
            JOIN instrument_symbol_history b
              ON a.instrument_id = b.instrument_id
             AND a.id < b.id
             AND a.series IN ('EQ', 'BE')
             AND b.series IN ('EQ', 'BE')
             AND a.valid_from <= COALESCE(b.valid_to, '9999-12-31')
             AND b.valid_from <= COALESCE(a.valid_to, '9999-12-31')
        """
        ov_res = db.execute(text(overlap_sql)).mappings().first()
        print(f"Overlapping intervals in EQ/BE: {ov_res['overlap_count']} pairs across {ov_res['affected_instruments']} instruments")
        if ov_res['overlap_count'] > 0:
            ov_samples = db.execute(text("""
                SELECT a.instrument_id, a.symbol as sym_a, a.series as ser_a, a.valid_from as vf_a, a.valid_to as vt_a,
                       b.symbol as sym_b, b.series as ser_b, b.valid_from as vf_b, b.valid_to as vt_b
                FROM instrument_symbol_history a
                JOIN instrument_symbol_history b
                  ON a.instrument_id = b.instrument_id
                 AND a.id < b.id
                 AND a.series IN ('EQ', 'BE')
                 AND b.series IN ('EQ', 'BE')
                 AND a.valid_from <= COALESCE(b.valid_to, '9999-12-31')
                 AND b.valid_from <= COALESCE(a.valid_to, '9999-12-31')
                LIMIT 10
            """)).mappings().all()
            print("Samples of overlapping symbol history intervals:")
            for s in ov_samples:
                print("  ", dict(s))


if __name__ == "__main__":
    run_audit()
