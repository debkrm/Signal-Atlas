"""
models.py - Pydantic Domain Models for Signal Atlas Trade Journal & Paper Trading.
"""

import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class JournalDecision(str, Enum):
    TAKEN = "TAKEN"
    SKIPPED = "SKIPPED"


class JournalStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class ExitReason(str, Enum):
    PROFIT_TARGET = "PROFIT_TARGET"
    STOP_LOSS = "STOP_LOSS"
    TIME_STOP = "TIME_STOP"
    MANUAL = "MANUAL"
    DISCRETIONARY = "DISCRETIONARY"
    INVALIDATION = "INVALIDATION"
    UNKNOWN = "UNKNOWN"


class JournalEntry(BaseModel):
    """
    Complete domain representation of a trade journal entry.
    Tracks planned strategy setup, actual manual fills, execution slippage,
    realized financial outcomes (costs, P&L, R-multiple), and behavioral notes.
    """
    model_config = ConfigDict(from_attributes=True)

    entry_id: str
    symbol: str
    signal_date: datetime.date
    strategy_id: str = "trend_pullback"
    strategy_version: str = "v1.0"

    # Decision & Lifecycle Status
    decision: JournalDecision
    decision_reason: Optional[str] = None
    status: JournalStatus = JournalStatus.OPEN

    # Planned Setup Geometry & Risk
    planned_entry_price: Decimal
    planned_stop_loss: Decimal
    planned_target_price: Decimal
    planned_quantity: int
    planned_risk_amount: Decimal
    planned_reward_to_risk: Decimal

    # Actual Execution & Fills
    actual_entry_date: Optional[datetime.date] = None
    actual_entry_price: Optional[Decimal] = None
    actual_quantity: Optional[int] = None
    actual_exit_date: Optional[datetime.date] = None
    actual_exit_price: Optional[Decimal] = None
    exit_reason: Optional[str] = None

    # Realized Outcomes & Comparisons
    entry_slippage: Optional[Decimal] = None
    realized_gross_pnl: Optional[Decimal] = None
    realized_costs: Optional[Decimal] = None
    realized_net_pnl: Optional[Decimal] = None
    realized_pnl_pct: Optional[Decimal] = None
    realized_r_multiple: Optional[Decimal] = None

    # Notes & Audit Metadata
    notes: Optional[str] = None
    tags: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    closed_at: Optional[datetime.datetime] = None


class JournalSummary(BaseModel):
    """
    Aggregated paper-trading performance analytics.
    Reported separately from backtests to evaluate operational evidence
    and execution quality over a live observation period.
    """
    total_signals_logged: int
    taken_count: int
    skipped_count: int
    open_count: int
    closed_count: int
    cancelled_count: int

    # Win / Loss Statistics (Closed Trades)
    win_count: int = 0
    loss_count: int = 0
    breakeven_count: int = 0
    win_rate_pct: Decimal = Decimal("0.00")

    # Financial Totals (Closed Trades)
    total_gross_pnl: Decimal = Decimal("0.00")
    total_realized_costs: Decimal = Decimal("0.00")
    total_net_pnl: Decimal = Decimal("0.00")
    profit_factor: Optional[Decimal] = None

    # Trade Averages & Multiples
    avg_trade_pnl: Decimal = Decimal("0.00")
    avg_win: Decimal = Decimal("0.00")
    avg_loss: Decimal = Decimal("0.00")
    avg_r_multiple: Optional[Decimal] = None
    max_win: Decimal = Decimal("0.00")
    max_loss: Decimal = Decimal("0.00")

    # Operational & Behavioral Metrics
    avg_holding_days: Decimal = Decimal("0.0")
    avg_entry_slippage: Decimal = Decimal("0.00")
