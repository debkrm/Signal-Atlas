import datetime
from typing import Optional
from sqlalchemy import Boolean, Date, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from signal_atlas.db.base import Base


class TradingCalendar(Base):
    __tablename__ = "trading_calendar"

    trade_date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    is_trading_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    holiday_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<TradingCalendar(date={self.trade_date}, is_trading={self.is_trading_day}, holiday={self.holiday_name})>"
