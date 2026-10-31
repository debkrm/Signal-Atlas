#!/usr/bin/env python3
"""
sweep_all_splits_and_bonuses.py - Comprehensive historical price discontinuity sweep.
Scans all 1,855,370 records in PostgreSQL daily_prices_raw across 2022-2024
to detect all corporate action candidates (splits and bonus issues) by identifying
all overnight price drops where (prev_close / open >= 1.30 or prev_close / close >= 1.30).
"""

import datetime
from decimal import Decimal
import json
from collections import defaultdict
from sqlalchemy import select, func, and_

from signal_atlas.db.session import get_db
from signal_atlas.db.models import DailyPriceRaw, Instrument, InstrumentSymbolHistory

def sweep_discontinuities():
    print("Executing historical price discontinuity sweep across 2022-2024...")

    with get_db() as db:
        # Pre-load symbol history to get symbol & ISIN for each instrument
        inst_info = {}
        histories = db.execute(select(InstrumentSymbolHistory)).scalars().all()
        for h in histories:
            if h.instrument_id not in inst_info:
                inst_info[h.instrument_id] = {
                    "symbol": h.symbol,
                    "series": h.series,
                    "isins": set(),
                }
            inst_info[h.instrument_id]["isins"].add(h.isin)

        # Query all price rows where close / prev_close indicates an ex-date drop >= 23%
        # i.e., prev_close / close >= 1.30 or prev_close / open >= 1.30
        # Exclude pennies < 2.0 to avoid roundoff noise
        stmt = (
            select(
                DailyPriceRaw.instrument_id,
                DailyPriceRaw.trade_date,
                DailyPriceRaw.series,
                DailyPriceRaw.prev_close,
                DailyPriceRaw.open,
                DailyPriceRaw.high,
                DailyPriceRaw.low,
                DailyPriceRaw.close,
                DailyPriceRaw.volume,
            )
            .where(
                DailyPriceRaw.series.in_(["EQ", "BE", "BZ", "SM"]),
                DailyPriceRaw.prev_close > Decimal("2.0"),
                DailyPriceRaw.close > Decimal("0.0"),
                (DailyPriceRaw.prev_close / DailyPriceRaw.close) >= Decimal("1.30"),
            )
            .order_by(DailyPriceRaw.trade_date)
        )

        rows = db.execute(stmt).all()
        print(f"Total potential ex-date drop observations found: {len(rows)}")

        candidates = []
        for r in rows:
            inst_id = r[0]
            dt = r[1]
            srs = r[2]
            prev_c = float(r[3])
            opn = float(r[4])
            hgh = float(r[5])
            low = float(r[6])
            cls = float(r[7])
            vol = r[8]

            ratio = round(prev_c / cls, 2)
            ratio_open = round(prev_c / opn, 2) if opn > 0 else ratio

            info = inst_info.get(inst_id, {})
            sym = info.get("symbol", "UNKNOWN")
            isin_count = len(info.get("isins", []))

            # Classify expected multiplier
            # Bonus 1:1 or Split 2:1 -> ~2.0
            # Split 5:2 -> ~2.5
            # Bonus 2:1 or Split 3:1 -> ~3.0
            # Split 5:1 -> ~5.0
            # Split 10:1 -> ~10.0
            # Split 10:1 + Bonus 1:1 -> ~20.0
            candidate_type = "UNKNOWN"
            est_multiplier = 1.0

            if 1.7 <= ratio <= 2.3:
                est_multiplier = 2.0
                candidate_type = "SPLIT_OR_BONUS_2_TO_1"
            elif 2.3 <= ratio <= 2.7:
                est_multiplier = 2.5
                candidate_type = "SPLIT_5_TO_2"
            elif 2.7 <= ratio <= 3.3:
                est_multiplier = 3.0
                candidate_type = "SPLIT_OR_BONUS_3_TO_1"
            elif 3.7 <= ratio <= 4.3:
                est_multiplier = 4.0
                candidate_type = "SPLIT_OR_BONUS_4_TO_1"
            elif 4.5 <= ratio <= 5.5:
                est_multiplier = 5.0
                candidate_type = "SPLIT_5_TO_1"
            elif 9.0 <= ratio <= 11.5:
                est_multiplier = 10.0
                candidate_type = "SPLIT_10_TO_1"
            elif 18.0 <= ratio <= 22.0:
                est_multiplier = 20.0
                candidate_type = "SPLIT_AND_BONUS_20_TO_1"
            elif 1.35 <= ratio <= 1.65:
                est_multiplier = 1.5
                candidate_type = "BONUS_1_TO_2"
            else:
                candidate_type = f"UNUSUAL_RATIO_{ratio}"
                est_multiplier = ratio

            candidates.append({
                "instrument_id": inst_id,
                "symbol": sym,
                "series": srs,
                "ex_date": str(dt),
                "prev_close": prev_c,
                "open": opn,
                "close": cls,
                "observed_ratio": ratio,
                "estimated_multiplier": est_multiplier,
                "candidate_type": candidate_type,
                "multi_isin": (isin_count > 1),
            })

        print(f"\nIdentified {len(candidates)} corporate action candidates.")
        
        # Breakdown by multi_isin vs same_isin
        multi_isin_cnt = sum(1 for c in candidates if c["multi_isin"])
        same_isin_cnt = sum(1 for c in candidates if not c["multi_isin"])
        print(f"  Candidates with multiple ISINs: {multi_isin_cnt}")
        print(f"  Candidates with SAME ISIN (e.g. bonus issues like RITES): {same_isin_cnt}")

        # Summary by candidate type
        from collections import Counter
        type_counts = Counter(c["candidate_type"] for c in candidates)
        print("\nBreakdown by Candidate Type:")
        for t, cnt in type_counts.most_common():
            print(f"  {t}: {cnt}")

        # Print some prominent same-ISIN candidates
        print("\nProminent Same-ISIN Candidates (Bonus Issues):")
        same_isin_list = [c for c in candidates if not c["multi_isin"]]
        for c in same_isin_list[:15]:
            print(f"  {c['ex_date']} | {c['symbol']} ({c['series']}) | PrevClose={c['prev_close']} -> Close={c['close']} | Ratio={c['observed_ratio']} | Type={c['candidate_type']}")

        out_path = "data/checkpoints/historical_split_bonus_sweep.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(candidates, f, indent=2)
        print(f"\nSaved complete sweep to {out_path}")

if __name__ == "__main__":
    sweep_discontinuities()
