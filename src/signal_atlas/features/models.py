import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field


class TechnicalFeatures(BaseModel):
    """
    Deterministic technical indicator features for an equity instrument on as_of_date.
    Computed strictly over point-in-time adjusted analytical prices up to as_of_date.
    """
    instrument_id: str
    symbol: str
    as_of_date: datetime.date

    # Price levels (point-in-time adjusted)
    close: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    raw_close: Decimal

    # Moving Averages
    ema_20: Optional[Decimal] = None
    ema_50: Optional[Decimal] = None

    # Momentum
    rsi_14: Optional[Decimal] = None

    # Trend / MACD (12, 26, 9)
    macd_line: Optional[Decimal] = None
    macd_signal: Optional[Decimal] = None
    macd_hist: Optional[Decimal] = None

    # Volatility / Invalidation
    atr_14: Optional[Decimal] = None

    # Volume & Liquidity (20-day rolling)
    avg_volume_20: Optional[int] = None
    rolling_adtv_20: Optional[Decimal] = None
    volume_ratio_20: Optional[Decimal] = None  # Today's volume / avg_volume_20

    # Weekly Trend derived from daily data
    weekly_close: Optional[Decimal] = None
    weekly_ema_10: Optional[Decimal] = None
    weekly_trend_bullish: Optional[bool] = None

    # Relative Strength vs Benchmark (trailing 50-session excess return)
    relative_strength_50: Optional[Decimal] = None

    # Data sufficiency flag
    sufficient_history: bool = True
    history_sessions_count: int = 0
