"""
models.py - Risk Engine & Trade Setup Domain Models for Signal Atlas.

Implements Section 9 of Build Instructions and Section 10 of Architecture:
- Configurable risk parameters (capital, risk budget, portfolio limits, liquidity thresholds).
- Strict handling of unknown vs known risk inputs.
- Structured TradeSetup outputs with complete rule audit, sizing breakdown, and provenance.
"""

import datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from signal_atlas.strategy.models import SignalState


class SurveillanceStatus(str, Enum):
    """NSE surveillance classification categories."""
    CLEAR = "CLEAR"
    ASM_STAGE_1 = "ASM_STAGE_1"
    ASM_STAGE_2 = "ASM_STAGE_2"
    ASM_STAGE_3 = "ASM_STAGE_3"
    ASM_STAGE_4 = "ASM_STAGE_4"
    GSM_STAGE_1 = "GSM_STAGE_1"
    GSM_STAGE_2 = "GSM_STAGE_2"
    CIRCUIT_FILTER_RESTRICTED = "CIRCUIT_FILTER_RESTRICTED"
    UNKNOWN = "UNKNOWN"


class CheckSeverity(str, Enum):
    """Severity of a risk check evaluation."""
    BLOCKING = "BLOCKING"  # Vetoes the BUY signal -> forces AVOID
    WARNING = "WARNING"    # Appends visible advisory notice without blocking


class RiskCheckResult(BaseModel):
    """Individual rule evaluation audit record."""
    check_id: str
    name: str
    passed: bool
    severity: CheckSeverity = CheckSeverity.BLOCKING
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class OpenPositionRisk(BaseModel):
    """Risk tracking record for an existing active open position."""
    instrument_id: str
    symbol: str
    sector: Optional[str] = None
    entry_price: Decimal
    current_price: Decimal
    stop_loss: Decimal
    quantity: int
    capital_allocated: Decimal
    open_risk_amount: Decimal  # quantity * (entry_price - stop_loss)


class PortfolioState(BaseModel):
    """Point-in-time portfolio context for evaluating concentration & aggregate risk."""
    as_of_date: datetime.date
    total_equity: Decimal
    available_cash: Decimal
    peak_equity: Optional[Decimal] = None
    open_positions: List[OpenPositionRisk] = Field(default_factory=list)

    @property
    def current_drawdown_pct(self) -> Decimal:
        """Calculates current portfolio drawdown percentage from peak."""
        peak = self.peak_equity or self.total_equity
        if peak <= Decimal("0"):
            return Decimal("0.00")
        dd = ((peak - self.total_equity) / peak) * Decimal("100")
        return max(Decimal("0.00"), dd.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    @property
    def concurrent_positions_count(self) -> int:
        return len(self.open_positions)

    @property
    def total_capital_deployed(self) -> Decimal:
        return sum((p.capital_allocated for p in self.open_positions), Decimal("0.00"))

    @property
    def total_open_risk_amount(self) -> Decimal:
        return sum((p.open_risk_amount for p in self.open_positions), Decimal("0.00"))

    @property
    def total_open_risk_pct(self) -> Decimal:
        if self.total_equity <= Decimal("0"):
            return Decimal("0.00")
        return (self.total_open_risk_amount / self.total_equity).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    def get_sector_exposure(self, sector: Optional[str]) -> Decimal:
        """Calculates total capital deployed in a specific sector."""
        if not sector:
            return Decimal("0.00")
        return sum(
            (p.capital_allocated for p in self.open_positions if p.sector and p.sector.upper() == sector.upper()),
            Decimal("0.00"),
        )


class RiskConfig(BaseModel):
    """
    Configuration parameters for the deterministic Risk Engine.
    """
    total_capital: Decimal = Decimal("1000000.00")  # ₹10 Lakhs starting capital
    risk_per_trade_pct: Decimal = Decimal("0.01")   # 1.0% risk of total equity per trade
    max_capital_per_position_pct: Decimal = Decimal("0.20")  # Max 20% capital in single stock
    max_concurrent_positions: int = 10
    max_total_open_risk_pct: Decimal = Decimal("0.06")  # Max 6.0% total open risk across portfolio
    max_sector_exposure_pct: Decimal = Decimal("0.30")   # Max 30% exposure to single sector
    min_reward_to_risk: Decimal = Decimal("1.50")
    max_holding_sessions: int = 30
    min_adtv: Decimal = Decimal("50000000.00")  # ₹5 Crore 20-day average daily turnover
    max_adtv_participation_pct: Decimal = Decimal("0.02")  # Max 2.0% of 20-day ADTV
    max_entry_deviation_pct: Decimal = Decimal("0.02")      # Max 2.0% opening gap deviation
    require_bullish_market_regime: bool = True
    veto_on_surveillance_flags: bool = True
    block_on_upcoming_earnings_days: Optional[int] = 5
    drawdown_killswitch_pct: Optional[Decimal] = Decimal("10.00")  # Halt new BUYs if drawdown >= 10%


class TradeSetup(BaseModel):
    """
    Published, actionable trade setup produced after passing all strategy and risk gates.
    """
    setup_id: str
    as_of_date: datetime.date
    instrument_id: str
    symbol: str
    series: str = "EQ"
    isin: Optional[str] = None
    sector: Optional[str] = None

    signal_state: SignalState  # BUY or AVOID
    is_approved: bool          # True only if state == BUY and all hard gates passed
    strategy_id: str
    strategy_version: str

    # Reference Entry & Exit Geometry
    entry_price: Decimal
    entry_zone_low: Decimal
    entry_zone_high: Decimal
    stop_loss: Decimal
    target_price: Decimal
    risk_per_share: Decimal
    reward_per_share: Decimal
    reward_to_risk: Decimal

    # Position Sizing
    allocated_quantity: int
    planned_capital_usage: Decimal
    planned_risk_amount: Decimal
    planned_risk_pct: Decimal
    limiting_factor: str  # "RISK_BUDGET", "CAPITAL_CAP", "LIQUIDITY_CAP", or "REJECTED_ZERO"
    sizing_breakdown: Dict[str, Any] = Field(default_factory=dict)

    # Auditing & Explanations
    passed_checks: List[str] = Field(default_factory=list)
    failed_checks: List[RiskCheckResult] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    primary_rejection_reason: Optional[str] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)
