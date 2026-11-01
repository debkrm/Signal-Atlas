"""
test_metrics_corrected.py - Unit test verifying hand-calculated 6-trade metrics per Task 5 (D5, D12).
"""

import datetime
from decimal import Decimal
import pytest

from signal_atlas.backtest.metrics import calculate_comprehensive_metrics
from signal_atlas.backtest.models import EquitySnapshot, ExitReason, PositionRecord


def test_six_trade_hand_verified_metrics():
    """
    Tests exact mathematical definitions of:
    - Net profit factor (net P&L based, not gross)
    - R-multiple profit factor
    - Costs as percentage of total gross P&L (not winners only)
    - Net expectancy in R
    - Post-tax calculations
    All verified by hand.
    """
    # 6 trades across 2 months
    t1 = PositionRecord(
        trade_id="TRD-0001", instrument_id="inst-1", symbol="ABC",
        entry_date=datetime.date(2023, 1, 5), exit_date=datetime.date(2023, 1, 15),
        entry_price=Decimal("100.00"), exit_price=Decimal("110.00"), quantity=100,
        entry_gross_value=Decimal("10000.00"), exit_gross_value=Decimal("11000.00"),
        entry_fees=Decimal("15.00"), exit_fees=Decimal("15.00"),
        initial_stop_loss=Decimal("95.00"), initial_target_price=Decimal("110.00"),
        initial_risk_per_share=Decimal("5.00"), holding_sessions_count=10,
        exit_reason=ExitReason.PROFIT_TARGET,
        gross_pnl=Decimal("1000.00"), net_pnl=Decimal("970.00"),
        net_return_pct=Decimal("9.70"), realized_r_multiple=Decimal("1.94"),
    )
    t2 = PositionRecord(
        trade_id="TRD-0002", instrument_id="inst-2", symbol="DEF",
        entry_date=datetime.date(2023, 1, 10), exit_date=datetime.date(2023, 1, 20),
        entry_price=Decimal("200.00"), exit_price=Decimal("190.00"), quantity=50,
        entry_gross_value=Decimal("10000.00"), exit_gross_value=Decimal("9500.00"),
        entry_fees=Decimal("12.50"), exit_fees=Decimal("12.50"),
        initial_stop_loss=Decimal("190.00"), initial_target_price=Decimal("220.00"),
        initial_risk_per_share=Decimal("10.00"), holding_sessions_count=10,
        exit_reason=ExitReason.STOP_LOSS,
        gross_pnl=Decimal("-500.00"), net_pnl=Decimal("-525.00"),
        net_return_pct=Decimal("-5.25"), realized_r_multiple=Decimal("-1.05"),
    )
    t3 = PositionRecord(
        trade_id="TRD-0003", instrument_id="inst-3", symbol="GHI",
        entry_date=datetime.date(2023, 1, 12), exit_date=datetime.date(2023, 1, 25),
        entry_price=Decimal("50.00"), exit_price=Decimal("55.00"), quantity=200,
        entry_gross_value=Decimal("10000.00"), exit_gross_value=Decimal("11000.00"),
        entry_fees=Decimal("10.00"), exit_fees=Decimal("10.00"),
        initial_stop_loss=Decimal("47.50"), initial_target_price=Decimal("55.00"),
        initial_risk_per_share=Decimal("2.50"), holding_sessions_count=13,
        exit_reason=ExitReason.PROFIT_TARGET,
        gross_pnl=Decimal("1000.00"), net_pnl=Decimal("980.00"),
        net_return_pct=Decimal("9.80"), realized_r_multiple=Decimal("1.96"),
    )
    t4 = PositionRecord(
        trade_id="TRD-0004", instrument_id="inst-4", symbol="JKL",
        entry_date=datetime.date(2023, 2, 2), exit_date=datetime.date(2023, 2, 12),
        entry_price=Decimal("150.00"), exit_price=Decimal("140.00"), quantity=60,
        entry_gross_value=Decimal("9000.00"), exit_gross_value=Decimal("8400.00"),
        entry_fees=Decimal("15.00"), exit_fees=Decimal("15.00"),
        initial_stop_loss=Decimal("140.00"), initial_target_price=Decimal("170.00"),
        initial_risk_per_share=Decimal("10.00"), holding_sessions_count=10,
        exit_reason=ExitReason.STOP_LOSS,
        gross_pnl=Decimal("-600.00"), net_pnl=Decimal("-630.00"),
        net_return_pct=Decimal("-7.00"), realized_r_multiple=Decimal("-1.05"),
    )
    t5 = PositionRecord(
        trade_id="TRD-0005", instrument_id="inst-5", symbol="MNO",
        entry_date=datetime.date(2023, 2, 5), exit_date=datetime.date(2023, 2, 18),
        entry_price=Decimal("80.00"), exit_price=Decimal("88.00"), quantity=125,
        entry_gross_value=Decimal("10000.00"), exit_gross_value=Decimal("11000.00"),
        entry_fees=Decimal("12.50"), exit_fees=Decimal("12.50"),
        initial_stop_loss=Decimal("76.00"), initial_target_price=Decimal("88.00"),
        initial_risk_per_share=Decimal("4.00"), holding_sessions_count=13,
        exit_reason=ExitReason.PROFIT_TARGET,
        gross_pnl=Decimal("1000.00"), net_pnl=Decimal("975.00"),
        net_return_pct=Decimal("9.75"), realized_r_multiple=Decimal("1.95"),
    )
    t6 = PositionRecord(
        trade_id="TRD-0006", instrument_id="inst-6", symbol="PQR",
        entry_date=datetime.date(2023, 2, 8), exit_date=datetime.date(2023, 2, 22),
        entry_price=Decimal("120.00"), exit_price=Decimal("110.00"), quantity=80,
        entry_gross_value=Decimal("9600.00"), exit_gross_value=Decimal("8800.00"),
        entry_fees=Decimal("17.50"), exit_fees=Decimal("17.50"),
        initial_stop_loss=Decimal("110.00"), initial_target_price=Decimal("140.00"),
        initial_risk_per_share=Decimal("10.00"), holding_sessions_count=14,
        exit_reason=ExitReason.STOP_LOSS,
        gross_pnl=Decimal("-800.00"), net_pnl=Decimal("-835.00"),
        net_return_pct=Decimal("-8.70"), realized_r_multiple=Decimal("-1.04375"),
    )

    trades = [t1, t2, t3, t4, t5, t6]
    equity_curve = [
        EquitySnapshot(trade_date=datetime.date(2023, 1, 1), cash=Decimal("1000000"), portfolio_value=Decimal("0"), total_equity=Decimal("1000000"), drawdown_pct=Decimal("0"), open_positions_count=0),
        EquitySnapshot(trade_date=datetime.date(2023, 1, 31), cash=Decimal("1001425"), portfolio_value=Decimal("0"), total_equity=Decimal("1001425"), drawdown_pct=Decimal("0"), open_positions_count=0),
        EquitySnapshot(trade_date=datetime.date(2023, 2, 28), cash=Decimal("1000935"), portfolio_value=Decimal("0"), total_equity=Decimal("1000935"), drawdown_pct=Decimal("0.05"), open_positions_count=0),
    ]

    metrics = calculate_comprehensive_metrics(trades, equity_curve, initial_capital=Decimal("1000000.00"))

    # Assertions
    assert metrics["total_trades"] == 6
    assert metrics["winning_trades"] == 3
    assert metrics["losing_trades"] == 3
    assert metrics["win_rate_pct"] == 50.0

    # Net profit factor = 2925.00 / 1990.00 = 1.47
    assert metrics["net_profit_factor"] == 1.47
    assert metrics["profit_factor"] == 1.47

    # R-multiple profit factor = (1.94 + 1.96 + 1.95) / (1.05 + 1.05 + 1.04375) = 5.85 / 3.14375 = 1.86
    assert metrics["r_profit_factor"] == 1.86

    # Total gross P&L = (1000 - 500 + 1000 - 600 + 1000 - 800) = 1100.00
    assert metrics["total_gross_pnl"] == 1100.00
    assert metrics["total_fees_paid"] == 165.00

    # Costs as % of total gross P&L = 165.00 / 1100.00 * 100 = 15.0%
    assert metrics["costs_as_pct_gross_pnl"] == 15.0

    # Net P&L = 2925 - 1990 = 935.00
    assert metrics["net_pnl"] == 935.00

    # Expectancy in R = (1.94 - 1.05 + 1.96 - 1.05 + 1.95 - 1.04375) / 6 = 2.70625 / 6 = +0.451 R
    assert metrics["expectancy_r"] == 0.451

    # Post-tax net P&L (20% STCG) = 935 - 187 = 748.00
    assert metrics["post_tax_net_pnl"] == 748.00
