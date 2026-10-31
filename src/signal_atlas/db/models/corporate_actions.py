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
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from signal_atlas.db.base import Base


class CorporateAction(Base):
    """
    Canonical Corporate Action Registry.
    Tracks all structural capital events (splits, bonuses, capital reorganizations,
    mergers, and share class changes) with explicit provenance, authoritatively
    verified share multipliers, and identity relationship decisions.
    """
    __tablename__ = "corporate_actions"

    action_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    instrument_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instruments.instrument_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    series: Mapped[str] = mapped_column(String(16), default="EQ", nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ex_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    record_date: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    
    old_isin: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    new_isin: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    
    old_face_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    new_face_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    
    old_share_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    new_share_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    
    share_multiplier: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1.0"), nullable=False)
    cash_entitlement: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    
    purpose: Mapped[str] = mapped_column(String(512), nullable=False)
    issuing_organisation: Mapped[str] = mapped_column(String(64), default="NSE", nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), default="EXCHANGE_CIRCULAR", nullable=False)
    source_circular: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    source_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    publication_date: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    retrieved_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    identity_decision: Mapped[str] = mapped_column(String(32), default="UNIFIED_IDENTITY", nullable=False)
    verification_status: Mapped[str] = mapped_column(String(64), default="VERIFIED", nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), default="v1.0", nullable=False)
    
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    instrument: Mapped["Instrument"] = relationship("Instrument")

    __table_args__ = (
        Index("ix_corporate_actions_date_symbol", "ex_date", "symbol"),
        Index("ix_corporate_actions_type_status", "action_type", "verification_status"),
    )

    def __repr__(self) -> str:
        return (
            f"<CorporateAction(id={self.action_id}, symbol={self.symbol}, type={self.action_type}, "
            f"ex_date={self.ex_date}, mult={self.share_multiplier}, status={self.verification_status})>"
        )
