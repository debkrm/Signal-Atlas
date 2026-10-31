"""
Strategy Package for Signal Atlas.
"""

from signal_atlas.strategy.base import Strategy
from signal_atlas.strategy.models import (
    MarketContext,
    SignalState,
    StrategyCandidate,
    StrategyParameters,
    TrendPullbackParameters,
)
from signal_atlas.strategy.trend_pullback import TrendPullbackStrategy

__all__ = [
    "Strategy",
    "SignalState",
    "MarketContext",
    "StrategyCandidate",
    "StrategyParameters",
    "TrendPullbackParameters",
    "TrendPullbackStrategy",
]
