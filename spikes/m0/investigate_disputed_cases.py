#!/usr/bin/env python3
"""
investigate_disputed_cases.py - Deep dive into HAL, NESTLEIND, RITES, POLYCAB
and the 152 instruments / 154 transitions.
"""

from sqlalchemy import select, func, and_
from signal_atlas.db.session import get_db
from signal_atlas.db.models import Instrument, InstrumentSymbolHistory, DailyPriceRaw

def investigate():
    with get_db() as db:
        # 1. Inspect HAL, NESTLEIND, RITES, POLYCAB
        target_symbols = ["HAL", "NESTLEIND", "RITES", "POLYCAB", "TATASTEEL", "VERTOZ"]
        print("=== INVESTIGATING TARGET SYMBOLS ===")
        for sym in target_symbols:
            rows = db.execute(
                select(InstrumentSymbolHistory)
                .where(InstrumentSymbolHistory.symbol == sym)
                .order_by(InstrumentSymbolHistory.valid_from)
            ).scalars().all()
            print(f"\nSymbol: {sym} ({len(rows)} history rows):")
            for r in rows:
                print(f"  inst_id={r.instrument_id}, ISIN={r.isin}, series={r.series}, valid_from={r.valid_from}, source={r.source}")

        # 2. Find the 2 instruments with > 2 distinct ISINs (3 ISINs)
        print("\n=== INSTRUMENTS WITH > 2 DISTINCT ISINS ===")
        multi = db.execute(
            select(InstrumentSymbolHistory.instrument_id, func.count(func.distinct(InstrumentSymbolHistory.isin)))
            .group_by(InstrumentSymbolHistory.instrument_id)
            .having(func.count(func.distinct(InstrumentSymbolHistory.isin)) > 2)
        ).all()
        for inst_id, cnt in multi:
            inst = db.execute(select(Instrument).where(Instrument.instrument_id == inst_id)).scalar()
            isins = db.execute(
                select(func.distinct(InstrumentSymbolHistory.isin))
                .where(InstrumentSymbolHistory.instrument_id == inst_id)
            ).scalars().all()
            symbols = db.execute(
                select(func.distinct(InstrumentSymbolHistory.symbol))
                .where(InstrumentSymbolHistory.instrument_id == inst_id)
            ).scalars().all()
            print(f"Inst ID: {inst_id}, Name: {inst.name if inst else 'N/A'}, Symbols: {symbols}, ISIN count: {cnt}, ISINs: {isins}")

        # 3. Check POLYCAB and RITES in raw archives / daily_prices_raw
        print("\n=== CHECKING POLYCAB IN DB ===")
        poly_insts = db.execute(
            select(InstrumentSymbolHistory.instrument_id, InstrumentSymbolHistory.symbol, InstrumentSymbolHistory.isin, InstrumentSymbolHistory.series)
            .where(InstrumentSymbolHistory.symbol == "POLYCAB")
        ).all()
        for p in poly_insts:
            print("  POLYCAB:", p)

        print("\n=== CHECKING RITES IN DB ===")
        rites_insts = db.execute(
            select(InstrumentSymbolHistory.instrument_id, InstrumentSymbolHistory.symbol, InstrumentSymbolHistory.isin, InstrumentSymbolHistory.series)
            .where(InstrumentSymbolHistory.symbol == "RITES")
        ).all()
        for r in rites_insts:
            print("  RITES:", r)

if __name__ == "__main__":
    investigate()
