from signal_atlas.db.session import get_db
from signal_atlas.db.models import Instrument, InstrumentSymbolHistory
from sqlalchemy import func, select

def analyze():
    with get_db() as db:
        collisions = db.execute(
            select(InstrumentSymbolHistory.instrument_id, func.count(func.distinct(InstrumentSymbolHistory.isin)))
            .group_by(InstrumentSymbolHistory.instrument_id)
            .having(func.count(func.distinct(InstrumentSymbolHistory.isin)) > 1)
        ).all()

        print(f"Total instruments with > 1 ISIN across 2022-2024: {len(collisions)}")

        sample_analyses = []
        for inst_id, cnt in collisions[:20]:
            inst = db.execute(select(Instrument).where(Instrument.instrument_id == inst_id)).scalar()
            hists = db.execute(
                select(InstrumentSymbolHistory.symbol, InstrumentSymbolHistory.isin, func.min(InstrumentSymbolHistory.valid_from))
                .where(InstrumentSymbolHistory.instrument_id == inst_id)
                .group_by(InstrumentSymbolHistory.symbol, InstrumentSymbolHistory.isin)
                .order_by(func.min(InstrumentSymbolHistory.valid_from))
            ).all()

            symbols = {h[0] for h in hists}
            isins = [h[1] for h in hists]
            sample_analyses.append({
                "instrument_id": inst_id,
                "name": inst.name if inst else "Unknown",
                "symbols": list(symbols),
                "isins": isins,
                "timeline": [(h[0], h[1], str(h[2])) for h in hists],
            })

        for s in sample_analyses:
            print(f"\n[{s['name']}] (Symbols: {s['symbols']})")
            for sym, isin, dt in s["timeline"]:
                print(f"   -> {dt}: Symbol={sym}, ISIN={isin}")

if __name__ == "__main__":
    analyze()
