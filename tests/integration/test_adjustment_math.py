"""
test_adjustment_math.py - Comprehensive Mathematical Verification of Corporate Action Adjustments.

Verifies:
  1. Tata Steel 10:1 split.
  2. HAL 2:1 split.
  3. Nestlé India 10:1 split.
  4. RITES 1:1 bonus (same ISIN).
  5. Vertoz concurrent 10:1 split + 1:1 bonus (multiplicative combined M=20).
  6. VBL two successive splits (2.0 and 2.5, cumulative M=5.0).
  7. Servotech two successive splits (5.0 and 2.0, cumulative M=10.0).
  8. High-precision adjusted volume & exact traded-value invariance.
  9. Pre-ex-date adjustment and post-ex-date invariance.
  10. Position accounting economic value invariance without double counting.
  11. Raw exchange data immutability (1,855,370 records untouched).
  12. Non-price adjusting nature of identity events and dividends.
"""

import datetime
from decimal import Decimal, ROUND_HALF_UP
import pytest
from sqlalchemy import select, func

from signal_atlas.db.session import get_db
from signal_atlas.db.models import (
    CorporateAction,
    DailyPriceRaw,
    InstrumentSymbolHistory,
)
from signal_atlas.quality.corporate_actions import CorporateActionEvent
from signal_atlas.quality.adjustment import (
    calculate_split_multiplier,
    calculate_bonus_multiplier,
    resolve_action_multiplier,
    calculate_cumulative_adjustment_factors,
    apply_backward_adjustment,
    SimulatedPosition,
    transform_position_for_action,
    DividendEntitlement,
)


def _get_symbol_data(symbol: str):
    """Helper to fetch raw prices and corporate actions for a symbol as detached value models."""
    with get_db() as db:
        hist = db.execute(
            select(InstrumentSymbolHistory).where(InstrumentSymbolHistory.symbol == symbol)
        ).scalars().first()
        if hist is None:
            pytest.skip(f"Historical dataset for symbol '{symbol}' not loaded in test database")
        inst_id = hist.instrument_id

        prices = db.execute(
            select(DailyPriceRaw)
            .where(DailyPriceRaw.instrument_id == inst_id)
            .order_by(DailyPriceRaw.trade_date)
        ).scalars().all()
        raw_dicts = [
            {
                "trade_date": p.trade_date,
                "open": p.open,
                "high": p.high,
                "low": p.low,
                "close": p.close,
                "last": p.last,
                "prev_close": p.prev_close,
                "volume": p.volume,
                "traded_value": p.traded_value,
            }
            for p in prices
        ]

        actions = db.execute(
            select(CorporateAction)
            .where(CorporateAction.symbol == symbol)
            .order_by(CorporateAction.ex_date)
        ).scalars().all()
        action_models = [
            CorporateActionEvent(
                action_id=a.action_id,
                instrument_id=a.instrument_id,
                symbol=a.symbol,
                series=a.series,
                action_type=a.action_type,
                ex_date=a.ex_date,
                record_date=a.record_date,
                old_isin=a.old_isin,
                new_isin=a.new_isin,
                old_face_value=a.old_face_value,
                new_face_value=a.new_face_value,
                old_share_qty=a.old_share_qty,
                new_share_qty=a.new_share_qty,
                share_multiplier=a.share_multiplier,
                cash_entitlement=a.cash_entitlement,
                purpose=a.purpose,
                issuing_organisation=a.issuing_organisation,
                source_type=a.source_type,
                source_circular=a.source_circular,
                source_url=a.source_url,
                source_hash=a.source_hash,
                publication_date=a.publication_date,
                identity_decision=a.identity_decision,
                verification_status=a.verification_status,
                parser_version=a.parser_version,
            )
            for a in actions
        ]
        return raw_dicts, action_models


def test_tatasteel_10_to_1_split_adjustment():
    """
    1. Tata Steel 10:1 split (ex-date: 2022-07-28).
    Pre-ex-date: 2022-07-27.
    """
    raw_prices, actions = _get_symbol_data("TATASTEEL")
    split_action = next(a for a in actions if a.action_type == "STOCK_SPLIT" and a.ex_date == datetime.date(2022, 7, 28))
    assert split_action.share_multiplier == Decimal("10.000000")

    adjusted = apply_backward_adjustment(raw_prices, [split_action])
    adj_map = {r.trade_date: r for r in adjusted}
    raw_map = {r["trade_date"]: r for r in raw_prices}

    # Pre-ex-date: 2022-07-27
    pre_date = datetime.date(2022, 7, 27)
    raw_pre = raw_map[pre_date]
    adj_pre = adj_map[pre_date]

    # Pre-ex-date prices are divided by 10 (high precision)
    assert adj_pre.cumulative_multiplier == Decimal("10.000000")
    assert adj_pre.close == (raw_pre["close"] / Decimal("10.0")).quantize(Decimal("0.000001"))
    assert adj_pre.volume == Decimal(raw_pre["volume"]) * Decimal("10.0")
    assert adj_pre.raw_volume == raw_pre["volume"]
    assert adj_pre.traded_value == raw_pre["traded_value"]
    assert adj_pre.verify_traded_value_invariance(raw_pre["close"], raw_pre["volume"])

    # Ex-date: 2022-07-28 (post-adjustment invariant)
    ex_date = datetime.date(2022, 7, 28)
    raw_ex = raw_map[ex_date]
    adj_ex = adj_map[ex_date]
    assert adj_ex.cumulative_multiplier == Decimal("1.000000")
    assert adj_ex.close == raw_ex["close"]
    assert adj_ex.volume == Decimal(raw_ex["volume"])


def test_hal_2_to_1_split_adjustment():
    """
    2. HAL 2:1 split (ex-date: 2023-09-28).
    Pre-ex-date: 2023-09-27.
    """
    raw_prices, actions = _get_symbol_data("HAL")
    split_action = next(a for a in actions if a.action_type == "STOCK_SPLIT" and a.ex_date == datetime.date(2023, 9, 28))
    assert split_action.share_multiplier == Decimal("2.000000")

    adjusted = apply_backward_adjustment(raw_prices, [split_action])
    adj_map = {r.trade_date: r for r in adjusted}
    raw_map = {r["trade_date"]: r for r in raw_prices}

    # Pre-ex-date: 2023-09-27
    pre_date = datetime.date(2023, 9, 27)
    raw_pre = raw_map[pre_date]
    adj_pre = adj_map[pre_date]

    assert adj_pre.cumulative_multiplier == Decimal("2.000000")
    assert adj_pre.close == (raw_pre["close"] / Decimal("2.0")).quantize(Decimal("0.000001"))
    assert adj_pre.volume == Decimal(raw_pre["volume"]) * Decimal("2.0")
    assert adj_pre.raw_volume == raw_pre["volume"]
    assert adj_pre.traded_value == raw_pre["traded_value"]
    assert adj_pre.verify_traded_value_invariance(raw_pre["close"], raw_pre["volume"])

    # Ex-date: 2023-09-28
    ex_date = datetime.date(2023, 9, 28)
    raw_ex = raw_map[ex_date]
    adj_ex = adj_map[ex_date]
    assert adj_ex.cumulative_multiplier == Decimal("1.000000")
    assert adj_ex.close == raw_ex["close"]
    assert adj_ex.volume == Decimal(raw_ex["volume"])


def test_nestleind_10_to_1_split_adjustment():
    """
    3. Nestlé India 10:1 split (ex-date: 2024-01-05).
    Pre-ex-date: 2024-01-04.
    """
    raw_prices, actions = _get_symbol_data("NESTLEIND")
    split_action = next(a for a in actions if a.action_type == "STOCK_SPLIT" and a.ex_date == datetime.date(2024, 1, 5))
    assert split_action.share_multiplier == Decimal("10.000000")

    adjusted = apply_backward_adjustment(raw_prices, [split_action])
    adj_map = {r.trade_date: r for r in adjusted}
    raw_map = {r["trade_date"]: r for r in raw_prices}

    # Pre-ex-date: 2024-01-04
    pre_date = datetime.date(2024, 1, 4)
    raw_pre = raw_map[pre_date]
    adj_pre = adj_map[pre_date]

    assert adj_pre.cumulative_multiplier == Decimal("10.000000")
    assert adj_pre.close == (raw_pre["close"] / Decimal("10.0")).quantize(Decimal("0.000001"))
    assert adj_pre.volume == Decimal(raw_pre["volume"]) * Decimal("10.0")
    assert adj_pre.raw_volume == raw_pre["volume"]
    assert adj_pre.traded_value == raw_pre["traded_value"]
    assert adj_pre.verify_traded_value_invariance(raw_pre["close"], raw_pre["volume"])

    # Ex-date: 2024-01-05
    ex_date = datetime.date(2024, 1, 5)
    raw_ex = raw_map[ex_date]
    adj_ex = adj_map[ex_date]
    assert adj_ex.cumulative_multiplier == Decimal("1.000000")
    assert adj_ex.close == raw_ex["close"]
    assert adj_ex.volume == Decimal(raw_ex["volume"])


def test_rites_1_to_1_bonus_adjustment():
    """
    4. RITES 1:1 bonus issue (ex-date: 2024-09-20).
    Same ISIN INE320J01015 before and after bonus.
    """
    raw_prices, actions = _get_symbol_data("RITES")
    bonus_action = next(a for a in actions if a.action_type == "BONUS_ISSUE" and a.ex_date == datetime.date(2024, 9, 20))
    assert bonus_action.share_multiplier == Decimal("2.000000")
    assert bonus_action.old_isin == bonus_action.new_isin

    adjusted = apply_backward_adjustment(raw_prices, [bonus_action])
    adj_map = {r.trade_date: r for r in adjusted}
    raw_map = {r["trade_date"]: r for r in raw_prices}

    # Pre-ex-date: 2024-09-19
    pre_date = datetime.date(2024, 9, 19)
    raw_pre = raw_map[pre_date]
    adj_pre = adj_map[pre_date]

    assert adj_pre.cumulative_multiplier == Decimal("2.000000")
    assert adj_pre.close == (raw_pre["close"] / Decimal("2.0")).quantize(Decimal("0.000001"))
    assert adj_pre.volume == Decimal(raw_pre["volume"]) * Decimal("2.0")
    assert adj_pre.raw_volume == raw_pre["volume"]
    assert adj_pre.traded_value == raw_pre["traded_value"]
    assert adj_pre.verify_traded_value_invariance(raw_pre["close"], raw_pre["volume"])

    # Ex-date: 2024-09-20
    ex_date = datetime.date(2024, 9, 20)
    raw_ex = raw_map[ex_date]
    adj_ex = adj_map[ex_date]
    assert adj_ex.cumulative_multiplier == Decimal("1.000000")
    assert adj_ex.close == raw_ex["close"]
    assert adj_ex.volume == Decimal(raw_ex["volume"])


def test_vertoz_concurrent_split_and_bonus_multiplicative_adjustment():
    """
    5. Vertoz concurrent 10:1 split + 1:1 bonus (ex-date: 2024-07-05).
    Split factor M=10, Bonus factor M=2 -> Multiplicative combination = 20.0.
    """
    raw_prices, actions = _get_symbol_data("VERTOZ")
    vert_actions = [a for a in actions if a.ex_date == datetime.date(2024, 7, 5)]
    assert len(vert_actions) == 2
    split_act = next(a for a in vert_actions if a.action_type == "STOCK_SPLIT")
    bonus_act = next(a for a in vert_actions if a.action_type == "BONUS_ISSUE")

    assert split_act.share_multiplier == Decimal("10.000000")
    assert bonus_act.share_multiplier == Decimal("2.000000")

    adjusted = apply_backward_adjustment(raw_prices, vert_actions)
    adj_map = {r.trade_date: r for r in adjusted}
    raw_map = {r["trade_date"]: r for r in raw_prices}

    # Pre-ex-date: 2024-07-04
    pre_date = datetime.date(2024, 7, 4)
    raw_pre = raw_map[pre_date]
    adj_pre = adj_map[pre_date]

    # Pre-ex-date prices are divided by 20.0
    assert adj_pre.cumulative_multiplier == Decimal("20.000000")
    assert adj_pre.close == (raw_pre["close"] / Decimal("20.0")).quantize(Decimal("0.000001"))
    assert adj_pre.volume == Decimal(raw_pre["volume"]) * Decimal("20.0")
    assert adj_pre.raw_volume == raw_pre["volume"]
    assert adj_pre.traded_value == raw_pre["traded_value"]
    assert adj_pre.verify_traded_value_invariance(raw_pre["close"], raw_pre["volume"])

    # Ex-date: 2024-07-05
    ex_date = datetime.date(2024, 7, 5)
    raw_ex = raw_map[ex_date]
    adj_ex = adj_map[ex_date]
    assert adj_ex.cumulative_multiplier == Decimal("1.000000")
    assert adj_ex.close == raw_ex["close"]
    assert adj_ex.volume == Decimal(raw_ex["volume"])


def test_vbl_two_successive_splits_cumulative_adjustment():
    """
    6. VBL two successive splits:
      - Split 1: 2023-06-15, ratio 2:1 (M=2.0)
      - Split 2: 2024-09-12, ratio 2.5:1 (M=2.5)
      
    Verifies 3 regimes and fractional multiplier precision:
      - Regime A (before 2023-06-15): Cumulative M = 2.0 * 2.5 = 5.0
      - Regime B (2023-06-15 to 2024-09-11): Cumulative M = 2.5 (fractional 2.5x volume exact)
      - Regime C (on/after 2024-09-12): Cumulative M = 1.0
    """
    raw_prices, actions = _get_symbol_data("VBL")
    splits = [a for a in actions if a.action_type == "STOCK_SPLIT"]
    assert len(splits) == 2

    adjusted = apply_backward_adjustment(raw_prices, splits)
    adj_map = {r.trade_date: r for r in adjusted}
    raw_map = {r["trade_date"]: r for r in raw_prices}

    # Regime A: 2023-06-14 (before first split)
    date_a = datetime.date(2023, 6, 14)
    assert adj_map[date_a].cumulative_multiplier == Decimal("5.000000")
    assert adj_map[date_a].close == (raw_map[date_a]["close"] / Decimal("5.0")).quantize(Decimal("0.000001"))
    assert adj_map[date_a].volume == Decimal(raw_map[date_a]["volume"]) * Decimal("5.0")
    assert adj_map[date_a].verify_traded_value_invariance(raw_map[date_a]["close"], raw_map[date_a]["volume"])

    # Regime B: 2023-06-15 (on first split, before second split: M=2.5)
    # Raw volume 3020929 * 2.5 = 7552322.500000 (high-precision Decimal preserves half share!)
    date_b = datetime.date(2023, 6, 15)
    assert adj_map[date_b].cumulative_multiplier == Decimal("2.500000")
    assert adj_map[date_b].close == (raw_map[date_b]["close"] / Decimal("2.5")).quantize(Decimal("0.000001"))
    assert adj_map[date_b].volume == Decimal(raw_map[date_b]["volume"]) * Decimal("2.5")
    assert adj_map[date_b].verify_traded_value_invariance(raw_map[date_b]["close"], raw_map[date_b]["volume"])

    # Regime C: 2024-09-12 (on second split: M=1.0)
    date_c = datetime.date(2024, 9, 12)
    assert adj_map[date_c].cumulative_multiplier == Decimal("1.000000")
    assert adj_map[date_c].close == raw_map[date_c]["close"]
    assert adj_map[date_c].volume == Decimal(raw_map[date_c]["volume"])


def test_servotech_two_successive_splits_cumulative_adjustment():
    """
    7. Servotech two successive splits:
      - Split 1: 2023-02-03, ratio 5:1 (M=5.0)
      - Split 2: 2023-07-28, ratio 2:1 (M=2.0)
      
    Verifies 3 regimes:
      - Regime A (before 2023-02-03): Cumulative M = 5.0 * 2.0 = 10.0
      - Regime B (2023-02-03 to 2023-07-27): Cumulative M = 2.0
      - Regime C (on/after 2023-07-28): Cumulative M = 1.0
    """
    raw_prices, actions = _get_symbol_data("SERVOTECH")
    splits = [a for a in actions if a.action_type == "STOCK_SPLIT"]
    assert len(splits) == 2

    adjusted = apply_backward_adjustment(raw_prices, splits)
    adj_map = {r.trade_date: r for r in adjusted}
    raw_map = {r["trade_date"]: r for r in raw_prices}

    # Regime A: 2023-02-02 (before first split)
    date_a = datetime.date(2023, 2, 2)
    assert adj_map[date_a].cumulative_multiplier == Decimal("10.000000")
    assert adj_map[date_a].close == (raw_map[date_a]["close"] / Decimal("10.0")).quantize(Decimal("0.000001"))
    assert adj_map[date_a].volume == Decimal(raw_map[date_a]["volume"]) * Decimal("10.0")
    assert adj_map[date_a].verify_traded_value_invariance(raw_map[date_a]["close"], raw_map[date_a]["volume"])

    # Regime B: 2023-02-03 (on first split, before second split)
    date_b = datetime.date(2023, 2, 3)
    assert adj_map[date_b].cumulative_multiplier == Decimal("2.000000")
    assert adj_map[date_b].close == (raw_map[date_b]["close"] / Decimal("2.0")).quantize(Decimal("0.000001"))
    assert adj_map[date_b].volume == Decimal(raw_map[date_b]["volume"]) * Decimal("2.0")
    assert adj_map[date_b].verify_traded_value_invariance(raw_map[date_b]["close"], raw_map[date_b]["volume"])

    # Regime C: 2023-07-28 (on second split)
    date_c = datetime.date(2023, 7, 28)
    assert adj_map[date_c].cumulative_multiplier == Decimal("1.000000")
    assert adj_map[date_c].close == raw_map[date_c]["close"]
    assert adj_map[date_c].volume == Decimal(raw_map[date_c]["volume"])


def test_rebuild_adjustment_idempotence():
    """
    Verifies that running the backward adjustment engine repeatedly produces identical results.
    """
    raw_prices, actions = _get_symbol_data("TATASTEEL")
    adj_run1 = apply_backward_adjustment(raw_prices, actions, version="v1.0")
    adj_run2 = apply_backward_adjustment(raw_prices, actions, version="v1.0")

    assert len(adj_run1) == len(adj_run2)
    for r1, r2 in zip(adj_run1, adj_run2):
        assert r1.trade_date == r2.trade_date
        assert r1.close == r2.close
        assert r1.volume == r2.volume
        assert r1.cumulative_multiplier == r2.cumulative_multiplier
        assert r1.applied_action_ids == r2.applied_action_ids


def test_raw_prices_database_immutability():
    """
    Verifies that raw prices table remains strictly untouched at 1,855,370 records.
    """
    with get_db() as db:
        cnt = db.execute(select(func.count(DailyPriceRaw.id))).scalar()
        assert cnt == 1855370, f"Raw price records must remain 1,855,370, got {cnt}"


def test_position_accounting_economic_value_invariance():
    """
    Tests open position mechanical transformation across corporate action.
    
    A position held through a split or bonus must have identical economic value
    before and after the mechanical adjustment, without double-applying the multiplier.
    """
    # 1. ACTUAL_UNITS mode (physical share transformation)
    # Long 100 HAL shares @ 4000.00, stop 3800.00, target 4400.00
    pos_pre = SimulatedPosition(
        symbol="HAL",
        quantity=Decimal("100"),
        entry_price=Decimal("4000.00"),
        stop_loss=Decimal("3800.00"),
        target=Decimal("4400.00"),
        accounting_convention="ACTUAL_UNITS",
    )
    assert pos_pre.position_value == Decimal("400000.00")

    # 2:1 split action (M=2)
    split_ca = CorporateActionEvent(
        action_id="CA-HAL-2023-09-28-STOCK_SPLIT",
        instrument_id="inst_hal",
        symbol="HAL",
        action_type="STOCK_SPLIT",
        ex_date=datetime.date(2023, 9, 28),
        share_multiplier=Decimal("2.000000"),
        purpose="2:1 split",
    )

    pos_post = transform_position_for_action(pos_pre, split_ca)
    assert pos_post.quantity == Decimal("200")
    assert pos_post.entry_price == Decimal("2000.00")
    assert pos_post.stop_loss == Decimal("1900.00")
    assert pos_post.target == Decimal("2200.00")
    # Value must remain strictly invariant!
    assert pos_post.position_value == pos_pre.position_value == Decimal("400000.00")

    # 2. ADJUSTED_UNITS mode (already normalized coordinates)
    pos_adj_pre = SimulatedPosition(
        symbol="HAL",
        quantity=Decimal("200"),
        entry_price=Decimal("2000.00"),
        stop_loss=Decimal("1900.00"),
        target=Decimal("2200.00"),
        accounting_convention="ADJUSTED_UNITS",
    )
    pos_adj_post = transform_position_for_action(pos_adj_pre, split_ca)
    # Must NOT double apply the split in adjusted coordinate space!
    assert pos_adj_post.quantity == Decimal("200")
    assert pos_adj_post.entry_price == Decimal("2000.00")
    assert pos_adj_post.position_value == pos_adj_pre.position_value == Decimal("400000.00")


def test_identity_and_reorganization_events_do_not_adjust_prices():
    """
    Verifies that CAPITAL_REORGANIZATION and ETF_SCHEME_RESTRUCTURING return M=1.0.
    """
    assert resolve_action_multiplier("CAPITAL_REORGANIZATION", Decimal("2.0")) == Decimal("1.000000")
    assert resolve_action_multiplier("ETF_SCHEME_RESTRUCTURING", Decimal("10.0")) == Decimal("1.000000")
    assert resolve_action_multiplier("IDENTITY_AUDIT", Decimal("1.0")) == Decimal("1.000000")
    assert resolve_action_multiplier("STOCK_SPLIT", Decimal("5.0")) == Decimal("5.0")
    assert resolve_action_multiplier("BONUS_ISSUE", Decimal("2.0")) == Decimal("2.0")


def test_dividend_entitlement_specification():
    """
    Verifies dividend entitlement structure:
      Dividends must NOT adjust technical indicator price series.
    """
    div = DividendEntitlement(
        symbol="TCS",
        ex_date=datetime.date(2024, 6, 15),
        record_date=datetime.date(2024, 6, 16),
        cash_per_share=Decimal("28.00"),
    )
    assert div.adjusts_price_series is False
    assert div.accounting_treatment == "CREDIT_CASH_LEDGER"
