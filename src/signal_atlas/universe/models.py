import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field


class EligibilityReason(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    EXCLUDED_ETF_MUTUAL_FUND = "EXCLUDED_ETF_MUTUAL_FUND"
    EXCLUDED_RIGHTS_ENTITLEMENT = "EXCLUDED_RIGHTS_ENTITLEMENT"
    EXCLUDED_NON_EQUITY_SERIES = "EXCLUDED_NON_EQUITY_SERIES"
    EXCLUDED_QUARANTINED = "EXCLUDED_QUARANTINED"
    EXCLUDED_FUTURE_LISTING = "EXCLUDED_FUTURE_LISTING"
    EXCLUDED_ALREADY_DELISTED = "EXCLUDED_ALREADY_DELISTED"
    EXCLUDED_INSUFFICIENT_HISTORY = "EXCLUDED_INSUFFICIENT_HISTORY"
    EXCLUDED_INSUFFICIENT_TURNOVER_COVERAGE = "EXCLUDED_INSUFFICIENT_TURNOVER_COVERAGE"
    EXCLUDED_AMBIGUOUS_SERIES_HISTORY = "EXCLUDED_AMBIGUOUS_SERIES_HISTORY"
    EXCLUDED_BELOW_LIQUIDITY_THRESHOLD = "EXCLUDED_BELOW_LIQUIDITY_THRESHOLD"
    EXCLUDED_BELOW_MEDIAN_LIQUIDITY = "EXCLUDED_BELOW_MEDIAN_LIQUIDITY"
    EXCLUDED_BELOW_MIN_PRICE = "EXCLUDED_BELOW_MIN_PRICE"
    EXCLUDED_ABOVE_MAX_PRICE = "EXCLUDED_ABOVE_MAX_PRICE"
    EXCLUDED_RANK_CUTOFF = "EXCLUDED_RANK_CUTOFF"


class UniverseConfig(BaseModel):
    """
    Immutable specification of Point-in-Time Liquidity Universe parameters.
    """
    model_config = ConfigDict(frozen=True)

    lookback_sessions: int = Field(default=126, description="Completed trading sessions lookback window (~6 months)")
    min_adtv: Decimal = Field(default=Decimal("5000000.00"), description="Minimum Average Daily Traded Value in INR")
    min_trading_completeness: Decimal = Field(default=Decimal("0.85"), description="Minimum fraction of sessions traded (0.85 = 85%)")
    min_turnover_completeness: Decimal = Field(default=Decimal("0.80"), description="Minimum fraction of lookback sessions with valid non-null turnover (0.80 = 80%)")
    min_price: Decimal = Field(default=Decimal("10.00"), description="Minimum raw share price in INR (penny stock cutoff)")
    max_price: Optional[Decimal] = Field(default=None, description="Optional maximum raw share price")
    permitted_series: Tuple[str, ...] = Field(default=("EQ", "BE"), description="Allowed cash equity series")
    include_sme: bool = Field(default=False, description="Whether to include SME exchange listings ('SM' series)")
    min_median_turnover: Optional[Decimal] = Field(default=None, description="Optional minimum median daily traded value")
    top_n: Optional[int] = Field(default=None, description="Optional cap on eligible universe size ranked by ADTV")
    adjustment_version: str = Field(default="v1.4", description="Authoritative candidate adjustment dataset version")
    raw_data_version: str = Field(default="RAW_NSE_2022_2024_V1", description="Raw dataset snapshot identifier")
    data_coverage_start: datetime.date = Field(default=datetime.date(2022, 1, 3), description="Data coverage window start date")
    data_coverage_end: datetime.date = Field(default=datetime.date(2024, 12, 31), description="Data coverage window end date")
    code_revision: str = Field(default="phase-1b-iii.1", description="Code revision or build identifier")
    config_version: str = Field(default="1.0", description="Semantic version of universe policy specification")

    @property
    def config_identifier(self) -> str:
        """Deterministic human-readable unique configuration identifier."""
        series_str = "_".join(sorted(self.permitted_series))
        if self.include_sme and "SM" not in self.permitted_series:
            series_str += "_SM"
        adtv_str = f"{int(self.min_adtv)}"
        comp_str = f"{int(self.min_trading_completeness * 100)}"
        turn_comp_str = f"-TC{int(self.min_turnover_completeness * 100)}"
        price_str = f"P{int(self.min_price)}"
        top_str = f"-TOP{self.top_n}" if self.top_n else ""
        return f"UNIV-v{self.config_version}-L{self.lookback_sessions}-ADT{adtv_str}-C{comp_str}{turn_comp_str}-{price_str}-{series_str}{top_str}"


class UniverseMember(BaseModel):
    """
    Individual security evaluated for historical universe inclusion as of a specific date.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    instrument_id: str
    symbol: str
    isin: str
    series: str
    observed_sessions_count: int
    missing_sessions_count: int
    trading_completeness: Decimal
    expected_lookback_sessions: int = 126
    valid_turnover_sessions_count: int = 0
    turnover_data_completeness: Decimal = Decimal("0.0000")
    total_turnover: Optional[Decimal] = None
    average_daily_turnover: Optional[Decimal] = None
    median_daily_turnover: Optional[Decimal] = None
    null_turnover_count: int = 0
    zero_turnover_count: int = 0
    positive_turnover_count: int = 0
    latest_raw_close: Optional[Decimal] = None
    is_eligible: bool
    rank: Optional[int] = None
    exclusion_reason: Optional[EligibilityReason] = None
    exclusion_detail: Optional[str] = None


class UniverseSnapshot(BaseModel):
    """
    Deterministic snapshot of the eligible and excluded universe for a specific point-in-time date.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    snapshot_id: str
    as_of_date: datetime.date
    lookback_sessions: int
    lookback_start_date: datetime.date
    lookback_end_date: datetime.date
    config: UniverseConfig
    config_identifier: str
    adjustment_version: str = "v1.4"
    raw_data_version: str = "RAW_NSE_2022_2024_V1"
    data_coverage_start: datetime.date = datetime.date(2022, 1, 3)
    data_coverage_end: datetime.date = datetime.date(2024, 12, 31)
    code_revision: str = "phase-1b-iii.1"
    total_instruments_evaluated: int
    eligible_count: int
    excluded_count: int
    eligible_members: List[UniverseMember] = Field(default_factory=list)
    excluded_members: List[UniverseMember] = Field(default_factory=list)

    def get_member(self, instrument_id: str) -> Optional[UniverseMember]:
        """Finds evaluated member by instrument_id."""
        for m in self.eligible_members:
            if m.instrument_id == instrument_id:
                return m
        for m in self.excluded_members:
            if m.instrument_id == instrument_id:
                return m
        return None

    def get_eligible_symbols(self) -> List[str]:
        """Returns sorted list of symbols eligible as of this date."""
        return sorted(m.symbol for m in self.eligible_members)

    def get_eligible_instrument_ids(self) -> List[str]:
        """Returns list of eligible stable instrument IDs."""
        return [m.instrument_id for m in self.eligible_members]
