import datetime
from typing import Any, Dict, Optional
from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from signal_atlas.db.base import Base


class DailyPriceQuarantine(Base):
    """
    Dedicated storage for quarantined or structurally suspicious source records.
    Preserves exact original payload, line number, source hash, and validation reason
    so that 100% of raw exchange records remain traceable and queryable, while
    isolated from downstream analytical calculations.
    """
    __tablename__ = "daily_price_quarantine"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    trade_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    series: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    isin: Mapped[Optional[str]] = mapped_column(String(12), nullable=True, index=True)
    instrument_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    row_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    validation_rule: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_message: Mapped[str] = mapped_column(String(512), nullable=False)
    source_file: Mapped[str] = mapped_column(String(128), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ingestion_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_runs.run_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ingestion_run = relationship("IngestionRun")

    __table_args__ = (
        Index("ix_quarantine_date_symbol", "trade_date", "symbol"),
    )

    def __repr__(self) -> str:
        return (
            f"<DailyPriceQuarantine(date={self.trade_date}, symbol={self.symbol}, "
            f"series={self.series}, rule={self.validation_rule})>"
        )
