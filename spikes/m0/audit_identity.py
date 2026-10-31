from signal_atlas.db.session import get_db
from signal_atlas.db.models import Instrument, InstrumentSymbolHistory, DailyPriceRaw
from sqlalchemy import func, select

def audit():
    with get_db() as db:
        print("=== 1. Concurrent Multi-Series Records (Same Date, Same Instrument) ===")
        concurrent = db.execute(
            select(DailyPriceRaw.trade_date, DailyPriceRaw.instrument_id, func.count())
            .group_by(DailyPriceRaw.trade_date, DailyPriceRaw.instrument_id)
            .having(func.count() > 1)
            .order_by(func.count().desc())
            .limit(5)
        ).all()
        for dt, inst_id, cnt in concurrent:
            inst = db.execute(select(Instrument).where(Instrument.instrument_id == inst_id)).scalar()
            rows = db.execute(
                select(DailyPriceRaw.series, DailyPriceRaw.close, DailyPriceRaw.volume)
                .where(DailyPriceRaw.trade_date == dt, DailyPriceRaw.instrument_id == inst_id)
            ).all()
            print(f"Date: {dt} | Instrument: {inst.name} ({inst_id[:8]}...) | Concurrent Count: {cnt} | Series: {[r[0] for r in rows]}")

        print("\n=== 2. Multi-Series Shifts (e.g. EQ to BE/BZ, or EQ + BL) ===")
        transitions = db.execute(
            select(InstrumentSymbolHistory.instrument_id, func.count(func.distinct(InstrumentSymbolHistory.series)))
            .group_by(InstrumentSymbolHistory.instrument_id)
            .having(func.count(func.distinct(InstrumentSymbolHistory.series)) > 1)
            .limit(5)
        ).all()
        print(f"Found {len(transitions)} sample instruments with multiple series transitions:")
        for inst_id, srs_cnt in transitions:
            inst = db.execute(select(Instrument).where(Instrument.instrument_id == inst_id)).scalar()
            hists = db.execute(
                select(InstrumentSymbolHistory.symbol, InstrumentSymbolHistory.series, InstrumentSymbolHistory.isin, InstrumentSymbolHistory.valid_from)
                .where(InstrumentSymbolHistory.instrument_id == inst_id)
                .order_by(InstrumentSymbolHistory.valid_from)
            ).all()
            print(f"Instrument: {inst.name} | ISIN: {hists[0][2]} | Series History: {[(h[1], str(h[3])) for h in hists]}")

        print("\n=== 3. ISIN Integrity Check (No Cross-ISIN Instrument Collisions) ===")
        isin_collisions = db.execute(
            select(InstrumentSymbolHistory.instrument_id, func.count(func.distinct(InstrumentSymbolHistory.isin)))
            .group_by(InstrumentSymbolHistory.instrument_id)
            .having(func.count(func.distinct(InstrumentSymbolHistory.isin)) > 1)
        ).all()
        print(f"Instrument IDs mapped to multiple distinct ISINs (must be 0): {len(isin_collisions)}")

if __name__ == "__main__":
    audit()
