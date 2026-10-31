import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from signal_atlas.backtest.costs import TransactionCostModel


class ExitReason(str, Enum):
    PROFIT_TARGET = "PROFIT_TARGET"
    STOP_LOSS = "STOP_LOSS"
    MAX_HOLDING_TIME = "MAX_HOLDING_TIME"
    END_OF_SIMULATION = "END_OF_SIMULATION"


class BacktestConfig(BaseModel):
    """
    Configuration parameters for backtesting execution.
    """
    initial_capital: Decimal = Decimal("1000000.00")  # ₹10 Lakhs starting portfolio
    max_concurrent_positions: int = 10
    risk_per_trade_pct: Decimal = Decimal("0.01")     # 1% risk of current equity per trade
    max_capital_per_position_pct: Decimal = Decimal("0.20")  # Max 20% capital in single stock
    max_adtv_participation_pct: Decimal = Decimal("0.02")    # Max 2% of 20-day ADTV
    max_holding_sessions: int = 30                     # Swing maximum duration in trading sessions
    min_history_sessions: int = 50                     # Minimum price history bars required
    cost_model: TransactionCostModel = Field(default_factory=TransactionCostModel)


class PositionRecord(BaseModel):
    """
    Completed trade position lifecycle audit.
    """
    trade_id: str
    instrument_id: str
    symbol: str

    entry_date: datetime.date
    entry_price: Decimal
    quantity: int
    entry_gross_value: Decimal
    entry_fees: Decimal

    initial_stop_loss: Decimal
    initial_target_price: Decimal
    initial_risk_per_share: Decimal

    exit_date: datetime.date
    exit_price: Decimal
    exit_gross_value: Decimal
    exit_fees: Decimal
    exit_reason: ExitReason

    holding_sessions_count: int
    gross_pnl: Decimal
    net_pnl: Decimal
    net_return_pct: Decimal
    realized_r_multiple: Decimal  # Net PnL / (Quantity * Initial Risk)


class EquitySnapshot(BaseModel):
    """Daily equity curve point."""
    trade_date: datetime.date
    cash: Decimal
    portfolio_value: Decimal
    total_equity: Decimal
    drawdown_pct: Decimal
    open_positions_count: int


class BacktestMetrics(BaseModel):
    """
    Comprehensive performance statistics for evaluation.
    """
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: Decimal = Decimal("0.00")

    gross_profit: Decimal = Decimal("0.00")
    gross_loss: Decimal = Decimal("0.00")
    total_fees_paid: Decimal = Decimal("0.00")
    net_pnl: Decimal = Decimal("0.00")
    total_return_pct: Decimal = Decimal("0.00")

    profit_factor: Decimal = Decimal("0.00")
    average_r_multiple: Decimal = Decimal("0.00")
    expectancy_per_trade: Decimal = Decimal("0.00")
    max_drawdown_pct: Decimal = Decimal("0.00")
    average_holding_sessions: Decimal = Decimal("0.00")
    exposure_time_pct: Decimal = Decimal("0.00")


class BaselineComparison(BaseModel):
    """
    Benchmark comparison against Buy & Hold and Random Entry baselines.
    """
    strategy_return_pct: Decimal
    strategy_max_drawdown_pct: Decimal
    strategy_win_rate_pct: Decimal

    buy_and_hold_return_pct: Decimal
    buy_and_hold_max_drawdown_pct: Decimal

    random_entry_return_pct: Decimal
    random_entry_win_rate_pct: Decimal
    random_entry_profit_factor: Decimal


class BacktestResult(BaseModel):
    """
    Complete backtest run deliverable.
    """
    strategy_id: str
    strategy_version: str
    start_date: datetime.date
    end_date: datetime.date
    config: BacktestConfig
    metrics: BacktestMetrics
    trades: List[PositionRecord]
    equity_curve: List[EquitySnapshot]
    baseline_comparison: Optional[BaselineComparison] = None
