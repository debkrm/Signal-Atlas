import datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
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

    allow_partial_lookback: bool = Field(default=False, description="Explicit opt-in to allow lookback windows with fewer sessions than lookback_sessions")

    def canonical_dict(self) -> Dict[str, Any]:
        """
        Deterministic canonical dictionary containing every parameter that can affect:
        - Instrument eligibility
        - Liquidity calculations
        - Ranking
        - Lookback construction
        - Security classification
        - Provenance and code/data revisions
        Decimals are serialized as exact canonical strings without lossy conversion.
        """
        def _ser(val: Any) -> Any:
            if isinstance(val, Decimal):
                return f"{val:f}"
            if isinstance(val, (datetime.date, datetime.datetime)):
                return val.isoformat()
            if isinstance(val, (tuple, list, set)):
                return sorted(list(val))
            return val

        raw: Dict[str, Any] = {
            "adjustment_version": self.adjustment_version,
            "allow_partial_lookback": self.allow_partial_lookback,
            "code_revision": self.code_revision,
            "config_version": self.config_version,
            "data_coverage_end": _ser(self.data_coverage_end),
            "data_coverage_start": _ser(self.data_coverage_start),
            "include_sme": self.include_sme,
            "lookback_sessions": self.lookback_sessions,
            "max_price": _ser(self.max_price) if self.max_price is not None else None,
            "min_adtv": _ser(self.min_adtv),
            "min_median_turnover": _ser(self.min_median_turnover) if self.min_median_turnover is not None else None,
            "min_price": _ser(self.min_price),
            "min_trading_completeness": _ser(self.min_trading_completeness),
            "min_turnover_completeness": _ser(self.min_turnover_completeness),
            "permitted_series": _ser(self.permitted_series),
            "raw_data_version": self.raw_data_version,
            "top_n": self.top_n,
        }
        return dict(sorted(raw.items()))

    def canonical_json(self) -> str:
        """Deterministic UTF-8 JSON representation with sorted keys and no extraneous whitespace."""
        return json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def config_hash(self) -> str:
        """
        Cryptographic SHA-256 fingerprint (16 hex chars) of all calculation inputs.
        Guarantees deterministic collision-free identity for any parameter change.
        """
        digest = hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
        return digest[:16]

    @property
    def config_identifier(self) -> str:
        """
        Canonical immutable configuration identifier incorporating semantic version and hash.
        e.g., UNIV-v1.0-e3b0c44298fc1c14
        """
        return f"UNIV-v{self.config_version}-{self.config_hash}"


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
