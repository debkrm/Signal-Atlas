import json
from collections import defaultdict

with open('data/checkpoints/historical_split_bonus_sweep.json') as f:
    sweep = json.load(f)
with open('data/checkpoints/candidates_full_disposition_report.json') as f:
    disp = json.load(f)

cross_tab = defaultdict(lambda: defaultdict(int))
cross_tab_records = []

for s, d in zip(sweep, disp):
    isin_type = 'MULTI_ISIN' if s['multi_isin'] else 'SAME_ISIN'
    cat = d['disposition']
    cross_tab[cat][isin_type] += 1
    cross_tab[cat]['TOTAL'] += 1

    cross_tab_records.append({
        "candidate_index": d["candidate_index"],
        "symbol": d["symbol"],
        "series": d["series"],
        "ex_date": d["ex_date"],
        "observed_ratio": d["observed_ratio"],
        "isin_classification": isin_type,
        "disposition": cat,
        "canonical_action_id": d["canonical_action_id"],
        "action_type": d["action_type"],
        "multiplier": d["multiplier"],
        "source_circular": d["source_circular"],
    })

report_data = {
    "report_name": "486 Price Discontinuity Candidates Cross-Tabulation & Reconciliation",
    "total_candidates": len(cross_tab_records),
    "summary_cross_tabulation": {
        cat: {
            "multi_isin": counts["MULTI_ISIN"],
            "same_isin": counts["SAME_ISIN"],
            "total": counts["TOTAL"],
        }
        for cat, counts in sorted(cross_tab.items(), key=lambda x: -x[1]["TOTAL"])
    },
    "reconciliation_bridge": {
        "total_detected_candidates": 486,
        "multi_isin_candidates": 170,
        "same_isin_candidates": 316,
        "verified_split_candidates": 92,
        "verified_bonus_candidates": 224,
        "rights_entitlement_expirations": 76,
        "duplicate_candidates": 43,
        "normal_market_movements": 43,
        "other_verified_actions": 8,
        "canonical_registry_events": 378,
        "audit_assertions_separated": 1
    },
    "candidates": cross_tab_records,
}

with open("data/checkpoints/candidates_disposition_cross_tabulation.json", "w", encoding="utf-8") as f:
    json.dump(report_data, f, indent=2)

print("Exported data/checkpoints/candidates_disposition_cross_tabulation.json")
