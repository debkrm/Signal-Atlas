"""
backtest package - Deterministic Backtesting Engine for Signal Atlas.
"""

from signal_atlas.backtest.costs import ExecutionCostBreakdown, TransactionCostModel
from signal_atlas.backtest.models import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    BaselineComparison,
    EquitySnapshot,
    ExitReason,
    PositionRecord,
)
from signal_atlas.backtest.simulator import BacktestSimulator

__all__ = [
    "ExecutionCostBreakdown",
    "TransactionCostModel",
    "BacktestConfig",
    "BacktestMetrics",
    "BacktestResult",
    "BaselineComparison",
    "EquitySnapshot",
    "ExitReason",
    "PositionRecord",
    "BacktestSimulator",
]
