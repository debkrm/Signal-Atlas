"""
test_v1_3_financial_closure.py - Comprehensive Verification for Phase 1B-ii.2.5.

Validates:
1. JTLIND Duplicate Corporate Action Resolution:
   - Duplicate CA-JTLIND-2024-11-14-BONUS is marked SUPERSEDED.
   - Authoritative split CA-JTLINFRA-2024-11-14-INE391J01024-INE391J01032 is active.
   - v1.3 pre-split multiplier is strictly 2.0 (not 4.0).
   - v1.3 historical OHLC = raw OHLC / 2.0, volume = raw volume * 2.0.
   - Post-split multiplier is 1.0 (no double application).
   - Ex-date prev-close alignment is correct.
   - PIT dynamic series behaves correctly before vs after ex-date.
   - v1.2 remains unchanged in DB showing M=4.0; v1.3 shows M=2.0.
2. GVPTECH Duplicate Corporate Action Resolution:
   - Duplicate CA-GVPTECH-2023-01-23-BONUS marked SUPERSEDED.
   - Authoritative split CA-4THDIM-2023-01-23-INE382T01022-INE382T01030 active.
   - v1.2 showed M=25.0, v1.3 shows M=5.0.
3. Legitimate Concurrent Compound Events Preserved:
   - GOLDSTAR (10:1 split + 1:1 bonus, M=20.0).
   - VERTOZ (10:1 split + 1:1 bonus, M=20.0).
4. The 25 Bonus-vs-Split Classifications:
   - Verified nominal face values populated and action_type updated to STOCK_SPLIT.
   - 360ONE and AARTECH concurrent split+bonus status verified.
5. Immutability and Dataset Counts:
   - daily_prices_raw strictly 1,855,370 immutable records.
   - daily_prices_adjusted has strictly 1,848,718 records per version across v1.0, v1.1, v1.2, v1.3.
"""

import datetime
from decimal import Decimal
import pytest
from sqlalchemy import select, func

from signal_atlas.db.session import get_db
from signal_atlas.db.models import (
    CorporateAction,
    DailyPriceRaw,
    DailyPriceAdjusted,
    InstrumentSymbolHistory,
)
from signal_atlas.quality.adjustment import (
    is_action_eligible_for_price_adjustment,
    get_point_in_time_adjusted_history,
)


@pytest.fixture(autouse=True)
def require_v1_3_dataset():
    with get_db() as db:
        hist = db.execute(
            select(InstrumentSymbolHistory).where(InstrumentSymbolHistory.symbol == "JTLIND")
        ).scalars().first()
        if hist is None:
            pytest.skip("Historical v1.3 dataset not loaded in test database")


def get_instrument_id_by_symbol(db, symbol: str) -> str:
    """Helper to resolve canonical instrument_id for a symbol."""
    stmt = (
        select(InstrumentSymbolHistory.instrument_id)
        .where(InstrumentSymbolHistory.symbol == symbol)
        .limit(1)
    )
    inst_id = db.execute(stmt).scalar()
    if inst_id is None:
        pytest.skip(f"Historical dataset for symbol '{symbol}' not loaded in test database")
    return inst_id


def test_jtlind_corporate_action_registry_deduplication():
    """Verify both JTLIND records are preserved and duplicate is marked SUPERSEDED."""
    with get_db() as db:
        inst_id = get_instrument_id_by_symbol(db, "JTLIND")

        actions = db.execute(
            select(CorporateAction)
            .where(
                CorporateAction.instrument_id == inst_id,
                CorporateAction.ex_date == datetime.date(2024, 11, 14),
            )
        ).scalars().all()

        assert len(actions) == 2, "Both corporate actions must be preserved for audit"

        split_action = next(a for a in actions if "STOCK_SPLIT" in a.action_id or a.action_type == "STOCK_SPLIT")
        bonus_action = next(a for a in actions if a.action_id == "CA-JTLIND-2024-11-14-BONUS")

        # Split action must be active & verified
        assert split_action.verification_status == "VERIFIED"
        assert is_action_eligible_for_price_adjustment(split_action) is True
        assert split_action.share_multiplier == Decimal("2.000000")

        # Duplicate bonus action must be SUPERSEDED
        assert bonus_action.verification_status == "SUPERSEDED"
        assert is_action_eligible_for_price_adjustment(bonus_action) is False
        assert bonus_action.identity_decision == "SUPERSEDED_DUPLICATE_OF_SPLIT"
        assert split_action.action_id in bonus_action.purpose


def test_jtlind_v1_2_vs_v1_3_prices():
    """Verify JTLIND pre-split prices in v1.2 (M=4) vs v1.3 (M=2) and post-split (M=1)."""
    with get_db() as db:
        inst_id = get_instrument_id_by_symbol(db, "JTLIND")

        # Day before ex-date: 2024-11-13
        pre_date = datetime.date(2024, 11, 13)
        raw_pre = db.execute(
            select(DailyPriceRaw).where(
                DailyPriceRaw.instrument_id == inst_id,
                DailyPriceRaw.trade_date == pre_date,
                DailyPriceRaw.series == "EQ",
            )
        ).scalars().first()
        assert raw_pre is not None

        v1_2_pre = db.execute(
            select(DailyPriceAdjusted).where(
                DailyPriceAdjusted.instrument_id == inst_id,
                DailyPriceAdjusted.trade_date == pre_date,
                DailyPriceAdjusted.series == "EQ",
                DailyPriceAdjusted.adjustment_version == "v1.2",
            )
        ).scalars().first()
        assert v1_2_pre is not None
        # v1.2 was incorrectly adjusted by factor 4.0
        assert v1_2_pre.cumulative_multiplier == Decimal("4.000000")
        assert v1_2_pre.close.quantize(Decimal("0.01")) == (raw_pre.close / Decimal("4.0")).quantize(Decimal("0.01"))

        v1_3_pre = db.execute(
            select(DailyPriceAdjusted).where(
                DailyPriceAdjusted.instrument_id == inst_id,
                DailyPriceAdjusted.trade_date == pre_date,
                DailyPriceAdjusted.series == "EQ",
                DailyPriceAdjusted.adjustment_version == "v1.3",
            )
        ).scalars().first()
        assert v1_3_pre is not None
        # v1.3 is correctly adjusted by factor 2.0
        assert v1_3_pre.cumulative_multiplier == Decimal("2.000000")
        assert v1_3_pre.close.quantize(Decimal("0.01")) == (raw_pre.close / Decimal("2.0")).quantize(Decimal("0.01"))
        assert v1_3_pre.open.quantize(Decimal("0.01")) == (raw_pre.open / Decimal("2.0")).quantize(Decimal("0.01"))
        assert v1_3_pre.high.quantize(Decimal("0.01")) == (raw_pre.high / Decimal("2.0")).quantize(Decimal("0.01"))
        assert v1_3_pre.low.quantize(Decimal("0.01")) == (raw_pre.low / Decimal("2.0")).quantize(Decimal("0.01"))
        assert v1_3_pre.volume.quantize(Decimal("0.0001")) == (raw_pre.volume * Decimal("2.0")).quantize(Decimal("0.0001"))

        # Ex-date: 2024-11-14
        ex_date = datetime.date(2024, 11, 14)
        raw_ex = db.execute(
            select(DailyPriceRaw).where(
                DailyPriceRaw.instrument_id == inst_id,
                DailyPriceRaw.trade_date == ex_date,
                DailyPriceRaw.series == "EQ",
            )
        ).scalars().first()
        assert raw_ex is not None

        v1_3_ex = db.execute(
            select(DailyPriceAdjusted).where(
                DailyPriceAdjusted.instrument_id == inst_id,
                DailyPriceAdjusted.trade_date == ex_date,
                DailyPriceAdjusted.series == "EQ",
                DailyPriceAdjusted.adjustment_version == "v1.3",
            )
        ).scalars().first()
        assert v1_3_ex is not None
        # Post-split: multiplier is 1.0
        assert v1_3_ex.cumulative_multiplier == Decimal("1.000000")
        assert v1_3_ex.close == raw_ex.close
        # Ex-date prev-close alignment: prev_close must match pre_date adjusted close
        assert v1_3_ex.prev_close == v1_3_pre.close


def test_jtlind_point_in_time_behavior():
    """Verify PIT adjustment behavior for JTLIND before vs after ex-date."""
    with get_db() as db:
        inst_id = get_instrument_id_by_symbol(db, "JTLIND")

        # Test trade date prior to as_of_date (2024-10-31)
        check_date = datetime.date(2024, 10, 31)

        # As-of before ex-date (2024-11-01): corporate action on 2024-11-14 is in the future
        pit_before = get_point_in_time_adjusted_history(
            db=db,
            instrument_id=inst_id,
            as_of_date=datetime.date(2024, 11, 1),
        )
        row_before = next(r for r in pit_before if r.trade_date == check_date)
        # Prior to ex-date, price is in raw units (M=1.0)
        assert row_before.cumulative_multiplier == Decimal("1.000000")

        # As-of after ex-date (2024-11-20): corporate action on 2024-11-14 is known
        pit_after = get_point_in_time_adjusted_history(
            db=db,
            instrument_id=inst_id,
            as_of_date=datetime.date(2024, 11, 20),
        )
        row_after = next(r for r in pit_after if r.trade_date == check_date)
        # After ex-date, historical prices reflect M=2.0 (not 4.0)
        assert row_after.cumulative_multiplier == Decimal("2.000000")
        assert row_after.close.quantize(Decimal("0.01")) == (row_before.close / Decimal("2.0")).quantize(Decimal("0.01"))


def test_gvptech_duplicate_resolution():
    """Verify GVPTECH duplicate resolution (M=5 in v1.3 vs M=25 in v1.2)."""
    with get_db() as db:
        inst_id = get_instrument_id_by_symbol(db, "GVPTECH")

        actions = db.execute(
            select(CorporateAction)
            .where(
                CorporateAction.instrument_id == inst_id,
                CorporateAction.ex_date == datetime.date(2023, 1, 23),
            )
        ).scalars().all()
        assert len(actions) == 2

        split_action = next(a for a in actions if "STOCK_SPLIT" in a.action_id or a.action_type == "STOCK_SPLIT")
        bonus_action = next(a for a in actions if a.action_id == "CA-GVPTECH-2023-01-23-BONUS")

        assert split_action.verification_status == "VERIFIED"
        assert is_action_eligible_for_price_adjustment(split_action) is True
        assert bonus_action.verification_status == "SUPERSEDED"
        assert is_action_eligible_for_price_adjustment(bonus_action) is False

        # Pre-event date: 2023-01-20
        pre_date = datetime.date(2023, 1, 20)
        v1_2 = db.execute(
            select(DailyPriceAdjusted).where(
                DailyPriceAdjusted.instrument_id == inst_id,
                DailyPriceAdjusted.trade_date == pre_date,
                DailyPriceAdjusted.series == "BE",
                DailyPriceAdjusted.adjustment_version == "v1.2",
            )
        ).scalars().first()
        assert v1_2.cumulative_multiplier == Decimal("25.000000")

        v1_3 = db.execute(
            select(DailyPriceAdjusted).where(
                DailyPriceAdjusted.instrument_id == inst_id,
                DailyPriceAdjusted.trade_date == pre_date,
                DailyPriceAdjusted.series == "BE",
                DailyPriceAdjusted.adjustment_version == "v1.3",
            )
        ).scalars().first()
        assert v1_3.cumulative_multiplier == Decimal("5.000000")


def test_concurrent_compound_events_preserved():
    """Verify GOLDSTAR and VERTOZ concurrent split+bonus combine to M=20.0 in v1.3."""
    with get_db() as db:
        # GOLDSTAR traded on 2023-01-19 (series SM), VERTOZ traded on 2024-07-04 (series BE)
        for symbol, ex_date, pre_date, series in [
            ("GOLDSTAR", datetime.date(2023, 1, 23), datetime.date(2023, 1, 19), "SM"),
            ("VERTOZ", datetime.date(2024, 7, 5), datetime.date(2024, 7, 4), "BE"),
        ]:
            inst_id = get_instrument_id_by_symbol(db, symbol)

            actions = db.execute(
                select(CorporateAction)
                .where(
                    CorporateAction.instrument_id == inst_id,
                    CorporateAction.ex_date == ex_date,
                )
            ).scalars().all()
            assert len(actions) == 2, f"{symbol} must have exactly 2 concurrent actions"
            assert all(a.verification_status == "VERIFIED" for a in actions)
            assert all(is_action_eligible_for_price_adjustment(a) is True for a in actions)

            v1_3_pre = db.execute(
                select(DailyPriceAdjusted).where(
                    DailyPriceAdjusted.instrument_id == inst_id,
                    DailyPriceAdjusted.trade_date == pre_date,
                    DailyPriceAdjusted.series == series,
                    DailyPriceAdjusted.adjustment_version == "v1.3",
                )
            ).scalars().first()
            assert v1_3_pre is not None
            assert v1_3_pre.cumulative_multiplier == Decimal("20.000000"), (
                f"{symbol} pre-event multiplier must be 20.000000 in v1.3"
            )


def test_bonus_vs_split_25_classifications():
    """
    Verify that 23 continuing equity subdivisions are pure STOCK_SPLIT with nominal face values,
    and 360ONE and AARTECH are decomposed into distinct component records (STOCK_SPLIT + BONUS_ISSUE).
    """
    with get_db() as db:
        # Check sample of the 23 pure subdivisions
        sample_symbols = ["KRITIKA", "AJOONI", "GLOBAL", "SHRADHA", "FILATFASH", "REFEX", "KPIGREEN"]
        for sym in sample_symbols:
            ca = db.execute(
                select(CorporateAction).where(
                    CorporateAction.symbol == sym,
                    CorporateAction.verification_status == "VERIFIED",
                )
            ).scalars().first()
            assert ca is not None, f"Action for {sym} must exist"
            assert ca.action_type == "STOCK_SPLIT", f"{sym} action_type must be STOCK_SPLIT"
            assert ca.old_face_value is not None, f"{sym} old_face_value must be populated"
            assert ca.new_face_value is not None, f"{sym} new_face_value must be populated"
            assert ca.old_face_value > ca.new_face_value, f"{sym} face value must decrease"

        # Verify 360ONE and AARTECH have decomposed component records
        for sym in ["360ONE", "AARTECH"]:
            verified_cas = db.execute(
                select(CorporateAction).where(
                    CorporateAction.symbol == sym,
                    CorporateAction.verification_status == "VERIFIED",
                )
            ).scalars().all()
            assert len(verified_cas) == 2, f"{sym} must have exactly 2 verified component records"
            types = set(ca.action_type for ca in verified_cas)
            assert types == {"STOCK_SPLIT", "BONUS_ISSUE"}, (
                f"{sym} must have both STOCK_SPLIT and BONUS_ISSUE components, got {types}"
            )


def test_compound_events_360one_and_aartech():
    """
    Issue 1 & 2: Detailed verification of concurrent split-plus-bonus components:
      - 360ONE has 1 split (M=2.0) + 1 bonus (M=2.0) -> aggregate M=4.0
      - AARTECH has 1 split (M=2.0) + 1 bonus (M=1.5) -> aggregate M=3.0
      - Composite records are marked SUPERSEDED
      - Applied action IDs and aggregate factors verified in v1.4
      - Point-in-Time dynamics verified before and after ex-date
    """
    with get_db() as db:
        # 1. 360ONE Component Audit
        c_360_split = db.execute(
            select(CorporateAction).where(CorporateAction.action_id == "CA-360ONE-2023-03-02-STOCK_SPLIT")
        ).scalars().first()
        c_360_bonus = db.execute(
            select(CorporateAction).where(CorporateAction.action_id == "CA-360ONE-2023-03-02-BONUS_ISSUE")
        ).scalars().first()
        c_360_old = db.execute(
            select(CorporateAction).where(CorporateAction.action_id == "CA-360ONE-2023-03-02-BONUS")
        ).scalars().first()

        assert c_360_split is not None
        assert c_360_split.action_type == "STOCK_SPLIT"
        assert c_360_split.share_multiplier == Decimal("2.000000")
        assert c_360_split.old_face_value == Decimal("2.00")
        assert c_360_split.new_face_value == Decimal("1.00")
        assert c_360_split.verification_status == "VERIFIED"
        assert is_action_eligible_for_price_adjustment(c_360_split) is True

        assert c_360_bonus is not None
        assert c_360_bonus.action_type == "BONUS_ISSUE"
        assert c_360_bonus.share_multiplier == Decimal("2.000000")
        assert c_360_bonus.old_share_qty == Decimal("1.00")
        assert c_360_bonus.new_share_qty == Decimal("1.00")
        assert c_360_bonus.verification_status == "VERIFIED"
        assert is_action_eligible_for_price_adjustment(c_360_bonus) is True

        assert c_360_old is not None
        assert c_360_old.verification_status == "SUPERSEDED"
        assert is_action_eligible_for_price_adjustment(c_360_old) is False

        # Aggregate factor = 2.0 * 2.0 = 4.0
        assert c_360_split.share_multiplier * c_360_bonus.share_multiplier == Decimal("4.000000")

        # 2. AARTECH Component Audit
        c_aar_split = db.execute(
            select(CorporateAction).where(CorporateAction.action_id == "CA-AARTECH-2024-08-09-STOCK_SPLIT")
        ).scalars().first()
        c_aar_bonus = db.execute(
            select(CorporateAction).where(CorporateAction.action_id == "CA-AARTECH-2024-08-09-BONUS_ISSUE")
        ).scalars().first()
        c_aar_old = db.execute(
            select(CorporateAction).where(CorporateAction.action_id == "CA-AARTECH-2024-08-09-BONUS")
        ).scalars().first()

        assert c_aar_split is not None
        assert c_aar_split.action_type == "STOCK_SPLIT"
        assert c_aar_split.share_multiplier == Decimal("2.000000")
        assert c_aar_split.old_face_value == Decimal("10.00")
        assert c_aar_split.new_face_value == Decimal("5.00")
        assert c_aar_split.verification_status == "VERIFIED"
        assert is_action_eligible_for_price_adjustment(c_aar_split) is True

        assert c_aar_bonus is not None
        assert c_aar_bonus.action_type == "BONUS_ISSUE"
        assert c_aar_bonus.share_multiplier == Decimal("1.500000")
        assert c_aar_bonus.old_share_qty == Decimal("2.00")
        assert c_aar_bonus.new_share_qty == Decimal("1.00")
        assert c_aar_bonus.verification_status == "VERIFIED"
        assert is_action_eligible_for_price_adjustment(c_aar_bonus) is True

        assert c_aar_old is not None
        assert c_aar_old.verification_status == "SUPERSEDED"
        assert is_action_eligible_for_price_adjustment(c_aar_old) is False

        # Aggregate factor = 2.0 * 1.5 = 3.0
        assert c_aar_split.share_multiplier * c_aar_bonus.share_multiplier == Decimal("3.000000")

        # 3. 360ONE Historical prices in v1.4
        pre_360 = db.execute(
            select(DailyPriceAdjusted).where(
                DailyPriceAdjusted.instrument_id == c_360_split.instrument_id,
                DailyPriceAdjusted.trade_date == datetime.date(2023, 3, 1),
                DailyPriceAdjusted.adjustment_version == "v1.4",
            )
        ).scalars().first()
        if pre_360 is not None:
            assert pre_360.cumulative_multiplier == Decimal("4.000000")
            assert set(pre_360.applied_action_ids.split(",")) == {
                "CA-360ONE-2023-03-02-STOCK_SPLIT",
                "CA-360ONE-2023-03-02-BONUS_ISSUE",
            }

        # 4. PIT Consistency for 360ONE
        # As-of before ex-date (2023-02-15): actions in future, M=1.0
        pit_before = get_point_in_time_adjusted_history(
            db=db,
            instrument_id=c_360_split.instrument_id,
            as_of_date=datetime.date(2023, 2, 15),
        )
        row_b = next(r for r in pit_before if r.trade_date == datetime.date(2023, 2, 10))
        assert row_b.cumulative_multiplier == Decimal("1.000000")

        # As-of after ex-date (2023-03-15): both components known, M=4.0
        pit_after = get_point_in_time_adjusted_history(
            db=db,
            instrument_id=c_360_split.instrument_id,
            as_of_date=datetime.date(2023, 3, 15),
        )
        row_a = next(r for r in pit_after if r.trade_date == datetime.date(2023, 2, 10))
        assert row_a.cumulative_multiplier == Decimal("4.000000")
        assert row_a.close.quantize(Decimal("0.01")) == (row_b.close / Decimal("4.0")).quantize(Decimal("0.01"))


def test_database_record_counts_and_immutability():
    """Verify raw immutability (1,855,370) and adjusted version counts (1,848,718 each across v1.0-v1.4)."""
    with get_db() as db:
        raw_count = db.execute(select(func.count()).select_from(DailyPriceRaw)).scalar()
        assert raw_count == 1855370, "DailyPriceRaw count must strictly remain 1,855,370"

        for v in ["v1.0", "v1.1", "v1.2", "v1.3", "v1.4"]:
            adj_count = db.execute(
                select(func.count())
                .select_from(DailyPriceAdjusted)
                .where(DailyPriceAdjusted.adjustment_version == v)
            ).scalar()
            assert adj_count == 1848718, f"DailyPriceAdjusted count for {v} must be 1,848,718"
