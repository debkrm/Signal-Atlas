import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class SignalState(str, Enum):
    """
    First executable signal states per Signal Atlas operating contract:
    - BUY: New delivery purchase candidate.
    - AVOID: No position recommended or setup criteria failed.
    """
    BUY = "BUY"
    AVOID = "AVOID"


class MarketContext(BaseModel):
    """
    Point-in-time macro market context on as_of_date.
    Used by the strategy engine to gate new long positions.
    """
    as_of_date: datetime.date
    benchmark_symbol: str = "NIFTY50"
    benchmark_close: Optional[Decimal] = None
    benchmark_ema_200: Optional[Decimal] = None
    is_market_regime_bullish: bool = True
    regime_detail: Optional[str] = None


class StrategyParameters(BaseModel):
    """Base configuration model for deterministic strategies."""
    strategy_id: str
    strategy_version: str


class TrendPullbackParameters(StrategyParameters):
    """
    Explicit, versioned parameters for Trend-Pullback Swing Strategy.
    """
    strategy_id: str = "trend_pullback"
    strategy_version: str = "v1.0"

    # Moving Average Trend Filters
    require_ema_alignment: bool = True  # EMA 20 > EMA 50
    require_price_above_ema50: bool = True

    # Pullback Proximity
    max_ema20_distance_pct: Decimal = Decimal("0.04")  # Price within 4% of EMA 20

    # RSI Momentum Reset Zone
    min_rsi: Decimal = Decimal("40.00")
    max_rsi: Decimal = Decimal("60.00")

    # Higher timeframe / weekly trend confirmation
    require_weekly_trend_bullish: bool = True

    # Invalidation & Target (ATR multiples or independent R-multiples per Task 7)
    stop_atr_multiplier: Decimal = Decimal("1.50")
    target_atr_multiplier: Decimal = Decimal("3.00")
    target_r_multiple: Optional[Decimal] = Decimal("2.00")  # When set, target = entry + target_r_multiple * risk
    min_reward_to_risk: Decimal = Decimal("1.50")

    # Next-session entry validation bounds
    max_entry_gap_pct: Decimal = Decimal("0.02")  # 2% max opening gap tolerance


class StrategyCandidate(BaseModel):
    """
    Deterministic setup candidate produced by a pure strategy evaluation on day t.
    """
    instrument_id: str
    symbol: str
    signal_date: datetime.date
    signal_state: SignalState
    strategy_id: str
    strategy_version: str

    is_valid: bool
    rejection_reason: Optional[str] = None
    rejection_detail: Optional[str] = None

    # Reference levels derived on day t
    close_t: Decimal
    entry_reference: Decimal
    entry_zone_low: Decimal
    entry_zone_high: Decimal
    stop_loss: Decimal
    target_price: Decimal

    # Risk metrics
    risk_per_share: Decimal
    reward_per_share: Decimal
    reward_to_risk: Decimal
    atr_14: Optional[Decimal] = None
    rsi_14: Optional[Decimal] = None

    adtv: Optional[Decimal] = None
    rank_score: Optional[Decimal] = None
    features_summary: Dict[str, Any] = Field(default_factory=dict)
