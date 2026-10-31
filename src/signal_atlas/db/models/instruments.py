import datetime
from typing import List, Optional
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from signal_atlas.db.base import Base


class Instrument(Base):
    __tablename__ = "instruments"

    instrument_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    listing_date: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    first_observed_trade_date: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True, index=True)
    delisting_date: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    symbol_history: Mapped[List["InstrumentSymbolHistory"]] = relationship(
        "InstrumentSymbolHistory", back_populates="instrument", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Instrument(id={self.instrument_id}, name={self.name}, status={self.status})>"


class InstrumentSymbolHistory(Base):
    __tablename__ = "instrument_symbol_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instruments.instrument_id", ondelete="CASCADE"), nullable=False, index=True
    )
    exchange: Mapped[str] = mapped_column(String(16), default="NSE", nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    isin: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    series: Mapped[str] = mapped_column(String(16), default="EQ", nullable=False)
    valid_from: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="NSE", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    instrument: Mapped["Instrument"] = relationship("Instrument", back_populates="symbol_history")

    __table_args__ = (
        Index("ix_sym_hist_lookup", "exchange", "symbol", "series"),
        Index("ix_isin_hist_lookup", "exchange", "isin"),
    )

    def __repr__(self) -> str:
        return f"<InstrumentSymbolHistory(inst_id={self.instrument_id}, sym={self.symbol}, srs={self.series}, isin={self.isin})>"
