from signal_atlas.db.session import get_db
from signal_atlas.db.models import Instrument, InstrumentSymbolHistory
from sqlalchemy import func, select

with get_db() as db:
    collisions = db.execute(
        select(InstrumentSymbolHistory.instrument_id, func.count(func.distinct(InstrumentSymbolHistory.isin)))
        .group_by(InstrumentSymbolHistory.instrument_id)
        .having(func.count(func.distinct(InstrumentSymbolHistory.isin)) > 1)
        .limit(10)
    ).all()

    for inst_id, cnt in collisions:
        inst = db.execute(select(Instrument).where(Instrument.instrument_id == inst_id)).scalar()
        hists = db.execute(
            select(InstrumentSymbolHistory.symbol, InstrumentSymbolHistory.series, InstrumentSymbolHistory.isin, InstrumentSymbolHistory.valid_from)
            .where(InstrumentSymbolHistory.instrument_id == inst_id)
            .order_by(InstrumentSymbolHistory.valid_from)
        ).all()
        print(f"\nInstrument: {inst.name if inst else 'None'} ({inst_id}) | Distinct ISINs: {cnt}")
        for h in hists:
            print(f"  Symbol: {h[0]}, Series: {h[1]}, ISIN: {h[2]}, ValidFrom: {h[3]}")
