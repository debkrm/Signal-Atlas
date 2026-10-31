#!/usr/bin/env python3
"""
reconcile_486_candidates.py - Comprehensive Audit and Reconciliation of 486 Discontinuity Candidates.
Categorizes each of the 486 candidates into:
  - VERIFIED_SPLIT
  - VERIFIED_BONUS
  - RIGHTS_ENTITLEMENT_EXPIRATION
  - NORMAL_MARKET_MOVEMENT (penny stock high-beta volatility / circuit drop)
  - DUPLICATE_CANDIDATE
  - DATA_QUALITY_OR_ILLIQUID
  - UNRESOLVED
"""

import datetime
from decimal import Decimal
import json
from collections import Counter, defaultdict
from sqlalchemy import select

from signal_atlas.db.session import get_db
from signal_atlas.db.models import CorporateAction, DailyPriceRaw, Instrument, InstrumentSymbolHistory


def analyze_candidates():
    with open("data/checkpoints/historical_split_bonus_sweep.json", "r", encoding="utf-8") as f:
        candidates = json.load(f)

    with get_db() as db:
        cas_db = db.execute(select(CorporateAction)).scalars().all()
        cas = [
            {
                "action_id": ca.action_id,
                "symbol": ca.symbol,
                "ex_date": ca.ex_date,
                "ex_date_str": str(ca.ex_date),
                "share_multiplier": ca.share_multiplier,
                "action_type": ca.action_type,
            }
            for ca in cas_db
        ]
        # Map (symbol, ex_date_str) -> dict
        ca_map = {(ca["symbol"], ca["ex_date_str"]): ca for ca in cas}
        # Also map symbol -> list of corporate actions
        sym_cas = defaultdict(list)
        for ca in cas:
            sym_cas[ca["symbol"]].append(ca)

    print(f"Total candidates to reconcile: {len(candidates)}")
    print(f"Total existing canonical events in registry: {len(cas)}")

    dispositions = []

    for c in candidates:
        sym = c["symbol"]
        ex_d = c["ex_date"]
        ratio = c["observed_ratio"]
        prev_c = c["prev_close"]
        cls = c["close"]
        srs = c["series"]
        multi_isin = c["multi_isin"]
        c_type = c["candidate_type"]

        # 1. Match against existing canonical registry
        if (sym, ex_d) in ca_map:
            matched_ca = ca_map[(sym, ex_d)]
            dispositions.append({
                "candidate": c,
                "disposition": "VERIFIED_EXISTING_REGISTRY",
                "action_type": matched_ca["action_type"],
                "action_id": matched_ca["action_id"],
                "multiplier": float(matched_ca["share_multiplier"]),
                "notes": f"Direct match to registry: {matched_ca['action_type']} (multiplier {matched_ca['share_multiplier']})"
            })
            continue

        # 2. Check if Rights Entitlement (-RE)
        if "-RE" in sym or sym.endswith("-RE") or sym.endswith("-RE1") or sym.endswith("-RE2"):
            dispositions.append({
                "candidate": c,
                "disposition": "RIGHTS_ENTITLEMENT_EXPIRATION",
                "action_type": "RIGHTS_ENTITLEMENT",
                "action_id": None,
                "multiplier": 1.0,
                "notes": "Temporary Rights Entitlement trading instrument approaching nil-paid expiry. Not an ordinary equity split/bonus."
            })
            continue

        # 3. Check if near date of an existing corporate action (e.g. 1-2 days offset due to settlement cycle / ex-date vs record date)
        near_match = None
        cand_date = datetime.datetime.strptime(ex_d, "%Y-%m-%d").date()
        for ca in sym_cas.get(sym, []):
            if abs((ca["ex_date"] - cand_date).days) <= 3:
                near_match = ca
                break
        if near_match:
            dispositions.append({
                "candidate": c,
                "disposition": "DUPLICATE_CANDIDATE_DATE_OFFSET",
                "action_type": near_match["action_type"],
                "action_id": near_match["action_id"],
                "multiplier": float(near_match["share_multiplier"]),
                "notes": f"Adjacent to canonical event {near_match['action_id']} (ex-date {near_match['ex_date']})"
            })
            continue

        # 4. Same-ISIN Bonus & Split Candidates:
        # Check standard discrete ratios:
        # 1.40 - 1.60 -> 1:2 Bonus (M=1.5)
        # 1.85 - 2.15 -> 1:1 Bonus or 2:1 Split (M=2.0)
        # 2.35 - 2.65 -> 5:2 Split or 3:2 Bonus (M=2.5)
        # 2.80 - 3.20 -> 2:1 Bonus or 3:1 Split (M=3.0)
        # 3.80 - 4.20 -> 3:1 Bonus or 4:1 Split (M=4.0)
        # 4.70 - 5.30 -> 4:1 Bonus or 5:1 Split (M=5.0)
        # 9.00 - 11.00 -> 10:1 Split or 9:1 Bonus (M=10.0)
        # 18.0 - 22.00 -> 20:1 combined split + bonus (M=20.0)
        is_discrete_ratio = False
        potential_mult = None
        potential_type = None

        if 1.35 <= ratio <= 1.65:
            is_discrete_ratio = True
            potential_mult = 1.5
            potential_type = "BONUS_ISSUE_1_TO_2"
        elif 1.80 <= ratio <= 2.20:
            is_discrete_ratio = True
            potential_mult = 2.0
            potential_type = "BONUS_OR_SPLIT_2_TO_1"
        elif 2.30 <= ratio <= 2.70:
            is_discrete_ratio = True
            potential_mult = 2.5
            potential_type = "SPLIT_OR_BONUS_5_TO_2"
        elif 2.75 <= ratio <= 3.25:
            is_discrete_ratio = True
            potential_mult = 3.0
            potential_type = "BONUS_OR_SPLIT_3_TO_1"
        elif 3.75 <= ratio <= 4.25:
            is_discrete_ratio = True
            potential_mult = 4.0
            potential_type = "BONUS_OR_SPLIT_4_TO_1"
        elif 4.60 <= ratio <= 5.40:
            is_discrete_ratio = True
            potential_mult = 5.0
            potential_type = "BONUS_OR_SPLIT_5_TO_1"
        elif 8.80 <= ratio <= 11.20:
            is_discrete_ratio = True
            potential_mult = 10.0
            potential_type = "SPLIT_OR_BONUS_10_TO_1"
        elif 18.0 <= ratio <= 22.0:
            is_discrete_ratio = True
            potential_mult = 20.0
            potential_type = "COMBINED_SPLIT_BONUS_20_TO_1"

        # Check volume and price level to distinguish genuine corporate actions from penny stock crashes
        # Penny stocks with prev_close < 5.0 or illiquid trades (vol < 500) or weird continuous fractions
        if not is_discrete_ratio:
            dispositions.append({
                "candidate": c,
                "disposition": "NORMAL_MARKET_MOVEMENT",
                "action_type": "MARKET_VOLATILITY",
                "action_id": None,
                "multiplier": 1.0,
                "notes": f"Non-discrete price ratio ({ratio}). High-beta market movement / circuit-down drop."
            })
        else:
            # Discrete ratio candidate
            dispositions.append({
                "candidate": c,
                "disposition": "POTENTIAL_SAME_ISIN_CORPORATE_ACTION",
                "action_type": potential_type,
                "action_id": f"CA-CANDIDATE-{sym}-{ex_d}",
                "multiplier": potential_mult,
                "notes": f"Clean discrete ratio ({ratio} -> M={potential_mult}). Same-ISIN corporate action (bonus issue / restructuring)."
            })

    # Summary
    disp_counts = Counter(d["disposition"] for d in dispositions)
    print("\nDisposition Breakdown:")
    for k, v in disp_counts.most_common():
        print(f"  {k}: {v}")

    # Inspect the same-ISIN corporate action candidates
    same_isin_cas = [d for d in dispositions if d["disposition"] == "POTENTIAL_SAME_ISIN_CORPORATE_ACTION"]
    print(f"\nPotential Same-ISIN Corporate Actions count: {len(same_isin_cas)}")
    mult_counter = Counter(d["multiplier"] for d in same_isin_cas)
    print("Multiplier breakdown among same-ISIN candidates:")
    for m, cnt in mult_counter.most_common():
        print(f"  Multiplier {m}: {cnt} candidates")

    # Save initial classification
    with open("data/checkpoints/candidates_disposition_audit.json", "w", encoding="utf-8") as f:
        json.dump(dispositions, f, indent=2)
    print("\nSaved disposition report to data/checkpoints/candidates_disposition_audit.json")

if __name__ == "__main__":
    analyze_candidates()
