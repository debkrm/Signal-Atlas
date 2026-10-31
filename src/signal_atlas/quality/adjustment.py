"""
adjustment.py - Mathematical Price, Volume, and Point-in-Time Adjustment Engine.

Implements official NSE corporate-action adjustment rules, point-in-time (PIT) adjustment
calculation, ex-date previous-close alignment, high-precision adjusted volume,
and exact exchange turnover preservation.

Key Concepts & Invariants:
  1. Traded Value vs Close-Volume Invariance:
     NSE-reported traded_value is transaction turnover, NOT closing price * volume.
     - adjusted_traded_value is preserved strictly equal to raw_traded_value.
     - adjusted_vwap * adjusted_volume == raw_traded_value (turnover-preserving).
     - adjusted_close * adjusted_volume == raw_close * raw_volume is a separate
       mathematical close-volume product invariant, not an exchange turnover reconciliation.
  2. Point-in-Time (PIT) Factors:
     For observation date T and simulated decision/as-of date A:
       M(T, A) = Product_{k: T < ex_date_k <= A} M_k
     A backtest as-of date A never applies corporate actions effective after date A.
  3. Ex-Date Previous-Close Alignment:
     On an ex-date T, raw_prev_close is published in pre-action share units.
     The ex-date action must be included when adjusting prev_close:
       M_prev_close(T, A) = Product_{k: T <= ex_date_k <= A} M_k
     This ensures adjusted_prev_close is in the identical share coordinate as adjusted OHLC.
"""

import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Dict, Any, Tuple
import uuid
from pydantic import BaseModel, Field

from signal_atlas.db.models import DailyPriceRaw, DailyPriceAdjusted, CorporateAction
from signal_atlas.quality.corporate_actions import CorporateActionEvent


def calculate_split_multiplier(old_face_value: Decimal, new_face_value: Decimal) -> Decimal:
    """
    NSE Split Rule:
    For a face-value split from A to B:
    M_split = A / B
    """
    if new_face_value <= 0:
        raise ValueError(f"New face value must be positive, got {new_face_value}")
    return (old_face_value / new_face_value).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def calculate_bonus_multiplier(existing_shares: Decimal, bonus_shares: Decimal) -> Decimal:
    """
    NSE Bonus Rule:
    For a bonus issue of A shares for every B existing shares held (A:B):
    M_bonus = (A + B) / B
    Example 1:1 bonus -> (1 + 1) / 1 = 2.0
    Example 1:2 bonus -> (1 + 2) / 2 = 1.5
    """
    if existing_shares <= 0:
        raise ValueError(f"Existing share quantity must be positive, got {existing_shares}")
    return ((bonus_shares + existing_shares) / existing_shares).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def resolve_action_multiplier(action_type: str, multiplier: Decimal) -> Decimal:
    """
    Determines whether a corporate action adjusts prices.
    Only verified STOCK_SPLIT and BONUS_ISSUE adjust prices.
    CAPITAL_REORGANIZATION and ETF_SCHEME_RESTRUCTURING return 1.0 (no automatic adjustment).
    """
    if action_type in ("STOCK_SPLIT", "BONUS_ISSUE"):
        return multiplier
    return Decimal("1.000000")


class AdjustedPriceRecord(BaseModel):
    """
    Represents an analytical backward-adjusted price record.
    Raw price values in daily_prices_raw are never modified; this represents the adjusted analytical view.
    Volume is stored as high-precision Decimal to guarantee exact volume scaling.
    Traded value represents physical currency turnover and is preserved unchanged.
    """
    trade_date: datetime.date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    last: Optional[Decimal] = None
    prev_close: Decimal          # Adjusted previous close in current share units
    raw_prev_close: Decimal      # Original unadjusted previous close published by NSE
    volume: Decimal              # High-precision adjusted volume (raw_vol * M)
    raw_volume: int              # Unchanged raw exchange volume
    traded_value: Optional[Decimal] = None        # Preserved exchange turnover
    raw_traded_value: Optional[Decimal] = None    # Original NSE-reported turnover
    raw_vwap: Optional[Decimal] = None
    adjusted_vwap: Optional[Decimal] = None
    cumulative_multiplier: Decimal
    prev_close_multiplier: Decimal
    adjustment_version: str = "v1.4"
    adjustment_vintage: str = "LATEST_VINTAGE"
    adjustment_as_of_date: Optional[datetime.date] = None
    applied_action_ids: List[str] = Field(default_factory=list)

    def verify_close_volume_product_invariance(
        self,
        raw_close: Decimal,
        raw_vol: int,
        rel_tolerance: Decimal = Decimal("0.0001"),
        abs_tolerance: Decimal = Decimal("0.05"),
    ) -> bool:
        """
        Verifies that P_adjusted * V_adjusted == P_raw * V_raw within defined numerical precision.
        Accommodates repeating decimal fractions (e.g. M=1.5 -> 2/3) via relative tolerance.
        Note: This is a close-volume product mathematical invariant, NOT exchange turnover!
        """
        adj_prod = self.close * self.volume
        raw_prod = raw_close * Decimal(raw_vol)
        diff = abs(adj_prod - raw_prod)
        if diff <= abs_tolerance:
            return True
        if raw_prod > Decimal("0"):
            return (diff / raw_prod) <= rel_tolerance
        return False

    def verify_traded_value_invariance(
        self,
        raw_close: Decimal,
        raw_vol: int,
        rel_tolerance: Decimal = Decimal("0.0001"),
        abs_tolerance: Decimal = Decimal("0.05"),
    ) -> bool:
        """Deprecated alias: use verify_close_volume_product_invariance."""
        return self.verify_close_volume_product_invariance(raw_close, raw_vol, rel_tolerance, abs_tolerance)

    def verify_turnover_invariance(self) -> bool:
        """
        Verifies that reported exchange turnover is preserved strictly unchanged.
        """
        return self.traded_value == self.raw_traded_value

    def verify_vwap_turnover_relationship(self, rel_tolerance: Decimal = Decimal("0.0001")) -> bool:
        """
        Verifies the true turnover-preserving relationship:
          adjusted_vwap * adjusted_volume == raw_traded_value
        within numerical precision. Safe when volume is zero or turnover is missing/null.
        """
        if self.raw_traded_value is None or self.adjusted_vwap is None or self.raw_volume == 0:
            return True
        calc_turnover = self.adjusted_vwap * self.volume
        diff = abs(calc_turnover - self.raw_traded_value)
        if diff <= Decimal("0.05"):
            return True
        if self.raw_traded_value > Decimal("0"):
            return (diff / self.raw_traded_value) <= rel_tolerance
        return False


def is_action_eligible_for_price_adjustment(ca: Any) -> bool:
    """
    Determines whether a corporate action is verified and mathematically eligible to adjust historical prices/volumes.
    
    Eligibility rules:
    - Must be a verified STOCK_SPLIT or BONUS_ISSUE action.
    - Multiplier must be strictly positive and differ from 1.0 (splits > 1.0, reverse splits < 1.0).
    - Neutral actions (multiplier == 1.0) do NOT adjust prices.
    - Unverified actions or ETF restructurings do NOT adjust prices.
    """
    action_type = getattr(ca, "action_type", None) or (ca.get("action_type") if isinstance(ca, dict) else None)
    multiplier = getattr(ca, "share_multiplier", None) or (ca.get("share_multiplier") if isinstance(ca, dict) else None)
    verification_status = getattr(ca, "verification_status", None) or (ca.get("verification_status") if isinstance(ca, dict) else None)
    
    if action_type not in ("STOCK_SPLIT", "BONUS_ISSUE"):
        return False
    if verification_status != "VERIFIED":
        return False
    if multiplier is None:
        return False
    mult_dec = Decimal(str(multiplier))
    if mult_dec <= Decimal("0"):
        return False
    if mult_dec == Decimal("1.000000"):
        return False
    return True


def calculate_cumulative_adjustment_factors(
    dates: List[datetime.date],
    corporate_actions: List[CorporateActionEvent | CorporateAction],
    as_of_date: Optional[datetime.date] = None,
) -> Dict[datetime.date, Tuple[Decimal, Decimal, List[str]]]:
    """
    Computes backward adjustment factors for historical dates, optionally anchored
    to a point-in-time decision/as-of date A.

    Formulas:
      For trade date T and decision date A:
        M_cum(T, A) = Product_{k: T < ex_date_k <= A} M_k       (for OHLC, volume, and VWAP)
        M_prev_close(T, A) = Product_{k: T <= ex_date_k <= A} M_k (for previous close)

    Returns:
      Dict mapping trade_date -> (cumulative_multiplier, prev_close_multiplier, applied_action_ids)
    """
    valid_actions = [
        ca for ca in corporate_actions
        if is_action_eligible_for_price_adjustment(ca)
    ]

    # Filter actions by point-in-time as-of date A, if specified
    if as_of_date is not None:
        valid_actions = [ca for ca in valid_actions if ca.ex_date <= as_of_date]

    date_factors: Dict[datetime.date, Tuple[Decimal, Decimal, List[str]]] = {}

    for d in dates:
        cum_mult = Decimal("1.000000")
        prev_mult = Decimal("1.000000")
        applied_ids: List[str] = []

        for ca in valid_actions:
            # For OHLC and volume: applies to observations strictly before ex-date (T < ex_date <= A)
            if d < ca.ex_date:
                cum_mult *= ca.share_multiplier
                applied_ids.append(ca.action_id)

            # For previous close: applies if ex-date is on or after observation date (T <= ex_date <= A)
            # This adjusts the ex-date row's prev_close from old share coordinate to new share coordinate.
            if d <= ca.ex_date:
                prev_mult *= ca.share_multiplier

        date_factors[d] = (
            cum_mult.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
            prev_mult.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
            applied_ids,
        )

    return date_factors


def apply_backward_adjustment(
    raw_records: List[DailyPriceRaw | Dict[str, Any]],
    corporate_actions: List[CorporateActionEvent | CorporateAction],
    version: str = "v1.4",
    as_of_date: Optional[datetime.date] = None,
    vintage: Optional[str] = None,
) -> List[AdjustedPriceRecord]:
    """
    Applies backward adjustment to historical OHLCV records:
      P_adjusted = P_raw / M_cum (high-precision Decimal, not rounded to tick size)
      V_adjusted = V_raw * M_cum (high-precision Decimal, not rounded to integer)
      PrevClose_adjusted = PrevClose_raw / M_prev_close (aligned on ex-date)
      Traded Value = raw_traded_value (strictly invariant exchange turnover, preserves None)
      VWAP_adjusted = VWAP_raw / M_cum (turnover-preserving, preserves None when missing/zero)
    """
    if not raw_records:
        return []

    # If as_of_date is given, filter raw records to dates <= as_of_date
    if as_of_date is not None:
        raw_records = [
            r for r in raw_records
            if (r.trade_date if hasattr(r, "trade_date") else r["trade_date"]) <= as_of_date
        ]
        if not raw_records:
            return []

    # Ensure records are sorted chronologically
    sorted_records = sorted(
        raw_records,
        key=lambda r: (r.trade_date if hasattr(r, "trade_date") else r["trade_date"])
    )

    dates = [r.trade_date if hasattr(r, "trade_date") else r["trade_date"] for r in sorted_records]
    cum_factors = calculate_cumulative_adjustment_factors(dates, corporate_actions, as_of_date=as_of_date)

    valid_actions = [
        ca for ca in corporate_actions
        if is_action_eligible_for_price_adjustment(ca)
    ]
    if as_of_date is not None:
        valid_actions = [ca for ca in valid_actions if ca.ex_date <= as_of_date]

    eff_vintage = vintage or ("POINT_IN_TIME" if as_of_date is not None else "LATEST_VINTAGE")
    effective_as_of = as_of_date or datetime.date(2024, 12, 31)

    adjusted_records: List[AdjustedPriceRecord] = []

    for idx, r in enumerate(sorted_records):
        t_date = r.trade_date if hasattr(r, "trade_date") else r["trade_date"]
        r_open = Decimal(str(r.open if hasattr(r, "open") else r["open"]))
        r_high = Decimal(str(r.high if hasattr(r, "high") else r["high"]))
        r_low = Decimal(str(r.low if hasattr(r, "low") else r["low"]))
        r_close = Decimal(str(r.close if hasattr(r, "close") else r["close"]))
        raw_last = r.last if hasattr(r, "last") else r.get("last")
        r_last = Decimal(str(raw_last)) if raw_last is not None else None
        r_prev_close = Decimal(str(r.prev_close if hasattr(r, "prev_close") else r["prev_close"]))
        r_vol = int(r.volume if hasattr(r, "volume") else r["volume"])
        
        # Preserve missing/null turnover as None, do NOT default to Decimal("0.00")
        raw_val = r.traded_value if hasattr(r, "traded_value") else r.get("traded_value")
        r_val = Decimal(str(raw_val)) if raw_val is not None else None

        # Calculate raw VWAP from reported turnover and volume safely (safeguards against zero volume or missing turnover)
        raw_vwap = (
            (r_val / Decimal(r_vol)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            if r_vol > 0 and r_val is not None
            else None
        )

        m_cum, m_prev, action_ids = cum_factors[t_date]

        if m_cum == Decimal("1.000000"):
            adj_open = r_open
            adj_high = r_high
            adj_low = r_low
            adj_close = r_close
            adj_last = r_last
            adj_vol = Decimal(r_vol).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            adj_vwap = raw_vwap
        else:
            adj_open = (r_open / m_cum).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            adj_high = (r_high / m_cum).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            adj_low = (r_low / m_cum).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            adj_close = (r_close / m_cum).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            adj_last = (r_last / m_cum).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP) if r_last is not None else None
            adj_vol = (Decimal(r_vol) * m_cum).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            adj_vwap = (raw_vwap / m_cum).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP) if raw_vwap is not None else None

        # Previous close adjustment (incorporates ex-date action when T == ex_date)
        # Check if the exchange already published prev_close in the post-action coordinate on ex-date
        # (e.g. KAUSHALYA 2024-02-06, DRCSYSTEMS 2022-03-21 where trading was suspended prior to resumption)
        eff_prev_mult = m_prev
        if idx > 0:
            prev_rec = sorted_records[idx - 1]
            prior_raw_close = Decimal(str(prev_rec.close if hasattr(prev_rec, "close") else prev_rec["close"]))
            for ca in valid_actions:
                if ca.ex_date == t_date:
                    scaled_candidate = prior_raw_close / ca.share_multiplier
                    # If exchange raw_prev_close is already closer to prior_close / M than prior_close,
                    # the exchange has already factored ca.share_multiplier into raw_prev_close.
                    if abs(r_prev_close - scaled_candidate) < abs(r_prev_close - prior_raw_close):
                        eff_prev_mult = eff_prev_mult / ca.share_multiplier

        if eff_prev_mult == Decimal("1.000000"):
            adj_prev_close = r_prev_close
        else:
            adj_prev_close = (r_prev_close / eff_prev_mult).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

        adjusted_records.append(
            AdjustedPriceRecord(
                trade_date=t_date,
                open=adj_open,
                high=adj_high,
                low=adj_low,
                close=adj_close,
                last=adj_last,
                prev_close=adj_prev_close,
                raw_prev_close=r_prev_close,
                volume=adj_vol,
                raw_volume=r_vol,
                traded_value=r_val,
                raw_traded_value=r_val,
                raw_vwap=raw_vwap,
                adjusted_vwap=adj_vwap,
                cumulative_multiplier=m_cum,
                prev_close_multiplier=eff_prev_mult,
                adjustment_version=version,
                adjustment_vintage=eff_vintage,
                adjustment_as_of_date=effective_as_of,
                applied_action_ids=action_ids,
            )
        )

    return adjusted_records


class SimulatedPosition(BaseModel):
    """
    Trading position model for mechanical corporate-action accounting.
    """
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    stop_loss: Optional[Decimal] = None
    target: Optional[Decimal] = None
    accounting_convention: str = "ACTUAL_UNITS"  # "ACTUAL_UNITS" or "ADJUSTED_UNITS"

    @property
    def position_value(self) -> Decimal:
        """Total economic value of the position."""
        return (self.quantity * self.entry_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def transform_position_for_action(
    position: SimulatedPosition,
    corporate_action: CorporateActionEvent | CorporateAction,
) -> SimulatedPosition:
    """
    Transforms a position across a mechanical corporate action.
    
    Invariant:
      Economic value immediately before and after the action must be identical:
      Value_pre = Q_pre * P_pre
      Value_post = Q_post * P_post
      Value_pre == Value_post (assuming zero market movement, fees, or taxes).
    """
    m = resolve_action_multiplier(corporate_action.action_type, corporate_action.share_multiplier)
    
    if position.accounting_convention == "ADJUSTED_UNITS":
        # In adjusted coordinate space, the position quantity and price are already normalized.
        # DO NOT double-apply the corporate action!
        return position.model_copy()
        
    elif position.accounting_convention == "ACTUAL_UNITS":
        new_qty = (position.quantity * m).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        new_entry = (position.entry_price / m).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        new_stop = (position.stop_loss / m).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP) if position.stop_loss else None
        new_target = (position.target / m).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP) if position.target else None
        
        return SimulatedPosition(
            symbol=position.symbol,
            quantity=new_qty,
            entry_price=new_entry,
            stop_loss=new_stop,
            target=new_target,
            accounting_convention="ACTUAL_UNITS",
        )
    else:
        raise ValueError(f"Unknown accounting convention: {position.accounting_convention}")


class DividendEntitlement(BaseModel):
    """
    Pending event specification for cash dividend entitlements.
    Dividends must NOT adjust technical indicator price series.
    """
    symbol: str
    ex_date: datetime.date
    record_date: datetime.date
    cash_per_share: Decimal
    qualification_rule: str = "Long settled quantity held as of record date close"
    accounting_treatment: str = "CREDIT_CASH_LEDGER"
    adjusts_price_series: bool = False


def get_point_in_time_adjusted_history(
    instrument_id: str,
    as_of_date: datetime.date,
    series: str = "EQ",
    db: Optional[Any] = None,
    adjustment_version: str = "v1.4",
) -> List[AdjustedPriceRecord]:
    """
    Retrieves dynamically adjusted historical price records for an instrument
    as observable at a specific historical point-in-time decision date A.

    Properties:
      1. Decision-date bounded: Only raw price observations where trade_date <= as_of_date
         are retrieved. No future prices enter the calculation.
      2. Strictly point-in-time factors: Corporate actions where ex_date > as_of_date are
         strictly excluded:
           M(T, A) = Product_{k: T < ex_date_k <= A} M_k       (for OHLC, volume, and VWAP)
           M_prev(T, A) = Product_{k: T <= ex_date_k <= A} M_k (for ex-date prev_close)
      3. O(1) storage overhead: Dynamically scales raw prices without storing quadratic
         historical vintages in PostgreSQL.
      4. Explicit version tagging: Explicitly tags output records with adjustment_version (default "v1.4").
    """
    from signal_atlas.db.session import get_db
    from sqlalchemy import select

    def _fetch_and_adjust(session: Any) -> List[AdjustedPriceRecord]:
        query = select(DailyPriceRaw).where(
            DailyPriceRaw.instrument_id == instrument_id,
            DailyPriceRaw.trade_date <= as_of_date,
        )
        if series:
            query = query.where(DailyPriceRaw.series == series)
        raw_prices = session.execute(query.order_by(DailyPriceRaw.trade_date)).scalars().all()

        if not raw_prices:
            return []

        cas = session.execute(
            select(CorporateAction).where(
                CorporateAction.instrument_id == instrument_id,
                CorporateAction.ex_date <= as_of_date,
                CorporateAction.action_type.in_(("STOCK_SPLIT", "BONUS_ISSUE")),
                CorporateAction.verification_status == "VERIFIED",
            ).order_by(CorporateAction.ex_date)
        ).scalars().all()

        return apply_backward_adjustment(
            raw_prices,
            cas,
            version=adjustment_version,
            as_of_date=as_of_date,
            vintage="POINT_IN_TIME",
        )

    if db is not None:
        return _fetch_and_adjust(db)
    else:
        with get_db() as session:
            return _fetch_and_adjust(session)
