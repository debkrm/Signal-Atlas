"""
trend_pullback.py - Pure Trend-Pullback Swing Strategy for NSE Cash Equities.

Strategy Logic:
1. Market Regime Gate: Nifty 50 macro trend must permit new long positions.
2. Verified Uptrend: Daily Close > EMA 50, EMA 20 > EMA 50, and Weekly Close > 10-week EMA.
3. Constructive Pullback: Price pulls back to within 4% of the 20-day EMA without closing below EMA 50.
4. Momentum Reset: 14-period RSI is reset in the 40-60 zone (constructive consolidation, not overbought).
5. Asymmetric Reward-to-Risk: Stop loss placed at 1.5x ATR below close, target at 3.0x ATR above close (minimum 1.5 R:R).
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple

from signal_atlas.features.models import TechnicalFeatures
from signal_atlas.strategy.base import Strategy
from signal_atlas.strategy.models import (
    MarketContext,
    SignalState,
    StrategyCandidate,
    TrendPullbackParameters,
)
from signal_atlas.universe.models import UniverseMember

TICK_SIZE = Decimal("0.05")


def round_to_tick(price: Decimal, tick_size: Decimal = TICK_SIZE) -> Decimal:
    """Rounds a price to the exchange minimum price tick (e.g. ₹0.05 on NSE)."""
    ticks = (price / tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return ticks * tick_size


class TrendPullbackStrategy(Strategy):
    """
    Pure deterministic Trend-Pullback Swing Strategy.
    """

    def __init__(self, parameters: Optional[TrendPullbackParameters] = None):
        self.params = parameters or TrendPullbackParameters()

    @property
    def strategy_id(self) -> str:
        return self.params.strategy_id

    @property
    def strategy_version(self) -> str:
        return self.params.strategy_version

    def evaluate_candidate(
        self,
        features: TechnicalFeatures,
        market_context: MarketContext,
        universe_member: Optional[UniverseMember] = None,
    ) -> StrategyCandidate:
        """
        Pure function evaluating technical features for day t.
        Returns a StrategyCandidate with state BUY or AVOID.
        """
        sym = features.symbol
        inst_id = features.instrument_id
        dt = features.as_of_date
        c = features.close

        # 0. Derive baseline technical geometry levels based on ATR
        atr = features.atr_14
        entry_ref = c
        entry_low = round_to_tick(c * Decimal("0.995"))
        entry_high = round_to_tick(c * Decimal("1.005"))

        if atr is not None and atr > Decimal("0") and c > Decimal("0"):
            stop_price = round_to_tick(c - (atr * self.params.stop_atr_multiplier))
            target_price = round_to_tick(c + (atr * self.params.target_atr_multiplier))
            risk_per_share = entry_ref - stop_price
            reward_per_share = target_price - entry_ref
            reward_to_risk = (
                (reward_per_share / risk_per_share).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if risk_per_share > Decimal("0")
                else Decimal("0.00")
            )
        else:
            stop_price = c
            target_price = c
            risk_per_share = Decimal("0.00")
            reward_per_share = Decimal("0.00")
            reward_to_risk = Decimal("0.00")

        dist_to_ema20 = (
            (c - features.ema_20) / features.ema_20
            if (features.ema_20 is not None and features.ema_20 > Decimal("0"))
            else None
        )

        # Build comprehensive condition evaluations checklist
        cond_data_ok = bool(
            features.sufficient_history
            and features.ema_20 is not None
            and features.ema_50 is not None
            and features.rsi_14 is not None
            and features.atr_14 is not None
        )
        cond_uptrend_ok = bool(c > features.ema_50) if features.ema_50 else False
        cond_ema_align_ok = bool(features.ema_20 > features.ema_50) if (features.ema_20 and features.ema_50) else False
        cond_weekly_ok = bool(features.weekly_trend_bullish is True)
        cond_proximity_ok = bool(
            dist_to_ema20 is not None
            and dist_to_ema20 <= self.params.max_ema20_distance_pct
            and c >= (features.ema_50 or Decimal("0"))
        )
        cond_rsi_ok = bool(
            features.rsi_14 is not None
            and self.params.min_rsi <= features.rsi_14 <= self.params.max_rsi
        )
        cond_geometry_ok = bool(
            stop_price < entry_ref
            and risk_per_share > Decimal("0")
            and reward_to_risk >= self.params.min_reward_to_risk
        )
        cond_regime_ok = bool(market_context.is_market_regime_bullish)

        condition_evaluations = [
            {
                "name": "Data Sufficiency",
                "criteria": ">= 50 sessions & indicators computed",
                "actual": f"{features.history_sessions_count} sessions" if features.sufficient_history else f"{features.history_sessions_count} sessions (< 50)",
                "passed": cond_data_ok,
                "detail": "Indicators computed" if cond_data_ok else "Insufficient history or missing indicators",
            },
            {
                "name": "Daily Uptrend (Close > EMA 50)",
                "criteria": "Close > EMA 50",
                "actual": f"Close Rs. {c:,.2f} | EMA50 Rs. {features.ema_50:,.2f}" if features.ema_50 else "EMA 50 missing",
                "passed": cond_uptrend_ok,
                "detail": "Above 50-day EMA" if cond_uptrend_ok else "Below 50-day EMA",
            },
            {
                "name": "EMA Alignment (EMA 20 > EMA 50)",
                "criteria": "EMA 20 > EMA 50",
                "actual": f"EMA20 Rs. {features.ema_20:,.2f} | EMA50 Rs. {features.ema_50:,.2f}" if (features.ema_20 and features.ema_50) else "EMAs missing",
                "passed": cond_ema_align_ok,
                "detail": "Bullish alignment" if cond_ema_align_ok else "Inverted/Bearish alignment",
            },
            {
                "name": "Weekly Trend Confirmation",
                "criteria": "Weekly trend bullish (Close > 10-week EMA)",
                "actual": f"Weekly Bullish: {features.weekly_trend_bullish}",
                "passed": cond_weekly_ok,
                "detail": "Weekly uptrend confirmed" if cond_weekly_ok else "Weekly trend is not bullish",
            },
            {
                "name": "Pullback Proximity (<= 4% to EMA 20)",
                "criteria": f"Within {self.params.max_ema20_distance_pct:.1%} of EMA 20 & >= EMA 50",
                "actual": f"Distance: {dist_to_ema20:.2%}" if dist_to_ema20 is not None else "N/A",
                "passed": cond_proximity_ok,
                "detail": (
                    "In pullback zone"
                    if cond_proximity_ok
                    else (
                        f"Extended (+{dist_to_ema20:.2%} > {self.params.max_ema20_distance_pct:.1%})"
                        if (dist_to_ema20 is not None and dist_to_ema20 > self.params.max_ema20_distance_pct)
                        else "Broke below EMA 50"
                    )
                ),
            },
            {
                "name": "RSI Momentum Reset Zone",
                "criteria": f"{self.params.min_rsi:.0f} <= RSI 14 <= {self.params.max_rsi:.0f}",
                "actual": f"RSI 14 = {features.rsi_14:.2f}" if features.rsi_14 is not None else "RSI missing",
                "passed": cond_rsi_ok,
                "detail": (
                    "In reset zone"
                    if cond_rsi_ok
                    else (
                        f"Oversold / Selling Pressure (RSI {features.rsi_14:.2f} < {self.params.min_rsi:.0f})"
                        if (features.rsi_14 is not None and features.rsi_14 < self.params.min_rsi)
                        else f"Overbought (RSI {features.rsi_14:.2f} > {self.params.max_rsi:.0f})"
                    )
                ),
            },
            {
                "name": "Risk-to-Reward Viability",
                "criteria": f"Stop < Entry, Risk > 0, R:R >= {self.params.min_reward_to_risk:.2f}",
                "actual": f"Stop Rs. {stop_price:,.2f} | Target Rs. {target_price:,.2f} | R:R {reward_to_risk:.2f}",
                "passed": cond_geometry_ok,
                "detail": "Geometry viable" if cond_geometry_ok else "Geometry non-viable",
            },
            {
                "name": "Market Regime Gate",
                "criteria": f"Benchmark ({market_context.benchmark_symbol}) > EMA 50",
                "actual": "BULLISH" if cond_regime_ok else "BEARISH_OR_NEUTRAL",
                "passed": cond_regime_ok,
                "detail": "Benchmark in uptrend" if cond_regime_ok else f"Benchmark {market_context.benchmark_symbol} in correction",
            },
        ]

        # Helper to construct rejection candidates while preserving technical reference geometry and full audit trail
        def _reject(reason: str, detail: str) -> StrategyCandidate:
            return StrategyCandidate(
                instrument_id=inst_id,
                symbol=sym,
                signal_date=dt,
                signal_state=SignalState.AVOID,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                is_valid=False,
                rejection_reason=reason,
                rejection_detail=detail,
                close_t=c,
                entry_reference=entry_ref,
                entry_zone_low=entry_low,
                entry_zone_high=entry_high,
                stop_loss=stop_price,
                target_price=target_price,
                risk_per_share=risk_per_share,
                reward_per_share=reward_per_share,
                reward_to_risk=reward_to_risk,
                atr_14=atr,
                rsi_14=features.rsi_14,
                features_summary={
                    "ema_20": str(features.ema_20) if features.ema_20 else None,
                    "ema_50": str(features.ema_50) if features.ema_50 else None,
                    "rsi_14": str(features.rsi_14) if features.rsi_14 else None,
                    "atr_14": str(features.atr_14) if features.atr_14 else None,
                    "weekly_bullish": features.weekly_trend_bullish,
                    "dist_to_ema20_pct": f"{dist_to_ema20:.2%}" if dist_to_ema20 is not None else None,
                    "condition_evaluations": condition_evaluations,
                },
            )

        # 1. Data Sufficiency Check
        if not features.sufficient_history:
            return _reject(
                "INSUFFICIENT_HISTORY",
                f"Instrument has {features.history_sessions_count} sessions; minimum 50 required",
            )
        if (
            features.ema_20 is None
            or features.ema_50 is None
            or features.rsi_14 is None
            or features.atr_14 is None
        ):
            return _reject(
                "MISSING_REQUIRED_INDICATORS",
                "One or more required indicators (EMA 20, EMA 50, RSI 14, ATR 14) are not computed",
            )

        # 2. Medium-Term Daily Uptrend Filter
        if self.params.require_price_above_ema50 and c <= features.ema_50:
            return _reject(
                "NOT_ABOVE_EMA50",
                f"Close (Rs. {c:,.2f}) is below 50-day EMA (Rs. {features.ema_50:,.2f})",
            )
        if self.params.require_ema_alignment and features.ema_20 <= features.ema_50:
            return _reject(
                "EMA_NOT_ALIGNED",
                f"20-day EMA (Rs. {features.ema_20:,.2f}) is below 50-day EMA (Rs. {features.ema_50:,.2f})",
            )

        # 3. Weekly Trend Confirmation
        if self.params.require_weekly_trend_bullish and features.weekly_trend_bullish is False:
            return _reject(
                "WEEKLY_TREND_BEARISH",
                "Weekly trend is not bullish relative to the 10-week weekly EMA",
            )

        # 4. Pullback Proximity to 20-Day EMA
        if dist_to_ema20 is not None and dist_to_ema20 > self.params.max_ema20_distance_pct:
            return _reject(
                "EXTENDED_ABOVE_EMA20",
                f"Price is {dist_to_ema20:.2%} above EMA 20; exceeds {self.params.max_ema20_distance_pct:.2%} threshold",
            )
        if c < features.ema_50:
            return _reject(
                "BROKEN_BELOW_EMA50",
                f"Pullback broke below 50-day EMA (Rs. {features.ema_50:,.2f})",
            )

        # 5. RSI Momentum Reset Zone
        if features.rsi_14 < self.params.min_rsi:
            return _reject(
                "MOMENTUM_BROKEN_RSI_TOO_LOW",
                f"RSI 14 ({features.rsi_14:.2f}) is below {self.params.min_rsi:.0f}; pullback indicates excessive selling pressure",
            )
        if features.rsi_14 > self.params.max_rsi:
            return _reject(
                "OVERBOUGHT_RSI_TOO_HIGH",
                f"RSI 14 ({features.rsi_14:.2f}) is above {self.params.max_rsi:.0f}; stock has not pulled back sufficiently",
            )

        # 6. Invalidation, Target, and Reward-to-Risk Architecture
        if stop_price >= entry_ref or stop_price <= Decimal("0"):
            return _reject(
                "INVALID_STOP_LEVEL",
                f"Calculated stop (Rs. {stop_price:,.2f}) is non-viable relative to entry (Rs. {entry_ref:,.2f})",
            )

        if risk_per_share <= Decimal("0"):
            return _reject("ZERO_OR_NEGATIVE_RISK", "Risk per share cannot be zero or negative")

        if reward_to_risk < self.params.min_reward_to_risk:
            return _reject(
                "INSUFFICIENT_REWARD_TO_RISK",
                f"Reward-to-risk {reward_to_risk:.2f} is below minimum required {self.params.min_reward_to_risk:.2f}",
            )

        # 7. Market Regime Check
        if not market_context.is_market_regime_bullish:
            return _reject(
                "MARKET_REGIME_BEARISH",
                f"Benchmark {market_context.benchmark_symbol} regime is unfavorable for new long setups",
            )

        # 8. All Criteria Passed -> Generate BUY Candidate
        return StrategyCandidate(
            instrument_id=inst_id,
            symbol=sym,
            signal_date=dt,
            signal_state=SignalState.BUY,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            is_valid=True,
            rejection_reason=None,
            rejection_detail=None,
            close_t=c,
            entry_reference=entry_ref,
            entry_zone_low=entry_low,
            entry_zone_high=entry_high,
            stop_loss=stop_price,
            target_price=target_price,
            risk_per_share=risk_per_share,
            reward_per_share=reward_per_share,
            reward_to_risk=reward_to_risk,
            atr_14=atr,
            rsi_14=features.rsi_14,
            features_summary={
                "ema_20": str(features.ema_20),
                "ema_50": str(features.ema_50),
                "rsi_14": str(features.rsi_14),
                "atr_14": str(features.atr_14),
                "weekly_bullish": features.weekly_trend_bullish,
                "dist_to_ema20_pct": f"{dist_to_ema20:.2%}" if dist_to_ema20 is not None else None,
                "condition_evaluations": condition_evaluations,
            },
        )

    def evaluate_next_session_entry(
        self,
        candidate: StrategyCandidate,
        next_open: Decimal,
        next_high: Decimal,
        next_low: Decimal,
    ) -> Tuple[bool, Optional[Decimal], Optional[str]]:
        """
        Section 8.3: Signal Timing & Next-Session (t+1) Execution Gate.
        - Verifies whether a day-t signal can be safely entered at day t+1 open.
        - Recalculates effective reward-to-risk at actual opening fill price.
        - Skips trade if the opening gap makes the setup invalid.
        Returns (is_fill_valid, actual_entry_price, skip_reason).
        """
        if candidate.signal_state != SignalState.BUY or not candidate.is_valid:
            return False, None, "NOT_A_BUY_SIGNAL"

        ref = candidate.entry_reference

        # If next open gaps below stop loss, setup was invalidated before entry
        if next_open <= candidate.stop_loss:
            return False, None, f"GAPPED_BELOW_STOP: Open {next_open} <= Stop {candidate.stop_loss}"

        # If next open gaps beyond target, profit potential already captured
        if next_open >= candidate.target_price:
            return False, None, f"GAPPED_TO_TARGET: Open {next_open} >= Target {candidate.target_price}"

        # Check opening gap magnitude
        gap_pct = abs(next_open - ref) / ref
        if gap_pct > self.params.max_entry_gap_pct:
            return False, None, f"OPENING_GAP_TOO_LARGE: {gap_pct:.2%} exceeds {self.params.max_entry_gap_pct:.2%}"

        # Recalculate reward-to-risk at actual opening price
        effective_risk = next_open - candidate.stop_loss
        effective_reward = candidate.target_price - next_open

        if effective_risk <= Decimal("0"):
            return False, None, "INVALID_RISK_AT_OPEN"

        effective_rr = (effective_reward / effective_risk).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if effective_rr < self.params.min_reward_to_risk:
            return False, None, f"REDUCED_REWARD_TO_RISK_AT_OPEN: {effective_rr} < {self.params.min_reward_to_risk}"

        return True, next_open, None
