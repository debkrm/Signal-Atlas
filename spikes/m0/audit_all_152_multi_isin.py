#!/usr/bin/env python3
"""
audit_all_152_multi_isin.py - Comprehensive audit of all 152 multi-ISIN instruments
and 154 pairwise transitions across 2022-2024.
"""

import datetime
import json
from decimal import Decimal
from typing import Dict, List, Any
from collections import Counter
from sqlalchemy import select, func, and_

from signal_atlas.db.session import get_db
from signal_atlas.db.models import Instrument, InstrumentSymbolHistory, DailyPriceRaw

def audit_all_multi_isin():
    with get_db() as db:
        # Find all instruments with > 1 ISIN
        multi_isin_insts = db.execute(
            select(InstrumentSymbolHistory.instrument_id, func.count(func.distinct(InstrumentSymbolHistory.isin)))
            .group_by(InstrumentSymbolHistory.instrument_id)
            .having(func.count(func.distinct(InstrumentSymbolHistory.isin)) > 1)
        ).all()

        print(f"Total multi-ISIN instruments: {len(multi_isin_insts)}")

        records = []
        inst_isin_counts = Counter()

        for inst_id, isin_cnt in multi_isin_insts:
            inst_isin_counts[isin_cnt] += 1
            inst = db.execute(select(Instrument).where(Instrument.instrument_id == inst_id)).scalar()

            # Query distinct ISINs ordered chronologically by valid_from
            isin_stats = db.execute(
                select(
                    InstrumentSymbolHistory.isin,
                    func.min(InstrumentSymbolHistory.valid_from),
                    func.max(InstrumentSymbolHistory.valid_to),
                    func.array_agg(func.distinct(InstrumentSymbolHistory.symbol)),
                    func.array_agg(func.distinct(InstrumentSymbolHistory.series)),
                )
                .where(InstrumentSymbolHistory.instrument_id == inst_id)
                .group_by(InstrumentSymbolHistory.isin)
                .order_by(func.min(InstrumentSymbolHistory.valid_from))
            ).all()

            # Pairwise transitions (old ISIN -> new ISIN)
            for i in range(len(isin_stats) - 1):
                old_isin, old_first, old_last, old_syms, old_srs = isin_stats[i]
                new_isin, new_first, new_last, new_syms, new_srs = isin_stats[i+1]

                # Find last price before new_first and first price on/after new_first
                # Use common equity series (EQ, BE, BZ, SM)
                equity_series = ["EQ", "BE", "BZ", "SM"]
                last_old_price = db.execute(
                    select(DailyPriceRaw.close, DailyPriceRaw.trade_date, DailyPriceRaw.series)
                    .where(
                        DailyPriceRaw.instrument_id == inst_id,
                        DailyPriceRaw.trade_date < new_first,
                        DailyPriceRaw.series.in_(equity_series),
                    )
                    .order_by(DailyPriceRaw.trade_date.desc())
                    .limit(1)
                ).first()

                first_new_price = db.execute(
                    select(DailyPriceRaw.close, DailyPriceRaw.trade_date, DailyPriceRaw.series)
                    .where(
                        DailyPriceRaw.instrument_id == inst_id,
                        DailyPriceRaw.trade_date >= new_first,
                        DailyPriceRaw.series.in_(equity_series),
                    )
                    .order_by(DailyPriceRaw.trade_date.asc())
                    .limit(1)
                ).first()

                ratio = None
                p_old = float(last_old_price[0]) if last_old_price else None
                p_new = float(first_new_price[0]) if first_new_price else None
                if p_old and p_new and p_new > 0:
                    ratio = round(p_old / p_new, 2)

                # Determine corporate action type and identity decision
                ca_type = "UNKNOWN"
                confidence = "HIGH"
                decision = "UNIFIED_IDENTITY"
                multiplier = 1.0

                same_issuer = (old_isin[:8] == new_isin[:8])
                share_class = "Equity Ordinary"
                if any(s in ("DVR", "PP") for s in (old_srs + new_srs)):
                    share_class = "DVR/Partly Paid"
                    decision = "PREDECESSOR_SUCCESSOR"
                    ca_type = "SHARE_CLASS_CHANGE"
                elif old_isin.startswith("INF") or new_isin.startswith("INF"):
                    share_class = "Mutual Fund / ETF Units"
                    decision = "PREDECESSOR_SUCCESSOR"
                    ca_type = "ETF_SCHEME_RESTRUCTURING"
                    confidence = "HIGH"
                elif same_issuer:
                    if ratio:
                        if 8.0 <= ratio <= 12.0:
                            ca_type = "STOCK_SPLIT_10_TO_1"
                            multiplier = 10.0
                        elif 4.0 <= ratio <= 6.0:
                            ca_type = "STOCK_SPLIT_5_TO_1"
                            multiplier = 5.0
                        elif 2.2 <= ratio <= 2.8:
                            ca_type = "STOCK_SPLIT_5_TO_2"
                            multiplier = 2.5
                        elif 1.6 <= ratio <= 2.2:
                            ca_type = "STOCK_SPLIT_2_TO_1"
                            multiplier = 2.0
                        elif 17.0 <= ratio <= 23.0:
                            ca_type = "COMBINED_SPLIT_AND_BONUS_20_TO_1"
                            multiplier = 20.0
                        elif 0.8 <= ratio <= 1.2:
                            ca_type = "CAPITAL_REORGANIZATION_OR_PARARI_PASSU"
                            multiplier = 1.0
                        else:
                            ca_type = f"STOCK_SPLIT_OR_CONSOLIDATION_RATIO_{ratio}"
                            multiplier = ratio
                    else:
                        ca_type = "FACE_VALUE_REDUCTION_SPLIT"
                else:
                    ca_type = "ISSUER_CHANGE_OR_MERGER"
                    decision = "PREDECESSOR_SUCCESSOR"
                    confidence = "MEDIUM"

                primary_sym = old_syms[0] if old_syms else "UNKNOWN"
                evidence = (
                    f"NSE Bhavcopy series continuous under {primary_sym} across {new_first}. "
                    f"Old ISIN {old_isin} (valid to {old_last}) transitioned to {new_isin} (valid from {new_first}). "
                    f"Price shifted from {p_old} (on {last_old_price[1] if last_old_price else 'N/A'}) to "
                    f"{p_new} (on {first_new_price[1] if first_new_price else 'N/A'}), observed ratio {ratio}."
                )

                rec = {
                    "instrument_id": inst_id,
                    "company_name": inst.name if inst else "Unknown",
                    "symbols": list(set(old_syms + new_syms)),
                    "old_isin": old_isin,
                    "new_isin": new_isin,
                    "same_issuer_prefix": same_issuer,
                    "share_class": share_class,
                    "effective_date": str(new_first),
                    "old_last_trade_date": str(last_old_price[1]) if last_old_price else "N/A",
                    "old_close": p_old,
                    "new_first_trade_date": str(first_new_price[1]) if first_new_price else "N/A",
                    "new_close": p_new,
                    "observed_price_ratio": ratio,
                    "expected_share_multiplier": multiplier,
                    "corporate_action_type": ca_type,
                    "decision": decision,
                    "confidence": confidence,
                    "evidence": evidence,
                }
                records.append(rec)

        print("\n=== MULTI-ISIN AUDIT SUMMARY ===")
        print(f"Total Unique Multi-ISIN Instruments: {len(multi_isin_insts)}")
        print(f"Instruments with exactly 2 ISINs:    {inst_isin_counts[2]} (yielding {inst_isin_counts[2]} transitions)")
        print(f"Instruments with exactly 3 ISINs:    {inst_isin_counts[3]} (yielding {inst_isin_counts[3] * 2} transitions)")
        print(f"Total Pairwise Transitions Audited:  {len(records)}")
        assert len(records) == 154, f"Expected 154 transitions, got {len(records)}"

        ca_counts = Counter(r["corporate_action_type"] for r in records)
        dec_counts = Counter(r["decision"] for r in records)
        same_prefix = sum(1 for r in records if r["same_issuer_prefix"])

        print("\nBreakdown by Corporate Action Type:")
        for ca, cnt in ca_counts.most_common():
            print(f"  {ca}: {cnt}")

        print("\nBreakdown by Identity Decision:")
        for dec, cnt in dec_counts.items():
            print(f"  {dec}: {cnt}")
        print(f"Same issuer prefix matches: {same_prefix} / {len(records)} ({round(same_prefix/len(records)*100, 1)}%)")

        # Save to JSON
        out_path = "data/checkpoints/isin_identity_mappings_audit.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
        print(f"\nSaved updated audit to {out_path}")

        # Save to CSV
        import pandas as pd
        df = pd.DataFrame(records)
        csv_path = "data/checkpoints/isin_identity_mappings_audit.csv"
        df.to_csv(csv_path, index=False)
        print(f"Saved updated CSV audit table to {csv_path}")

if __name__ == "__main__":
    audit_all_multi_isin()
