import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
)
from signal_atlas.db.base import Base


class JournalEntryRecord(Base):
    """
    SQLAlchemy model for trade journal entries in Signal Atlas.
    Records both taken and skipped trade setups, actual manual execution fills,
    exit details, realized transaction costs, realized P&L, and behavioral notes.
    """
    __tablename__ = "journal_entries"

    entry_id = Column(String(64), primary_key=True)
    symbol = Column(String(32), nullable=False, index=True)
    signal_date = Column(Date, nullable=False, index=True)
    strategy_id = Column(String(64), nullable=False, default="trend_pullback")
    strategy_version = Column(String(32), nullable=False, default="v1.0")

    # Decision state: TAKEN, SKIPPED
    decision = Column(String(16), nullable=False)
    decision_reason = Column(Text, nullable=True)

    # Status: OPEN, CLOSED, SKIPPED, CANCELLED
    status = Column(String(16), nullable=False, default="OPEN", index=True)

    # Planned Setup Geometry & Risk
    planned_entry_price = Column(Numeric(12, 4), nullable=False)
    planned_stop_loss = Column(Numeric(12, 4), nullable=False)
    planned_target_price = Column(Numeric(12, 4), nullable=False)
    planned_quantity = Column(Integer, nullable=False)
    planned_risk_amount = Column(Numeric(14, 2), nullable=False)
    planned_reward_to_risk = Column(Numeric(6, 2), nullable=False)

    # Execution / Fills (for taken trades)
    actual_entry_date = Column(Date, nullable=True)
    actual_entry_price = Column(Numeric(12, 4), nullable=True)
    actual_quantity = Column(Integer, nullable=True)
    actual_exit_date = Column(Date, nullable=True, index=True)
    actual_exit_price = Column(Numeric(12, 4), nullable=True)
    exit_reason = Column(String(32), nullable=True)

    # Financial Realization & Comparison Metrics
    entry_slippage = Column(Numeric(10, 4), nullable=True)
    realized_gross_pnl = Column(Numeric(14, 2), nullable=True)
    realized_costs = Column(Numeric(14, 2), nullable=True)
    realized_net_pnl = Column(Numeric(14, 2), nullable=True)
    realized_pnl_pct = Column(Numeric(8, 4), nullable=True)
    realized_r_multiple = Column(Numeric(8, 2), nullable=True)

    # Notes & Audit
    notes = Column(Text, nullable=True)
    tags = Column(String(256), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
    closed_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<JournalEntryRecord(entry_id='{self.entry_id}', symbol='{self.symbol}', "
            f"decision='{self.decision}', status='{self.status}', "
            f"planned_entry={self.planned_entry_price}, planned_qty={self.planned_quantity})>"
        )
