"""
apply_v1_4_compound_components.py - Milestone Phase 1B-ii.2.6.

Decomposes the composite split-plus-bonus actions for 360ONE and AARTECH into
distinct component records matching the GOLDSTAR / VERTOZ canonical pattern:

1. 360ONE (ex-date: 2023-03-02):
   - Component A: CA-360ONE-2023-03-02-STOCK_SPLIT (type: STOCK_SPLIT, M=2.0, FV Rs 2 -> Rs 1)
   - Component B: CA-360ONE-2023-03-02-BONUS_ISSUE (type: BONUS_ISSUE, M=2.0, Ratio 1:1)
   - Combined factor: 2.0 * 2.0 = 4.0
   - Composite record CA-360ONE-2023-03-02-BONUS is marked SUPERSEDED.

2. AARTECH (ex-date: 2024-08-09):
   - Component A: CA-AARTECH-2024-08-09-STOCK_SPLIT (type: STOCK_SPLIT, M=2.0, FV Rs 10 -> Rs 5)
   - Component B: CA-AARTECH-2024-08-09-BONUS_ISSUE (type: BONUS_ISSUE, M=1.5, Ratio 1:2)
   - Combined factor: 2.0 * 1.5 = 3.0
   - Composite record CA-AARTECH-2024-08-09-BONUS is marked SUPERSEDED.
"""

import datetime
from decimal import Decimal
import json
from pathlib import Path
from sqlalchemy import text

from signal_atlas.db.session import get_db


def apply_compound_component_modelling():
    with get_db() as db:
        print("=== Decomposing Composite Actions for 360ONE and AARTECH ===")

        # 1. Supersede original composite records
        supersede_sql = text("""
            UPDATE corporate_actions
            SET verification_status = 'SUPERSEDED',
                identity_decision = 'SUPERSEDED_DECOMPOSED',
                purpose = purpose || ' [SUPERSEDED: Decomposed into canonical component records: STOCK_SPLIT and BONUS_ISSUE in v1.4]'
            WHERE action_id IN ('CA-360ONE-2023-03-02-BONUS', 'CA-AARTECH-2024-08-09-BONUS')
        """)
        sup_count = db.execute(supersede_sql).rowcount
        print(f"Marked {sup_count} composite records as SUPERSEDED.")

        # 2. Insert component records
        components = [
            # 360ONE Split
            {
                "action_id": "CA-360ONE-2023-03-02-STOCK_SPLIT",
                "instrument_id": "d91374bc-d696-49c1-9b4f-f3ac825f3d64",
                "symbol": "360ONE",
                "series": "EQ",
                "action_type": "STOCK_SPLIT",
                "ex_date": datetime.date(2023, 3, 2),
                "record_date": datetime.date(2023, 3, 2),
                "old_isin": "INE466L01020",
                "new_isin": "INE466L01038",
                "old_face_value": Decimal("2.00"),
                "new_face_value": Decimal("1.00"),
                "old_share_qty": None,
                "new_share_qty": None,
                "share_multiplier": Decimal("2.000000"),
                "cash_entitlement": None,
                "purpose": "Sub-division of 1 equity share of face value Rs 2 into 2 equity shares of face value Re 1 (Concurrent with 1:1 Bonus Issue, Event Group: EVT-360ONE-20230302)",
                "issuing_organisation": "NSE",
                "source_type": "EXCHANGE_CIRCULAR",
                "source_circular": "NSE/CML/20230302/360ONE",
                "source_url": "https://nsearchives.nseindia.com/content/circulars/CML_360ONE_20230302.pdf",
                "identity_decision": "UNIFIED_IDENTITY",
                "verification_status": "VERIFIED",
                "parser_version": "v1.4",
            },
            # 360ONE Bonus
            {
                "action_id": "CA-360ONE-2023-03-02-BONUS_ISSUE",
                "instrument_id": "d91374bc-d696-49c1-9b4f-f3ac825f3d64",
                "symbol": "360ONE",
                "series": "EQ",
                "action_type": "BONUS_ISSUE",
                "ex_date": datetime.date(2023, 3, 2),
                "record_date": datetime.date(2023, 3, 2),
                "old_isin": "INE466L01038",
                "new_isin": "INE466L01038",
                "old_face_value": None,
                "new_face_value": None,
                "old_share_qty": Decimal("1.00"),
                "new_share_qty": Decimal("1.00"),
                "share_multiplier": Decimal("2.000000"),
                "cash_entitlement": None,
                "purpose": "Bonus issue of 1 equity share of Re 1 for every 1 fully paid-up equity share held (Concurrent with 2:1 Stock Split, Event Group: EVT-360ONE-20230302)",
                "issuing_organisation": "NSE",
                "source_type": "EXCHANGE_CIRCULAR",
                "source_circular": "NSE/CML/20230302/360ONE",
                "source_url": "https://nsearchives.nseindia.com/content/circulars/CML_360ONE_20230302.pdf",
                "identity_decision": "UNIFIED_IDENTITY",
                "verification_status": "VERIFIED",
                "parser_version": "v1.4",
            },
            # AARTECH Split
            {
                "action_id": "CA-AARTECH-2024-08-09-STOCK_SPLIT",
                "instrument_id": "743db139-4298-426e-b5c3-51e3bafdd957",
                "symbol": "AARTECH",
                "series": "EQ",
                "action_type": "STOCK_SPLIT",
                "ex_date": datetime.date(2024, 8, 9),
                "record_date": datetime.date(2024, 8, 9),
                "old_isin": "INE01C001018",
                "new_isin": "INE01C001026",
                "old_face_value": Decimal("10.00"),
                "new_face_value": Decimal("5.00"),
                "old_share_qty": None,
                "new_share_qty": None,
                "share_multiplier": Decimal("2.000000"),
                "cash_entitlement": None,
                "purpose": "Sub-division of 1 equity share of face value Rs 10 into 2 equity shares of face value Rs 5 (Concurrent with 1:2 Bonus Issue, Event Group: EVT-AARTECH-20240809)",
                "issuing_organisation": "NSE",
                "source_type": "EXCHANGE_CIRCULAR",
                "source_circular": "NSE/CML/20240809/AARTECH",
                "source_url": "https://nsearchives.nseindia.com/content/circulars/CML_AARTECH_20240809.pdf",
                "identity_decision": "UNIFIED_IDENTITY",
                "verification_status": "VERIFIED",
                "parser_version": "v1.4",
            },
            # AARTECH Bonus
            {
                "action_id": "CA-AARTECH-2024-08-09-BONUS_ISSUE",
                "instrument_id": "743db139-4298-426e-b5c3-51e3bafdd957",
                "symbol": "AARTECH",
                "series": "EQ",
                "action_type": "BONUS_ISSUE",
                "ex_date": datetime.date(2024, 8, 9),
                "record_date": datetime.date(2024, 8, 9),
                "old_isin": "INE01C001026",
                "new_isin": "INE01C001026",
                "old_face_value": None,
                "new_face_value": None,
                "old_share_qty": Decimal("2.00"),
                "new_share_qty": Decimal("1.00"),
                "share_multiplier": Decimal("1.500000"),
                "cash_entitlement": None,
                "purpose": "Bonus issue of 1 equity share of Rs 5 for every 2 existing equity shares of Rs 5 held (Concurrent with 2:1 Stock Split, Event Group: EVT-AARTECH-20240809)",
                "issuing_organisation": "NSE",
                "source_type": "EXCHANGE_CIRCULAR",
                "source_circular": "NSE/CML/20240809/AARTECH",
                "source_url": "https://nsearchives.nseindia.com/content/circulars/CML_AARTECH_20240809.pdf",
                "identity_decision": "UNIFIED_IDENTITY",
                "verification_status": "VERIFIED",
                "parser_version": "v1.4",
            },
        ]

        insert_sql = text("""
            INSERT INTO corporate_actions (
                action_id, instrument_id, symbol, series, action_type, ex_date, record_date,
                old_isin, new_isin, old_face_value, new_face_value, old_share_qty, new_share_qty,
                share_multiplier, cash_entitlement, purpose, issuing_organisation, source_type,
                source_circular, source_url, identity_decision, verification_status, parser_version
            ) VALUES (
                :action_id, :instrument_id, :symbol, :series, :action_type, :ex_date, :record_date,
                :old_isin, :new_isin, :old_face_value, :new_face_value, :old_share_qty, :new_share_qty,
                :share_multiplier, :cash_entitlement, :purpose, :issuing_organisation, :source_type,
                :source_circular, :source_url, :identity_decision, :verification_status, :parser_version
            )
            ON CONFLICT (action_id) DO UPDATE SET
                action_type = EXCLUDED.action_type,
                share_multiplier = EXCLUDED.share_multiplier,
                old_face_value = EXCLUDED.old_face_value,
                new_face_value = EXCLUDED.new_face_value,
                old_share_qty = EXCLUDED.old_share_qty,
                new_share_qty = EXCLUDED.new_share_qty,
                purpose = EXCLUDED.purpose,
                verification_status = EXCLUDED.verification_status,
                identity_decision = EXCLUDED.identity_decision,
                parser_version = EXCLUDED.parser_version
        """)

        for c in components:
            db.execute(insert_sql, c)
            print(f"Inserted/Updated component: {c['action_id']} ({c['action_type']}, M={c['share_multiplier']})")

        db.commit()
        print("Registry updates committed successfully.")


if __name__ == "__main__":
    apply_compound_component_modelling()
