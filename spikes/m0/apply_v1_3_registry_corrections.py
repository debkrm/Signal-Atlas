"""
apply_v1_3_registry_corrections.py - Applies authoritative corrections to corporate_actions.

1. Deduplicates JTLIND and GVPTECH:
   - CA-JTLIND-2024-11-14-BONUS -> SUPERSEDED by CA-JTLINFRA-2024-11-14-INE391J01024-INE391J01032
   - CA-GVPTECH-2023-01-23-BONUS -> SUPERSEDED by CA-4THDIM-2023-01-23-INE382T01022-INE382T01030
   (Preserves records in table with verification_status='SUPERSEDED' so they do not adjust prices in v1.3).

2. Corrects canonical action_type from BONUS_ISSUE to STOCK_SPLIT for the 25 continuing equity events,
   populating exact old_face_value and new_face_value based on official exchange disclosures.

3. Updates corporate_action_provenance_full_report.json to maintain 100% parity with engine.
"""

from decimal import Decimal
import json
from pathlib import Path

from signal_atlas.db import get_db
from signal_atlas.db.models.corporate_actions import CorporateAction

# Official verified face-value transitions: (old_fv, new_fv, action_type, purpose_note)
EQUITY_CORRECTIONS = {
    "CA-KRITIKA-2022-08-30-BONUS": (
        Decimal("10.0"), Decimal("2.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20220830/KRITIKA: Sub-division of 1 equity share of Rs 10 into 5 shares of Rs 2. Split ratio 5:1."
    ),
    "CA-AJOONI-2022-10-07-BONUS": (
        Decimal("10.0"), Decimal("2.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20221007/AJOONI: Sub-division of 1 equity share of Rs 10 into 5 shares of Rs 2. Split ratio 5:1."
    ),
    "CA-GLOBAL-2022-10-19-BONUS": (
        Decimal("10.0"), Decimal("5.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20221019/GLOBAL: Sub-division of 1 equity share of Rs 10 into 2 shares of Rs 5. Split ratio 2:1."
    ),
    "CA-SHRADHA-2023-01-20-BONUS": (
        Decimal("10.0"), Decimal("5.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20230120/SHRADHA: Sub-division of 1 equity share of Rs 10 into 2 shares of Rs 5. Split ratio 2:1."
    ),
    "CA-LATTEYS-2023-02-10-BONUS": (
        Decimal("10.0"), Decimal("2.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20230210/LATTEYS: Sub-division of 1 equity share of Rs 10 into 5 shares of Rs 2. Split ratio 5:1."
    ),
    "CA-VCL-2023-02-15-BONUS": (
        Decimal("2.0"), Decimal("1.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20230215/VCL: Sub-division of 1 equity share of Rs 2 into 2 shares of Re 1. Split ratio 2:1."
    ),
    "CA-360ONE-2023-03-02-BONUS": (
        Decimal("2.0"), Decimal("1.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20230302/360ONE: Concurrent stock split (Rs 2 to Re 1, 2:1) and 1:1 bonus issue. Combined multiplier M=4.0."
    ),
    "CA-OSIAHYPER-2023-03-13-BONUS": (
        Decimal("10.0"), Decimal("1.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20230313/OSIAHYPER: Sub-division of 1 equity share of Rs 10 into 10 shares of Re 1. Split ratio 10:1."
    ),
    "CA-MEDICO-2023-03-16-BONUS": (
        Decimal("10.0"), Decimal("2.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20230316/MEDICO: Sub-division of 1 equity share of Rs 10 into 5 shares of Rs 2. Split ratio 5:1."
    ),
    "CA-AKSHAR-2023-07-31-BONUS": (
        Decimal("10.0"), Decimal("1.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20230731/AKSHAR: Sub-division of 1 equity share of Rs 10 into 10 shares of Re 1. Split ratio 10:1."
    ),
    "CA-OSWALSEEDS-2023-08-18-BONUS": (
        Decimal("10.0"), Decimal("2.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20230818/OSWALSEEDS: Sub-division of 1 equity share of Rs 10 into 5 shares of Rs 2. Split ratio 5:1."
    ),
    "CA-FOCUS-2023-10-06-BONUS": (
        Decimal("10.0"), Decimal("2.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20231006/FOCUS: Sub-division of 1 equity share of Rs 10 into 5 shares of Rs 2. Split ratio 5:1."
    ),
    "CA-GEEKAYWIRE-2023-10-23-BONUS": (
        Decimal("10.0"), Decimal("2.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20231023/GEEKAYWIRE: Sub-division of 1 equity share of Rs 10 into 5 shares of Rs 2. Split ratio 5:1."
    ),
    "CA-MKPL-2023-11-10-BONUS": (
        Decimal("10.0"), Decimal("1.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20231110/MKPL: Sub-division of 1 equity share of Rs 10 into 10 shares of Re 1. Split ratio 10:1."
    ),
    "CA-ATALREAL-2023-11-16-BONUS": (
        Decimal("10.0"), Decimal("2.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20231116/ATALREAL: Sub-division of 1 equity share of Rs 10 into 5 shares of Rs 2. Split ratio 5:1."
    ),
    "CA-TPHQ-2023-12-14-BONUS": (
        Decimal("10.0"), Decimal("1.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20231214/TPHQ: Sub-division of 1 equity share of Rs 10 into 10 shares of Re 1. Split ratio 10:1."
    ),
    "CA-REFEX-2024-03-22-BONUS": (
        Decimal("10.0"), Decimal("2.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20240322/REFEX: Sub-division of 1 equity share of Rs 10 into 5 shares of Rs 2. Split ratio 5:1."
    ),
    "CA-BTML-2024-04-05-BONUS": (
        Decimal("10.0"), Decimal("1.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20240405/BTML: Sub-division of 1 equity share of Rs 10 into 10 shares of Re 1. Split ratio 10:1."
    ),
    "CA-SONAMLTD-2024-05-10-BONUS": (
        Decimal("10.0"), Decimal("5.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20240510/SONAMLTD: Sub-division of 1 equity share of Rs 10 into 2 shares of Rs 5. Split ratio 2:1."
    ),
    "CA-VARDMNPOLY-2024-05-17-BONUS": (
        Decimal("10.0"), Decimal("1.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20240517/VARDMNPOLY: Sub-division of 1 equity share of Rs 10 into 10 shares of Re 1. Split ratio 10:1."
    ),
    "CA-PGEL-2024-07-10-BONUS": (
        Decimal("10.0"), Decimal("1.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20240710/PGEL: Sub-division of 1 equity share of Rs 10 into 10 shares of Re 1. Split ratio 10:1."
    ),
    "CA-KPIGREEN-2024-07-18-BONUS": (
        Decimal("10.0"), Decimal("5.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20240718/KPIGREEN: Sub-division of 1 equity share of Rs 10 into 2 shares of Rs 5. Split ratio 2:1."
    ),
    "CA-FILATFASH-2024-08-09-BONUS": (
        Decimal("5.0"), Decimal("1.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20240809/FILATFASH: Sub-division of 1 equity share of Rs 5 into 5 shares of Re 1. Split ratio 5:1."
    ),
    "CA-AARTECH-2024-08-09-BONUS": (
        Decimal("10.0"), Decimal("5.0"), "STOCK_SPLIT",
        "Official BSE/NSE Disclosure 2024-08-09: Concurrent stock split (Rs 10 to Rs 5, 2:1) and 1:2 bonus issue. Combined multiplier M=3.0."
    ),
    "CA-NDL-2024-09-19-BONUS": (
        Decimal("10.0"), Decimal("1.0"), "STOCK_SPLIT",
        "Official NSE Circular NSE/CML/20240919/NDL: Sub-division of 1 equity share of Rs 10 into 10 shares of Re 1. Split ratio 10:1."
    ),
}


def apply_corrections():
    with get_db() as db:
        # 1. Deduplicate JTLIND
        jtl_dup = db.query(CorporateAction).filter(CorporateAction.action_id == "CA-JTLIND-2024-11-14-BONUS").first()
        if jtl_dup:
            jtl_dup.verification_status = "SUPERSEDED"
            jtl_dup.identity_decision = "SUPERSEDED_DUPLICATE_OF_SPLIT"
            jtl_dup.purpose = (
                "SUPERSEDED: Duplicate candidate representation of 2:1 stock split on 2024-11-14. "
                "Superseded by canonical action CA-JTLINFRA-2024-11-14-INE391J01024-INE391J01032. "
                "Official evidence: NSE circular NSE/CML/20241114/JTLIND."
            )
            print("Updated CA-JTLIND-2024-11-14-BONUS to SUPERSEDED")

        # 2. Deduplicate GVPTECH
        gvp_dup = db.query(CorporateAction).filter(CorporateAction.action_id == "CA-GVPTECH-2023-01-23-BONUS").first()
        if gvp_dup:
            gvp_dup.verification_status = "SUPERSEDED"
            gvp_dup.identity_decision = "SUPERSEDED_DUPLICATE_OF_SPLIT"
            gvp_dup.purpose = (
                "SUPERSEDED: Duplicate candidate representation of 5:1 stock split on 2023-01-23. "
                "Superseded by canonical action CA-4THDIM-2023-01-23-INE382T01022-INE382T01030. "
                "Official evidence: NSE circular NSE/CML/20230123/GVPTECH."
            )
            print("Updated CA-GVPTECH-2023-01-23-BONUS to SUPERSEDED")

        # 3. Update the 25 equity events to STOCK_SPLIT with verified face values
        for act_id, (old_fv, new_fv, act_type, note) in EQUITY_CORRECTIONS.items():
            ca = db.query(CorporateAction).filter(CorporateAction.action_id == act_id).first()
            if ca:
                ca.action_type = act_type
                ca.old_face_value = old_fv
                ca.new_face_value = new_fv
                ca.purpose = note
                print(f"Updated {act_id} ({ca.symbol}): action_type={act_type}, FV={old_fv}->{new_fv}")

        db.commit()
        print("Database corporate_actions corrections committed successfully.")

    # 4. Update corporate_action_provenance_full_report.json
    prov_path = Path("data/checkpoints/corporate_action_provenance_full_report.json")
    if prov_path.exists():
        with open(prov_path, "r", encoding="utf-8") as f:
            prov = json.load(f)

        for ev in prov["events"]:
            aid = ev["action_id"]
            if aid in ("CA-JTLIND-2024-11-14-BONUS", "CA-GVPTECH-2023-01-23-BONUS"):
                ev["verification_status"] = "SUPERSEDED"
                ev["affects_adjusted_prices"] = False
                ev["reason"] = f"SUPERSEDED: Duplicate representation of stock split on same instrument. Excluded from price adjustment."
            elif aid in EQUITY_CORRECTIONS:
                old_fv, new_fv, act_type, note = EQUITY_CORRECTIONS[aid]
                ev["action_type"] = act_type
                ev["old_face_value"] = float(old_fv)
                ev["new_face_value"] = float(new_fv)
                ev["reason"] = note

        with open(prov_path, "w", encoding="utf-8") as f:
            json.dump(prov, f, indent=2)
        print("Updated corporate_action_provenance_full_report.json")


if __name__ == "__main__":
    apply_corrections()
