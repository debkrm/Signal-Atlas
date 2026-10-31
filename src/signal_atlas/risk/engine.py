"""
engine.py - Configuration-Driven Risk Engine for Signal Atlas.

Implements the mandatory risk gate between Strategy output and published TradeSetup:
- Capital and available cash checks.
- Risk budget per trade (default 1.0%).
- Maximum concurrent positions (default 10).
- Maximum total open risk across portfolio (default 6.0%).
- Sector concentration limits (default 30.0%).
- Minimum reward-to-risk ratio (default 1.50).
- Minimum 20-day average daily turnover (ADTV) threshold (default ₹5 Cr).
- Maximum ADTV participation cap (default 2.0%).
- Opening gap / entry deviation limit (default 2.0%).
- Market regime gate (benchmark trend confirmation).
- Hard regulatory & surveillance exclusions (ASM/GSM/Price-band restrictions).
- Corporate earnings calendar veto.
- Portfolio drawdown kill-switch.
- Strict unknown vs known data policy: unknown mandatory data blocks setup;
  unknown non-mandatory data appends a visible warning.
"""

import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
import uuid

from signal_atlas.risk.models import (
    CheckSeverity,
    OpenPositionRisk,
    PortfolioState,
    RiskCheckResult,
    RiskConfig,
    SurveillanceStatus,
    TradeSetup,
)
from signal_atlas.risk.sizing import calculate_position_sizing
from signal_atlas.strategy.models import MarketContext, SignalState, StrategyCandidate


class RiskEngine:
    """
    Deterministic, configuration-driven Risk Engine enforcing trade and portfolio rules.
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()

    def evaluate_trade_setup(
        self,
        candidate: StrategyCandidate,
        portfolio: PortfolioState,
        market_context: MarketContext,
        adtv: Optional[Decimal] = None,
        sector: Optional[str] = None,
        isin: Optional[str] = None,
        series: str = "EQ",
        surveillance_status: SurveillanceStatus = SurveillanceStatus.CLEAR,
        next_open: Optional[Decimal] = None,
        days_to_earnings: Optional[int] = None,
        pledge_pct: Optional[Decimal] = None,
        setup_id: Optional[str] = None,
        ignore_regime: bool = False,
    ) -> TradeSetup:
        """
        Pure deterministic evaluation of a StrategyCandidate against RiskConfig and PortfolioState.
        Returns a complete, structured TradeSetup with full audit trail of passed/failed checks.
        """
        passed_checks: List[str] = []
        failed_checks: List[RiskCheckResult] = []
        warnings: List[str] = []

        eff_setup_id = setup_id or f"SETUP-{uuid.uuid4().hex[:8]}"
        as_of_date = candidate.signal_date

        # Helper to record results
        def _pass(check_id: str, name: str, msg: str = "Passed") -> None:
            passed_checks.append(check_id)

        def _fail(
            check_id: str,
            name: str,
            msg: str,
            severity: CheckSeverity = CheckSeverity.BLOCKING,
            details: Optional[Dict[str, Any]] = None,
        ) -> None:
            failed_checks.append(
                RiskCheckResult(
                    check_id=check_id,
                    name=name,
                    passed=False,
                    severity=severity,
                    message=msg,
                    details=details or {},
                )
            )

        # -------------------------------------------------------------
        # 1. Strategy Signal Validity
        # -------------------------------------------------------------
        # If the candidate was rejected solely due to macro regime, the technical setup is valid.
        # The macro filter is owned exclusively by Gate 3 (Market Regime Gate).
        if candidate.rejection_reason == "MARKET_REGIME_BEARISH":
            _pass("STRATEGY_SIGNAL_VALID", "Strategy Signal Validity")
        elif candidate.signal_state != SignalState.BUY or not candidate.is_valid:
            _fail(
                "STRATEGY_SIGNAL_INVALID",
                "Strategy Signal Validity",
                candidate.rejection_detail or candidate.rejection_reason or "Strategy produced AVOID signal",
            )
        else:
            _pass("STRATEGY_SIGNAL_VALID", "Strategy Signal Validity")

        # -------------------------------------------------------------
        # 2. Reference Price Geometry & Stop Invariants
        # -------------------------------------------------------------
        entry_ref = candidate.entry_reference
        stop_ref = candidate.stop_loss
        target_ref = candidate.target_price

        if stop_ref >= entry_ref or stop_ref <= Decimal("0"):
            _fail(
                "INVALID_STOP_LOSS",
                "Stop Loss Geometry",
                f"Stop loss ({stop_ref}) must be positive and strictly below entry reference ({entry_ref})",
            )
        else:
            _pass("VALID_STOP_LOSS", "Stop Loss Geometry")

        if target_ref <= entry_ref:
            _fail(
                "INVALID_PROFIT_TARGET",
                "Profit Target Geometry",
                f"Profit target ({target_ref}) must be strictly above entry reference ({entry_ref})",
            )
        else:
            _pass("VALID_PROFIT_TARGET", "Profit Target Geometry")

        # -------------------------------------------------------------
        # 3. Market Regime Gate (Single Owner of Macro Filter)
        # -------------------------------------------------------------
        if ignore_regime or not self.config.require_bullish_market_regime:
            _pass("MARKET_REGIME_BYPASSED", "Market Regime Gate")
            if not market_context.is_market_regime_bullish:
                warnings.append(
                    f"Market regime check bypassed via diagnostic flag (--ignore-regime); benchmark ({market_context.benchmark_symbol}) was unfavorable"
                )
        elif not market_context.is_market_regime_bullish:
            _fail(
                "MARKET_REGIME_UNFAVORABLE",
                "Market Regime Gate",
                f"Benchmark ({market_context.benchmark_symbol}) regime is unfavorable for new long setups",
            )
        else:
            _pass("MARKET_REGIME_BULLISH", "Market Regime Gate")

        # -------------------------------------------------------------
        # 4. Portfolio Drawdown Kill-Switch
        # -------------------------------------------------------------
        if self.config.drawdown_killswitch_pct is not None:
            if portfolio.current_drawdown_pct >= self.config.drawdown_killswitch_pct:
                _fail(
                    "DRAWDOWN_KILLSWITCH_ACTIVE",
                    "Drawdown Kill-Switch",
                    f"Current portfolio drawdown ({portfolio.current_drawdown_pct}%) exceeds kill-switch threshold ({self.config.drawdown_killswitch_pct}%)",
                )
            else:
                _pass("DRAWDOWN_KILLSWITCH_INACTIVE", "Drawdown Kill-Switch")

        # -------------------------------------------------------------
        # 5. Concurrent Positions & Duplicate Holding Limit
        # -------------------------------------------------------------
        already_held = any(p.instrument_id == candidate.instrument_id for p in portfolio.open_positions)
        if already_held:
            _fail(
                "ALREADY_HOLDING_POSITION",
                "Position Duplication",
                f"Instrument {candidate.symbol} ({candidate.instrument_id}) is already held in portfolio",
            )
        else:
            _pass("NOT_ALREADY_HELD", "Position Duplication")

        if portfolio.concurrent_positions_count >= self.config.max_concurrent_positions:
            _fail(
                "MAX_CONCURRENT_POSITIONS_REACHED",
                "Portfolio Capacity",
                f"Portfolio holds {portfolio.concurrent_positions_count} open positions; max allowed is {self.config.max_concurrent_positions}",
            )
        else:
            _pass("CONCURRENT_POSITIONS_AVAILABLE", "Portfolio Capacity")

        # -------------------------------------------------------------
        # 6. Aggregate Portfolio Open Risk Limit
        # -------------------------------------------------------------
        trade_risk_budget = portfolio.total_equity * self.config.risk_per_trade_pct
        prospective_open_risk = portfolio.total_open_risk_amount + trade_risk_budget
        max_allowed_risk = portfolio.total_equity * self.config.max_total_open_risk_pct

        if prospective_open_risk > max_allowed_risk:
            _fail(
                "MAX_TOTAL_OPEN_RISK_EXCEEDED",
                "Portfolio Open Risk Limit",
                f"Prospective open risk (₹{prospective_open_risk}) exceeds portfolio open risk limit of {self.config.max_total_open_risk_pct:.1%} (₹{max_allowed_risk})",
            )
        else:
            _pass("OPEN_RISK_WITHIN_BUDGET", "Portfolio Open Risk Limit")

        # -------------------------------------------------------------
        # 7. Sector Concentration Limit
        # -------------------------------------------------------------
        if sector:
            curr_sector_capital = portfolio.get_sector_exposure(sector)
            max_sector_cap = portfolio.total_equity * self.config.max_sector_exposure_pct
            # Estimate single position capital cap
            prospective_sector_cap = curr_sector_capital + (portfolio.total_equity * self.config.max_capital_per_position_pct)
            if curr_sector_capital >= max_sector_cap:
                _fail(
                    "SECTOR_CONCENTRATION_EXCEEDED",
                    "Sector Exposure Limit",
                    f"Current exposure to {sector} (₹{curr_sector_capital}) already meets or exceeds sector ceiling of {self.config.max_sector_exposure_pct:.1%} (₹{max_sector_cap})",
                )
            else:
                _pass("SECTOR_EXPOSURE_COMPLIANT", "Sector Exposure Limit")
        else:
            warnings.append("Sector metadata is unavailable for concentration evaluation")

        # -------------------------------------------------------------
        # 8. Minimum Liquidity (20-day ADTV)
        # -------------------------------------------------------------
        if adtv is None:
            # Mandatory data missing policy: Blocks setup
            _fail(
                "MANDATORY_LIQUIDITY_DATA_MISSING",
                "Liquidity Threshold (ADTV)",
                "20-day Average Daily Turnover (ADTV) is missing and cannot be verified",
                severity=CheckSeverity.BLOCKING,
            )
        elif adtv < self.config.min_adtv:
            _fail(
                "INSUFFICIENT_LIQUIDITY",
                "Liquidity Threshold (ADTV)",
                f"20-day ADTV (₹{adtv:,.2f}) is below minimum threshold of ₹{self.config.min_adtv:,.2f}",
                severity=CheckSeverity.BLOCKING,
            )
        else:
            _pass("LIQUIDITY_SUFFICIENT", "Liquidity Threshold (ADTV)")

        # -------------------------------------------------------------
        # 9. Regulatory & Surveillance Restrictions (ASM/GSM/Circuit Filter)
        # -------------------------------------------------------------
        if self.config.veto_on_surveillance_flags:
            if surveillance_status in [
                SurveillanceStatus.ASM_STAGE_1,
                SurveillanceStatus.ASM_STAGE_2,
                SurveillanceStatus.ASM_STAGE_3,
                SurveillanceStatus.ASM_STAGE_4,
                SurveillanceStatus.GSM_STAGE_1,
                SurveillanceStatus.GSM_STAGE_2,
                SurveillanceStatus.CIRCUIT_FILTER_RESTRICTED,
            ]:
                _fail(
                    "SURVEILLANCE_RESTRICTION_VETO",
                    "Surveillance & Exchange Restrictions",
                    f"Security is under active exchange surveillance ({surveillance_status.value})",
                    severity=CheckSeverity.BLOCKING,
                )
            elif surveillance_status == SurveillanceStatus.UNKNOWN:
                warnings.append("Surveillance data is UNKNOWN; verify exchange circulars before execution")
                _pass("SURVEILLANCE_ADVISORY", "Surveillance & Exchange Restrictions")
            else:
                _pass("SURVEILLANCE_CLEAR", "Surveillance & Exchange Restrictions")

        # -------------------------------------------------------------
        # 10. Earnings Inside Intended Holding Window
        # -------------------------------------------------------------
        if self.config.block_on_upcoming_earnings_days is not None:
            if days_to_earnings is not None:
                if days_to_earnings <= self.config.block_on_upcoming_earnings_days:
                    _fail(
                        "UPCOMING_EARNINGS_ANNOUNCEMENT",
                        "Corporate Earnings Gate",
                        f"Company reports earnings in {days_to_earnings} sessions; inside blackout window of {self.config.block_on_upcoming_earnings_days} sessions",
                        severity=CheckSeverity.BLOCKING,
                    )
                else:
                    _pass("EARNINGS_CLEAR", "Corporate Earnings Gate")
            else:
                warnings.append("Corporate earnings calendar is unavailable; manual check of results date required before live execution (event risk unmodeled)")

        # -------------------------------------------------------------
        # 11. Promoter Pledge Advisory Check
        # -------------------------------------------------------------
        if pledge_pct is not None:
            if pledge_pct > Decimal("25.00"):
                warnings.append(f"Elevated promoter pledge: {pledge_pct:.1f}% of promoter holding is pledged")
        else:
            warnings.append("Promoter pledge data is UNKNOWN (not verified CLEAR)")

        # -------------------------------------------------------------
        # 12. Next-Session Fill & Gap Deviation Validation
        # -------------------------------------------------------------
        eff_entry = next_open if next_open is not None else entry_ref
        if next_open is not None:
            # Check gap boundaries
            if next_open <= stop_ref:
                _fail(
                    "GAPPED_BELOW_STOP",
                    "Opening Gap Boundary",
                    f"Opening price ({next_open}) gapped down beyond stop loss ({stop_ref})",
                )
            elif next_open >= target_ref:
                _fail(
                    "GAPPED_TO_TARGET",
                    "Opening Gap Boundary",
                    f"Opening price ({next_open}) gapped up beyond target ({target_ref})",
                )
            else:
                gap_pct = abs(next_open - entry_ref) / entry_ref
                if gap_pct > self.config.max_entry_deviation_pct:
                    _fail(
                        "OPENING_GAP_EXCEEDS_TOLERANCE",
                        "Opening Gap Tolerance",
                        f"Opening gap of {gap_pct:.2%} exceeds maximum allowed deviation of {self.config.max_entry_deviation_pct:.2%}",
                    )
                else:
                    _pass("OPENING_GAP_WITHIN_TOLERANCE", "Opening Gap Tolerance")

        # -------------------------------------------------------------
        # 13. Effective Reward-to-Risk Ratio
        # -------------------------------------------------------------
        eff_risk = eff_entry - stop_ref
        eff_reward = target_ref - eff_entry

        if eff_risk <= Decimal("0"):
            eff_rr = Decimal("0.00")
            _fail(
                "INVERTED_EFFECTIVE_RISK",
                "Reward-to-Risk Ratio",
                "Effective risk per share is zero or negative",
            )
        else:
            eff_rr = (eff_reward / eff_risk).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if eff_rr < self.config.min_reward_to_risk:
                _fail(
                    "INSUFFICIENT_REWARD_TO_RISK",
                    "Reward-to-Risk Ratio",
                    f"Effective reward-to-risk ratio ({eff_rr}) is below required minimum of {self.config.min_reward_to_risk}",
                )
            else:
                _pass("REWARD_TO_RISK_SATISFIED", "Reward-to-Risk Ratio")

        # -------------------------------------------------------------
        # 14. Deterministic Position Sizing
        # -------------------------------------------------------------
        blocking_failures = [f for f in failed_checks if f.severity == CheckSeverity.BLOCKING]

        if not blocking_failures and eff_risk > Decimal("0"):
            sizing = calculate_position_sizing(
                entry_price=eff_entry,
                stop_loss=stop_ref,
                total_equity=portfolio.total_equity,
                available_cash=portfolio.available_cash,
                risk_per_trade_pct=self.config.risk_per_trade_pct,
                max_capital_per_position_pct=self.config.max_capital_per_position_pct,
                adtv=adtv,
                max_adtv_participation_pct=self.config.max_adtv_participation_pct,
            )

            if sizing.quantity == 0:
                _fail(
                    "ZERO_ALLOCATED_QUANTITY",
                    "Position Sizing Capital Capacity",
                    "Calculated position size is 0 shares due to insufficient cash or risk budget",
                )
                allocated_qty = 0
                planned_capital = Decimal("0.00")
                planned_risk = Decimal("0.00")
                planned_risk_pct = Decimal("0.00")
                limiting_factor = "ZERO_QUANTITY"
            else:
                _pass("POSITION_SIZED_SUCCESSFULLY", "Position Sizing")
                allocated_qty = sizing.quantity
                planned_capital = sizing.planned_capital
                planned_risk = sizing.planned_risk
                planned_risk_pct = sizing.planned_risk_pct
                limiting_factor = sizing.limiting_factor

            sizing_breakdown = {
                "q_risk": sizing.q_risk,
                "q_capital": sizing.q_capital,
                "q_liquidity": sizing.q_liquidity,
                "limiting_factor": limiting_factor,
            }
        else:
            allocated_qty = 0
            planned_capital = Decimal("0.00")
            planned_risk = Decimal("0.00")
            planned_risk_pct = Decimal("0.00")
            limiting_factor = "REJECTED_ZERO"
            sizing_breakdown = {
                "q_risk": 0,
                "q_capital": 0,
                "q_liquidity": 0,
                "limiting_factor": "REJECTED_ZERO",
            }

        # Final Approval Disposition
        final_blocking = [f for f in failed_checks if f.severity == CheckSeverity.BLOCKING]
        is_approved = len(final_blocking) == 0 and allocated_qty > 0
        final_signal_state = SignalState.BUY if is_approved else SignalState.AVOID
        primary_reason = final_blocking[0].message if final_blocking else None

        return TradeSetup(
            setup_id=eff_setup_id,
            as_of_date=as_of_date,
            instrument_id=candidate.instrument_id,
            symbol=candidate.symbol,
            series=series,
            isin=isin,
            sector=sector,
            signal_state=final_signal_state,
            is_approved=is_approved,
            strategy_id=candidate.strategy_id,
            strategy_version=candidate.strategy_version,
            entry_price=eff_entry,
            entry_zone_low=candidate.entry_zone_low,
            entry_zone_high=candidate.entry_zone_high,
            stop_loss=stop_ref,
            target_price=target_ref,
            risk_per_share=eff_risk if eff_risk > Decimal("0") else Decimal("0.00"),
            reward_per_share=eff_reward if eff_reward > Decimal("0") else Decimal("0.00"),
            reward_to_risk=eff_rr,
            allocated_quantity=allocated_qty,
            planned_capital_usage=planned_capital,
            planned_risk_amount=planned_risk,
            planned_risk_pct=planned_risk_pct,
            limiting_factor=limiting_factor,
            sizing_breakdown=sizing_breakdown,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            condition_evaluations=candidate.features_summary.get("condition_evaluations", []),
            warnings=warnings,
            primary_rejection_reason=primary_reason,
            provenance={
                "candidate_date": str(candidate.signal_date),
                "evaluated_at": str(datetime.datetime.now(datetime.timezone.utc)),
                "portfolio_equity": str(portfolio.total_equity),
                "portfolio_cash": str(portfolio.available_cash),
            },
        )
