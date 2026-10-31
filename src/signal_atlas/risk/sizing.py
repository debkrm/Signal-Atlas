"""
sizing.py - Deterministic Position Sizing Engine for Signal Atlas.

Implements Section 10.2 of Architecture and Section 9 of Build Instructions:
  Q_risk = floor(Risk Budget / (Entry Price - Stop Price))
  Q_capital = floor(min(Available Cash, Total Capital * Max Capital Pct) / Entry Price)
  Q_liquidity = floor((ADTV * Participation Pct) / Entry Price)
  Q = min(Q_risk, Q_capital, Q_liquidity)
"""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import NamedTuple, Optional


class PositionSizingResult(NamedTuple):
    quantity: int
    q_risk: int
    q_capital: int
    q_liquidity: int
    limiting_factor: str
    planned_capital: Decimal
    planned_risk: Decimal
    planned_risk_pct: Decimal


def calculate_position_sizing(
    entry_price: Decimal,
    stop_loss: Decimal,
    total_equity: Decimal,
    available_cash: Decimal,
    risk_per_trade_pct: Decimal = Decimal("0.01"),
    max_capital_per_position_pct: Decimal = Decimal("0.20"),
    adtv: Optional[Decimal] = None,
    max_adtv_participation_pct: Decimal = Decimal("0.02"),
) -> PositionSizingResult:
    """
    Calculates deterministic delivery position size respecting risk budget,
    capital ceiling, available cash, and liquidity participation constraints.
    """
    if entry_price <= Decimal("0"):
        return PositionSizingResult(
            quantity=0,
            q_risk=0,
            q_capital=0,
            q_liquidity=0,
            limiting_factor="ZERO_QUANTITY",
            planned_capital=Decimal("0.00"),
            planned_risk=Decimal("0.00"),
            planned_risk_pct=Decimal("0.00"),
        )

    risk_per_share = entry_price - stop_loss
    if risk_per_share <= Decimal("0"):
        return PositionSizingResult(
            quantity=0,
            q_risk=0,
            q_capital=0,
            q_liquidity=0,
            limiting_factor="ZERO_QUANTITY",
            planned_capital=Decimal("0.00"),
            planned_risk=Decimal("0.00"),
            planned_risk_pct=Decimal("0.00"),
        )

    # 1. Risk-based Quantity
    risk_budget = total_equity * risk_per_trade_pct
    if risk_budget <= Decimal("0"):
        q_risk = 0
    else:
        q_risk = int((risk_budget / risk_per_share).quantize(Decimal("1"), rounding=ROUND_DOWN))

    # 2. Capital-based Quantity
    capital_cap = total_equity * max_capital_per_position_pct
    capital_budget = max(Decimal("0.00"), min(available_cash, capital_cap))
    q_capital = int((capital_budget / entry_price).quantize(Decimal("1"), rounding=ROUND_DOWN))

    # 3. Liquidity-based Quantity
    if adtv is not None and adtv > Decimal("0") and max_adtv_participation_pct > Decimal("0"):
        liquidity_budget = adtv * max_adtv_participation_pct
        q_liquidity = int((liquidity_budget / entry_price).quantize(Decimal("1"), rounding=ROUND_DOWN))
    else:
        q_liquidity = q_capital

    # 4. Final Minimum Quantity & Limiting Factor
    final_q = min(q_risk, q_capital, q_liquidity)
    final_q = max(0, final_q)

    if final_q == 0:
        limiting_factor = "ZERO_QUANTITY"
    elif final_q == q_liquidity and q_liquidity < q_risk and q_liquidity < q_capital:
        limiting_factor = "LIQUIDITY_CAP"
    elif final_q == q_capital and q_capital < q_risk:
        limiting_factor = "CAPITAL_CAP"
    else:
        limiting_factor = "RISK_BUDGET"

    planned_capital = (entry_price * Decimal(final_q)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    planned_risk = (risk_per_share * Decimal(final_q)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    planned_risk_pct = (
        (planned_risk / total_equity).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if total_equity > Decimal("0")
        else Decimal("0.00")
    )

    return PositionSizingResult(
        quantity=final_q,
        q_risk=q_risk,
        q_capital=q_capital,
        q_liquidity=q_liquidity,
        limiting_factor=limiting_factor,
        planned_capital=planned_capital,
        planned_risk=planned_risk,
        planned_risk_pct=planned_risk_pct,
    )
