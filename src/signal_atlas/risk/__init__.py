"""
risk package - Configuration-Driven Risk Engine and Trade Setup Module for Signal Atlas.
"""

from signal_atlas.risk.engine import RiskEngine
from signal_atlas.risk.models import (
    CheckSeverity,
    OpenPositionRisk,
    PortfolioState,
    RiskCheckResult,
    RiskConfig,
    SurveillanceStatus,
    TradeSetup,
)
from signal_atlas.risk.sizing import PositionSizingResult, calculate_position_sizing

__all__ = [
    "CheckSeverity",
    "OpenPositionRisk",
    "PortfolioState",
    "RiskCheckResult",
    "RiskConfig",
    "SurveillanceStatus",
    "TradeSetup",
    "PositionSizingResult",
    "calculate_position_sizing",
    "RiskEngine",
]
