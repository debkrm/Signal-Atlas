import datetime
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from signal_atlas.db.base import Base


class UniverseSnapshotRecord(Base):
    """
    Persisted metadata for a deterministic Point-in-Time Universe evaluation.
    Tracks configuration parameters, lookback window dates, adjustment version,
    and member counts for exact auditability and reproducibility.
    """
    __tablename__ = "universe_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    as_of_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    config_version: Mapped[str] = mapped_column(String(32), default="1.0", nullable=False)
    config_identifier: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    lookback_sessions: Mapped[int] = mapped_column(Integer, nullable=False)
    lookback_start_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    lookback_end_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    min_adtv: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    min_trading_completeness: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    min_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    permitted_series: Mapped[str] = mapped_column(String(64), nullable=False)
    adjustment_version: Mapped[str] = mapped_column(String(32), default="v1.4", nullable=False)
    raw_data_version: Mapped[str] = mapped_column(String(64), default="RAW_NSE_2022_2024_V1", nullable=False)
    data_coverage_start: Mapped[datetime.date] = mapped_column(Date, default=datetime.date(2022, 1, 3), nullable=False)
    data_coverage_end: Mapped[datetime.date] = mapped_column(Date, default=datetime.date(2024, 12, 31), nullable=False)
    code_revision: Mapped[str] = mapped_column(String(64), default="phase-1b-iii.1", nullable=False)
    total_instruments_evaluated: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    members: Mapped[List["UniverseMemberRecord"]] = relationship(
        "UniverseMemberRecord", back_populates="snapshot", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "as_of_date", "config_identifier", "adjustment_version",
            name="uq_universe_snapshot_date_config_ver"
        ),
        Index("ix_universe_snapshot_date_ver", "as_of_date", "adjustment_version"),
    )

    def __repr__(self) -> str:
        return (
            f"<UniverseSnapshotRecord(id={self.snapshot_id}, as_of={self.as_of_date}, "
            f"eligible={self.eligible_count}, ver={self.adjustment_version})>"
        )


class UniverseMemberRecord(Base):
    """
    Individual instrument evaluation within a Point-in-Time Universe Snapshot.
    Stores point-in-time symbol, ISIN, trading activity metrics, liquidity measures,
    eligibility status, rank, and explicit exclusion reason.
    """
    __tablename__ = "universe_members"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("universe_snapshots.snapshot_id", ondelete="CASCADE"), nullable=False, index=True
    )
    instrument_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("instruments.instrument_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    isin: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    series: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_sessions_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_sessions_count: Mapped[int] = mapped_column(Integer, nullable=False)
    trading_completeness: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    expected_lookback_sessions: Mapped[int] = mapped_column(Integer, default=126, nullable=False)
    valid_turnover_sessions_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    turnover_data_completeness: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0.0000"), nullable=False)
    total_turnover: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    average_daily_turnover: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    median_daily_turnover: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    null_turnover_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    zero_turnover_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    positive_turnover_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latest_raw_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    is_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    exclusion_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    exclusion_detail: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    snapshot: Mapped["UniverseSnapshotRecord"] = relationship("UniverseSnapshotRecord", back_populates="members")
    instrument = relationship("Instrument")

    __table_args__ = (
        UniqueConstraint("snapshot_id", "instrument_id", name="uq_universe_member_snapshot_inst"),
        Index("ix_universe_member_snapshot_eligible", "snapshot_id", "is_eligible"),
        Index("ix_universe_member_snapshot_rank", "snapshot_id", "rank"),
    )

    def __repr__(self) -> str:
        return (
            f"<UniverseMemberRecord(snap={self.snapshot_id}, sym={self.symbol}, "
            f"eligible={self.is_eligible}, adtv={self.average_daily_turnover}, reason={self.exclusion_reason})>"
        )
