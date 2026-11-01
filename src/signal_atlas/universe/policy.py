import datetime
from decimal import Decimal
from typing import Optional, Set, Tuple

from signal_atlas.universe.models import EligibilityReason, UniverseConfig


def is_common_equity_isin(isin: str) -> bool:
    """
    Verifies that the ISIN represents common corporate equity (INE prefix).
    Excludes mutual fund/ETF schemes (INF), rights entitlements (IN9), and debt (IN0, IN8).
    """
    if not isin or len(isin) < 3:
        return False
    return isin.startswith("INE")


def is_rights_entitlement(symbol: str, isin: str, series: str) -> bool:
    """
    Identifies temporary rights entitlement instruments based on exchange naming,
    ISIN depository allocation, and series conventions.
    """
    if not symbol:
        return False
    if symbol.endswith("-RE") or "-RE-" in symbol:
        return True
    if isin and isin.startswith("IN9"):
        return True
    if series and series.upper() == "RE":
        return True
    return False


def is_permitted_trading_series(
    series: str,
    permitted_series: Tuple[str, ...],
    include_sme: bool = False,
) -> bool:
    """
    Validates trading series against permitted equity series (default: EQ, BE).
    SME series ('SM') is permitted only if include_sme is True.
    """
    if not series:
        return False
    s_upper = series.upper()
    if s_upper in permitted_series:
        return True
    if include_sme and s_upper == "SM":
        return True
    return False


def evaluate_instrument_eligibility(
    instrument_id: str,
    symbol: str,
    isin: str,
    series: str,
    observed_sessions_count: int,
    lookback_sessions: int,
    average_daily_turnover: Optional[Decimal],
    median_daily_turnover: Optional[Decimal],
    latest_raw_close: Optional[Decimal],
    as_of_date: datetime.date,
    listing_date: Optional[datetime.date],
    delisting_date: Optional[datetime.date],
    quarantined_instrument_ids: Set[str],
    config: UniverseConfig,
    first_observed_trade_date: Optional[datetime.date] = None,
    valid_turnover_sessions_count: int = 0,
) -> Tuple[bool, EligibilityReason, str]:
    """
    Evaluates an instrument against point-in-time universe eligibility criteria.
    Returns:
        (is_eligible, eligibility_reason, reason_detail)
    """
    # 1. Point-in-time listing and delisting boundaries
    if listing_date is not None and listing_date > as_of_date:
        return False, EligibilityReason.EXCLUDED_FUTURE_LISTING, f"Listed after decision date: {listing_date} > {as_of_date}"

    if first_observed_trade_date is not None and first_observed_trade_date > as_of_date:
        return False, EligibilityReason.EXCLUDED_FUTURE_LISTING, f"First observed trade date {first_observed_trade_date} is after decision date {as_of_date}"

    if delisting_date is not None and delisting_date < as_of_date:
        return False, EligibilityReason.EXCLUDED_ALREADY_DELISTED, f"Delisted prior to decision date: {delisting_date} < {as_of_date}"

    # 2. Quarantine policy check
    if instrument_id in quarantined_instrument_ids:
        return False, EligibilityReason.EXCLUDED_QUARANTINED, "Instrument is quarantined due to unresolved corporate actions or data anomalies"

    # 3. Rights Entitlement check
    if is_rights_entitlement(symbol, isin, series):
        return False, EligibilityReason.EXCLUDED_RIGHTS_ENTITLEMENT, f"Rights entitlement instrument: symbol={symbol}, isin={isin}, series={series}"

    # 4. Security classification: Common Equity vs ETF/Mutual Fund
    if not is_common_equity_isin(isin):
        if isin and isin.startswith("INF"):
            return False, EligibilityReason.EXCLUDED_ETF_MUTUAL_FUND, f"Excluded ETF/Mutual Fund scheme ISIN: {isin}"
        return False, EligibilityReason.EXCLUDED_NON_EQUITY_SERIES, f"Non-equity ISIN prefix: {isin}"

    # 5. Permitted trading series
    if not is_permitted_trading_series(series, config.permitted_series, config.include_sme):
        return False, EligibilityReason.EXCLUDED_NON_EQUITY_SERIES, f"Trading series '{series}' not in permitted series {config.permitted_series}"

    # 6. Minimum trading history / completeness
    if lookback_sessions > 0:
        completeness = Decimal(observed_sessions_count) / Decimal(lookback_sessions)
    else:
        completeness = Decimal("0")

    if completeness < config.min_trading_completeness:
        pct = (completeness * Decimal("100")).quantize(Decimal("0.1"))
        req_pct = (config.min_trading_completeness * Decimal("100")).quantize(Decimal("0.1"))
        return (
            False,
            EligibilityReason.EXCLUDED_INSUFFICIENT_HISTORY,
            f"Trading completeness {pct}% ({observed_sessions_count}/{lookback_sessions} sessions) below required {req_pct}%",
        )

    # 6b. Minimum turnover data completeness (coverage of valid non-null turnover sessions)
    if lookback_sessions > 0:
        turnover_completeness = Decimal(valid_turnover_sessions_count) / Decimal(lookback_sessions)
    else:
        turnover_completeness = Decimal("0")

    if turnover_completeness < config.min_turnover_completeness:
        t_pct = (turnover_completeness * Decimal("100")).quantize(Decimal("0.1"))
        req_t_pct = (config.min_turnover_completeness * Decimal("100")).quantize(Decimal("0.1"))
        return (
            False,
            EligibilityReason.EXCLUDED_INSUFFICIENT_TURNOVER_COVERAGE,
            f"Turnover data completeness {t_pct}% ({valid_turnover_sessions_count}/{lookback_sessions} sessions) below required {req_t_pct}%",
        )

    # 7. Liquidity threshold (ADTV)
    if average_daily_turnover is None or average_daily_turnover < config.min_adtv:
        adtv_str = f"₹{average_daily_turnover:,.2f}" if average_daily_turnover is not None else "None"
        req_str = f"₹{config.min_adtv:,.2f}"
        return (
            False,
            EligibilityReason.EXCLUDED_BELOW_LIQUIDITY_THRESHOLD,
            f"Average daily traded value {adtv_str} below minimum {req_str}",
        )

    # 8. Optional Median Liquidity threshold
    if config.min_median_turnover is not None:
        if median_daily_turnover is None or median_daily_turnover < config.min_median_turnover:
            med_str = f"₹{median_daily_turnover:,.2f}" if median_daily_turnover is not None else "None"
            req_str = f"₹{config.min_median_turnover:,.2f}"
            return (
                False,
                EligibilityReason.EXCLUDED_BELOW_MEDIAN_LIQUIDITY,
                f"Median daily traded value {med_str} below minimum {req_str}",
            )

    # 9. Minimum absolute price filter (penny stock cutoff, using raw price)
    if latest_raw_close is None or latest_raw_close < config.min_price:
        p_str = f"₹{latest_raw_close:.2f}" if latest_raw_close is not None else "None"
        req_str = f"₹{config.min_price:.2f}"
        return (
            False,
            EligibilityReason.EXCLUDED_BELOW_MIN_PRICE,
            f"Latest raw close {p_str} below minimum price filter {req_str}",
        )

    # 10. Optional maximum price filter
    if config.max_price is not None and latest_raw_close is not None:
        if latest_raw_close > config.max_price:
            return (
                False,
                EligibilityReason.EXCLUDED_ABOVE_MAX_PRICE,
                f"Latest raw close ₹{latest_raw_close:.2f} exceeds maximum price filter ₹{config.max_price:.2f}",
            )

    return True, EligibilityReason.ELIGIBLE, "Passed all point-in-time eligibility and liquidity criteria"
