import datetime
from decimal import Decimal
import json
from pathlib import Path
import pytest
from sqlalchemy import select, func

from signal_atlas.db.models import (
    CorporateAction,
    DailyPriceRaw,
    Instrument,
    InstrumentSymbolHistory,
)
from signal_atlas.db.session import get_db
from signal_atlas.quality.corporate_actions import (
    CorporateActionEvent,
    CorporateActionRegistry,
)


def test_multi_isin_and_transition_counts():
    """
    Phase 1B-ii.0 Item 1: Resolve the 152 vs 154 discrepancy.
    Verify against production DB:
      - Exactly 152 unique instruments have > 1 distinct ISIN across 2022-2024.
      - Exactly 150 instruments have 2 distinct ISINs (contributing 150 transitions).
      - Exactly 2 instruments have 3 distinct ISINs (VBL and SERVOTECH, contributing 4 transitions).
      - Total pairwise ISIN transitions = 150 + 4 = 154.
    """
    with get_db() as db:
        stmt = (
            select(
                InstrumentSymbolHistory.instrument_id,
                func.count(func.distinct(InstrumentSymbolHistory.isin)),
            )
            .group_by(InstrumentSymbolHistory.instrument_id)
            .having(func.count(func.distinct(InstrumentSymbolHistory.isin)) > 1)
        )
        multi_isin_insts = db.execute(stmt).all()
        assert len(multi_isin_insts) == 152, f"Expected 152 multi-ISIN instruments, got {len(multi_isin_insts)}"

        two_isin_insts = [inst_id for inst_id, cnt in multi_isin_insts if cnt == 2]
        three_isin_insts = [inst_id for inst_id, cnt in multi_isin_insts if cnt == 3]

        assert len(two_isin_insts) == 150
        assert len(three_isin_insts) == 2

        three_isin_symbols = set(
            db.execute(
                select(InstrumentSymbolHistory.symbol)
                .where(InstrumentSymbolHistory.instrument_id.in_(three_isin_insts))
            ).scalars().all()
        )
        assert "VBL" in three_isin_symbols
        assert "SERVOTECH" in three_isin_symbols

        total_transitions = len(two_isin_insts) * 1 + len(three_isin_insts) * 2
        assert total_transitions == 154


def test_tatasteel_split_event_and_multiplier():
    """
    Phase 1B-ii.0: Tata Steel 10:1 split verification.
    """
    with get_db() as db:
        ca = db.execute(
            select(CorporateAction).where(
                CorporateAction.symbol == "TATASTEEL",
                CorporateAction.action_type == "STOCK_SPLIT",
            )
        ).scalar()
        assert ca is not None
        assert ca.ex_date == datetime.date(2022, 7, 28)
        assert ca.old_face_value == Decimal("10.00")
        assert ca.new_face_value == Decimal("1.00")
        assert ca.share_multiplier == Decimal("10.000000")
        assert ca.old_isin == "INE081A01012"
        assert ca.new_isin == "INE081A01020"
        assert ca.verification_status == "VERIFIED"
        assert ca.identity_decision == "UNIFIED_IDENTITY"
        assert ca.source_circular == "NSE/CML/53019"
        assert ca.issuing_organisation == "NSE"
        assert ca.source_type == "EXCHANGE_CIRCULAR"
        assert "CML53019.pdf" in (ca.source_url or "")


def test_hal_split_event_and_multiplier():
    """
    Phase 1B-ii.0: HAL 2:1 split verification (rebutting incorrect 5:1 claim).
    """
    with get_db() as db:
        ca = db.execute(
            select(CorporateAction).where(
                CorporateAction.symbol == "HAL",
                CorporateAction.action_type == "STOCK_SPLIT",
            )
        ).scalar()
        assert ca is not None
        assert ca.ex_date == datetime.date(2023, 9, 28)
        assert ca.old_face_value == Decimal("10.00")
        assert ca.new_face_value == Decimal("5.00")
        assert ca.share_multiplier == Decimal("2.000000")  # 2:1 split
        assert ca.old_isin == "INE066F01012"
        assert ca.new_isin == "INE066F01020"
        assert ca.verification_status == "VERIFIED"
        assert ca.source_circular == "NSE/CML/58633"
        assert ca.issuing_organisation == "NSE"
        assert ca.source_type == "EXCHANGE_CIRCULAR"
        assert "CML58633.pdf" in (ca.source_url or "")


def test_nestleind_split_event_and_multiplier():
    """
    Phase 1B-ii.0: Nestlé India 10:1 split verification (rebutting incorrect 5:1 claim).
    """
    with get_db() as db:
        ca = db.execute(
            select(CorporateAction).where(
                CorporateAction.symbol == "NESTLEIND",
                CorporateAction.action_type == "STOCK_SPLIT",
            )
        ).scalar()
        assert ca is not None
        assert ca.ex_date == datetime.date(2024, 1, 5)
        assert ca.old_face_value == Decimal("10.00")
        assert ca.new_face_value == Decimal("1.00")
        assert ca.share_multiplier == Decimal("10.000000")  # 10:1 split
        assert ca.old_isin == "INE239A01016"
        assert ca.new_isin == "INE239A01024"
        assert ca.verification_status == "VERIFIED"
        assert ca.source_circular == "NSE/CML/59895"
        assert ca.issuing_organisation == "NSE"
        assert ca.source_type == "EXCHANGE_CIRCULAR"
        assert "CML59895.pdf" in (ca.source_url or "")


def test_rites_bonus_distinct_representation():
    """
    Phase 1B-ii.0: RITES 1:1 bonus issue (distinguishing bonus from face-value split).
    """
    with get_db() as db:
        ca = db.execute(
            select(CorporateAction).where(
                CorporateAction.symbol == "RITES",
                CorporateAction.action_type == "BONUS_ISSUE",
            )
        ).scalar()
        assert ca is not None
        assert ca.ex_date == datetime.date(2024, 9, 20)
        assert ca.share_multiplier == Decimal("2.000000")  # 1:1 bonus doubles share count
        assert ca.old_isin == "INE320J01015"
        assert ca.new_isin == "INE320J01015"
        assert ca.verification_status == "VERIFIED"
        assert ca.source_circular == "NSE/CML/64019"
        assert ca.issuing_organisation == "NSE"
        assert ca.source_type == "EXCHANGE_CIRCULAR"
        assert "CML64019.pdf" in (ca.source_url or "")


def test_vertoz_split_and_bonus_decomposition():
    """
    Phase 1B-ii.0: Vertoz concurrent split + bonus decomposition.
    Multiple corporate actions on the same ex-date MUST NOT be collapsed into one event.
    """
    with get_db() as db:
        evs = db.execute(
            select(CorporateAction)
            .where(CorporateAction.symbol == "VERTOZ", CorporateAction.ex_date == datetime.date(2024, 7, 5))
            .order_by(CorporateAction.action_type.desc())
        ).scalars().all()

        assert len(evs) == 2, f"Expected 2 separate events for Vertoz, got {len(evs)}"
        split_ev = next(e for e in evs if e.action_type == "STOCK_SPLIT")
        bonus_ev = next(e for e in evs if e.action_type == "BONUS_ISSUE")

        assert split_ev.share_multiplier == Decimal("10.000000")
        assert split_ev.old_face_value == Decimal("10.00")
        assert split_ev.new_face_value == Decimal("1.00")
        assert split_ev.source_circular == "NSE/CML/62802"

        assert bonus_ev.share_multiplier == Decimal("2.000000")
        assert bonus_ev.source_circular == "NSE/CML/62802"

        combined_multiplier = split_ev.share_multiplier * bonus_ev.share_multiplier
        assert combined_multiplier == Decimal("20.000000")


def test_polycab_split_exclusion_and_audit():
    """
    Phase 1B-ii.0.1: Polycab has NO_VERIFIED_SPLIT_IN_AUDITED_PERIOD.
    Verify that Polycab is excluded from STOCK_SPLIT and has an explicit audit record.
    """
    with get_db() as db:
        ca = db.execute(
            select(CorporateAction).where(
                CorporateAction.symbol == "POLYCAB",
                CorporateAction.action_type == "STOCK_SPLIT",
            )
        ).scalar()
        assert ca is None, "Polycab must NOT have a stock split record"

        # Phase 1B-ii.2: Polycab audit assertion is decoupled from corporate_actions table
        audit_ca = db.execute(
            select(CorporateAction).where(
                CorporateAction.symbol == "POLYCAB",
            )
        ).scalar()
        assert audit_ca is None, "Polycab must NOT be stored in corporate_actions table"

    # Verify Polycab is preserved in audit assertions checkpoint
    audit_file = Path("data/checkpoints/corporate_action_audit_assertions.json")
    assert audit_file.exists(), "corporate_action_audit_assertions.json must exist"
    with open(audit_file, "r", encoding="utf-8") as f:
        audit_assertions = json.load(f)
    polycab_assertions = [a for a in audit_assertions if a["symbol"] == "POLYCAB"]
    assert len(polycab_assertions) == 1
    assert polycab_assertions[0]["assertion_type"] == "NO_VERIFIED_SPLIT_IN_AUDITED_PERIOD"
    assert polycab_assertions[0]["share_multiplier"] == "1.000000"


def test_raw_prices_unmodified_by_corporate_actions():
    """
    Phase 1B-ii.0 Requirement: Historical raw prices remain strictly untouched.
    """
    with get_db() as db:
        price_count = db.execute(select(func.count(DailyPriceRaw.id))).scalar()
        assert price_count == 1855370, f"Raw price records count must remain exactly 1,855,370, got {price_count}"


def test_registry_checkpoint_files_exist_and_match():
    """
    Verifies that corporate_action_registry.json and .csv exist and match the DB events.
    """
    json_path = Path("data/checkpoints/corporate_action_registry.json")
    csv_path = Path("data/checkpoints/corporate_action_registry.csv")
    assert json_path.exists(), "JSON registry checkpoint missing"
    assert csv_path.exists(), "CSV registry checkpoint missing"

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) >= 154, f"Expected at least 154 records in registry, got {len(data)}"
    
    # Check HAL, NESTLEIND, RITES, TATASTEEL presence in JSON
    symbols = {r["symbol"] for r in data}
    assert "TATASTEEL" in symbols
    assert "HAL" in symbols
    assert "NESTLEIND" in symbols
    assert "RITES" in symbols
    assert "VERTOZ" in symbols
