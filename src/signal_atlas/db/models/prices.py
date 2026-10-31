import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from signal_atlas.db.base import Base


class DailyPriceRaw(Base):
    __tablename__ = "daily_prices_raw"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    instrument_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instruments.instrument_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    trade_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    last: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    prev_close: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    traded_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    trades_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    series: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="NSE_CM_UDIFF", nullable=False)
    ingestion_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_runs.run_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ingestion_run: Mapped["IngestionRun"] = relationship("IngestionRun", back_populates="prices")

    __table_args__ = (
        UniqueConstraint("instrument_id", "trade_date", "series", name="uq_daily_price_inst_date_series"),
        Index("ix_daily_prices_date_series", "trade_date", "series"),
    )

    def __repr__(self) -> str:
        return (
            f"<DailyPriceRaw(inst_id={self.instrument_id}, date={self.trade_date}, "
            f"close={self.close}, vol={self.volume})>"
        )


class DailyPriceAdjusted(Base):
    """
    Derived Historical Adjusted Price Dataset.
    Stores backward-adjusted prices, high-precision adjusted volume, and invariant traded value.
    Raw records in daily_prices_raw are never modified.
    """
    __tablename__ = "daily_prices_adjusted"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    instrument_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instruments.instrument_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    trade_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    series: Mapped[str] = mapped_column(String(16), nullable=False)
    
    open: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    last: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6), nullable=True)
    prev_close: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    raw_prev_close: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    
    volume: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    raw_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    traded_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    raw_traded_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    raw_vwap: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6), nullable=True)
    adjusted_vwap: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6), nullable=True)
    
    cumulative_multiplier: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1.0"), nullable=False)
    applied_action_ids: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    adjustment_version: Mapped[str] = mapped_column(String(32), default="v1.1", nullable=False)
    adjustment_vintage: Mapped[str] = mapped_column(String(32), default="LATEST_VINTAGE", nullable=False)
    adjustment_as_of_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    adjustment_run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    instrument: Mapped["Instrument"] = relationship("Instrument")

    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "trade_date", "series", "adjustment_version", "adjustment_as_of_date",
            name="uq_adj_price_inst_date_series_ver_asof"
        ),
        Index("ix_adj_prices_date_series", "trade_date", "series"),
        Index("ix_adj_prices_inst_date", "instrument_id", "trade_date"),
        Index("ix_adj_prices_pit", "instrument_id", "adjustment_as_of_date", "trade_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<DailyPriceAdjusted(inst_id={self.instrument_id}, date={self.trade_date}, "
            f"close={self.close}, vol={self.volume}, mult={self.cumulative_multiplier})>"
        )

