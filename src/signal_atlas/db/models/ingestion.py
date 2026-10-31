import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Date,
    DateTime,
    Integer,
    JSON,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from signal_atlas.db.base import Base


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    trade_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    validation_issues: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    prices: Mapped[List["DailyPriceRaw"]] = relationship(
        "DailyPriceRaw", back_populates="ingestion_run"
    )

    def __repr__(self) -> str:
        return f"<IngestionRun(id={self.run_id}, date={self.trade_date}, status={self.status}, rows={self.row_count})>"
