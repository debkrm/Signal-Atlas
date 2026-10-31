"""
Technical Features & Indicators Package for Signal Atlas.
"""

from signal_atlas.features.engine import TechnicalFeatureEngine
from signal_atlas.features.indicators import (
    compute_atr,
    compute_ema,
    compute_macd,
    compute_relative_strength,
    compute_rsi,
    compute_sma,
    compute_weekly_trend,
    aggregate_daily_to_weekly,
)
from signal_atlas.features.models import TechnicalFeatures

__all__ = [
    "TechnicalFeatures",
    "TechnicalFeatureEngine",
    "compute_atr",
    "compute_ema",
    "compute_macd",
    "compute_relative_strength",
    "compute_rsi",
    "compute_sma",
    "compute_weekly_trend",
    "aggregate_daily_to_weekly",
]
