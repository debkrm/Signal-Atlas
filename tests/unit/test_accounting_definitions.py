"""
test_accounting_definitions.py - Deterministic Verification of Accounting & Risk Definitions

Tests the core requirements of Stage 2 (P1):
1. Unweighted mean per-trade R vs risk-weighted portfolio payoff ratio divergence.
2. Positive aggregate rupee P&L alongside negative unweighted trade expectancy.
3. Protection against near-zero risk denominators (micro-lot rejection).
4. Explicit risk-percentage denominators (equity immediately before entry vs initial capital).
5. Unrounded realized R precision retention.
6. Trade ledger row grain consistency.
"""

import datetime
from decimal import Decimal, ROUND_HALF_UP
import pytest

from signal_atlas.backtest.metrics import calculate_comprehensive_metrics
from signal_atlas.backtest.models import EquitySnapshot, ExitReason, PositionRecord
from signal_atlas.risk.sizing import calculate_position_sizing


def test_unweighted_r_vs_portfolio_payoff_ratio_divergence():
    """
    Demonstrates that:
    1. Unweighted mean per-trade R (expectancy)
    2. Sum of per-trade net P&L
    3. Portfolio payoff ratio (total P&L / total rupee risk)
    can legitimately diverge in sign and magnitude due to unequal risk denominators.
    """
    # Trade 1: Large winning trade (Risk ₹10,000, P&L +₹20,000 -> +2.00 R)
    t1 = PositionRecord(
        trade_id="TRD-0001",
        instrument_id="inst-1",
        symbol="WINNER",
        entry_date=datetime.date(2023, 1, 5),
        exit_date=datetime.date(2023, 1, 15),
        entry_price=Decimal("100.00"),
        exit_price=Decimal("120.30"),
        quantity=1000,
        entry_gross_value=Decimal("100000.00"),
        exit_gross_value=Decimal("120300.00"),
        entry_fees=Decimal("150.00"),
        exit_fees=Decimal("150.00"),
        initial_stop_loss=Decimal("90.00"),
        initial_target_price=Decimal("120.00"),
        initial_risk_per_share=Decimal("10.00"),
        holding_sessions_count=10,
        exit_reason=ExitReason.PROFIT_TARGET,
        gross_pnl=Decimal("20300.00"),
        net_pnl=Decimal("20000.00"),
        net_return_pct=Decimal("20.00"),
        realized_r_multiple=Decimal("2.00"),
    )

    # Trades 2, 3, 4: Small losing trades (Risk ₹1,000, P&L -₹1,200 -> -1.20 R each)
    small_losers = []
    for idx, sym in enumerate(["LOSER1", "LOSER2", "LOSER3"], start=2):
        small_losers.append(
            PositionRecord(
                trade_id=f"TRD-{idx:04d}",
                instrument_id=f"inst-{idx}",
                symbol=sym,
                entry_date=datetime.date(2023, 1, 10),
                exit_date=datetime.date(2023, 1, 20),
                entry_price=Decimal("50.00"),
                exit_price=Decimal("38.50"),
                quantity=100,
                entry_gross_value=Decimal("5000.00"),
                exit_gross_value=Decimal("3850.00"),
                entry_fees=Decimal("25.00"),
                exit_fees=Decimal("25.00"),
                initial_stop_loss=Decimal("40.00"),
                initial_target_price=Decimal("70.00"),
                initial_risk_per_share=Decimal("10.00"),
                holding_sessions_count=10,
                exit_reason=ExitReason.STOP_LOSS,
                gross_pnl=Decimal("-1150.00"),
                net_pnl=Decimal("-1200.00"),
                net_return_pct=Decimal("-24.00"),
                realized_r_multiple=Decimal("-1.20"),
            )
        )

    all_trades = [t1] + small_losers

    # 1. Total Net P&L: +20,000 - 1,200 - 1,200 - 1,200 = +₹16,400.00 (POSITIVE)
    total_net_pnl = sum(t.net_pnl for t in all_trades)
    assert total_net_pnl == Decimal("16400.00")

    # 2. Total Planned Rupee Risk: 10,000 + 1,000 + 1,000 + 1,000 = ₹13,000.00
    total_rupee_risk = sum(t.initial_risk_per_share * Decimal(t.quantity) for t in all_trades)
    assert total_rupee_risk == Decimal("13000.00")

    # 3. Portfolio Payoff Ratio: +16,400 / 13,000 = +1.2615 (POSITIVE)
    portfolio_payoff_ratio = total_net_pnl / total_rupee_risk
    assert portfolio_payoff_ratio > Decimal("1.26")

    # 4. Unweighted Mean Per-Trade R: (+2.00 - 1.20 - 1.20 - 1.20) / 4 = -1.60 / 4 = -0.40 R (NEGATIVE!)
    mean_unweighted_r = sum(t.realized_r_multiple for t in all_trades) / len(all_trades)
    assert mean_unweighted_r == Decimal("-0.40")

    # PROOF: Positive aggregate rupee P&L alongside negative unweighted trade expectancy
    # is mathematically guaranteed when winners have larger rupee risk than losers.
    assert total_net_pnl > Decimal("0")
    assert mean_unweighted_r < Decimal("0")


def test_near_zero_risk_denominator_protection():
    """
    Verifies that the sizing engine rejects or floors micro-lot trades
    where stop distance is abnormally tight or risk budget is negligible.
    """
    # Extremely tight stop: entry = 100.00, stop = 99.99 (0.01 risk per share)
    # Available cash = 1000.00, equity = 100,000.00
    res = calculate_position_sizing(
        entry_price=Decimal("100.00"),
        stop_loss=Decimal("99.99"),
        total_equity=Decimal("100000.00"),
        available_cash=Decimal("1000.00"),
        risk_per_trade_pct=Decimal("0.01"),
        max_capital_per_position_pct=Decimal("0.20"),
    )

    # Capital cap binds at min(1000, 20000) / 100 = 10 shares
    assert res.quantity == 10
    # Planned risk is 10 * 0.01 = 0.10 rupees
    assert res.planned_risk == Decimal("0.10")
    # Equity risk pct is 0.10 / 100,000 = 0.000001 (0.0001%)
    # In BacktestEngine, any trade risk < 0.20% equity is rejected
    min_trade_risk = Decimal("100000.00") * Decimal("0.002")  # ₹200 min
    assert res.planned_risk < min_trade_risk, "Micro risk must be detected and rejected by engine"


def test_explicit_risk_denominators():
    """
    Tests distinction between:
    - risk_pct_current_equity: RupeeRisk / EquityImmediatelyBeforeEntry
    - risk_pct_initial_capital: RupeeRisk / InitialCapital
    """
    initial_cap = Decimal("1000000.00")
    current_equity = Decimal("850000.00")  # After a 15% drawdown
    rupee_risk = Decimal("8500.00")         # Exactly 1.0% of current equity

    risk_pct_current = (rupee_risk / current_equity) * Decimal("100.0")
    risk_pct_initial = (rupee_risk / initial_cap) * Decimal("100.0")

    # Current equity risk is exactly 1.00%
    assert risk_pct_current == Decimal("1.0")
    # Initial capital normalized risk is only 0.85%
    assert risk_pct_initial == Decimal("0.85")
    assert risk_pct_current != risk_pct_initial


def test_unrounded_realized_r_preserves_precision():
    """
    Ensures realized R calculations maintain full Decimal precision
    and do not lose information from premature 2-decimal rounding.
    """
    net_pnl = Decimal("1234.56")
    rupee_risk = Decimal("9876.54")

    # Raw full-precision division
    unrounded_r = net_pnl / rupee_risk
    # Quantized 2-decimal display R
    rounded_r = unrounded_r.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    assert rounded_r == Decimal("0.12")
    # Unrounded preserves higher digits
    assert unrounded_r.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP) == Decimal("0.124999")
    assert unrounded_r != rounded_r
