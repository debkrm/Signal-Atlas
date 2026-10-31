"""
test_risk_engine.py - Comprehensive Unit Tests for Signal Atlas Risk Engine.

Fulfills Phase 3 Acceptance Criteria:
- At least ten hand-calculated cases matching the engine.
- Includes gap deviation, invalid stop, insufficient capital, insufficient liquidity,
  unknown mandatory data, market regime rejection, concentration limits,
  surveillance veto, earnings blackout, and drawdown kill-switch.
"""

import datetime
from decimal import Decimal
import pytest

from signal_atlas.risk.engine import RiskEngine
from signal_atlas.risk.models import (
    OpenPositionRisk,
    PortfolioState,
    RiskConfig,
    SurveillanceStatus,
)
from signal_atlas.risk.sizing import calculate_position_sizing
from signal_atlas.strategy.models import MarketContext, SignalState, StrategyCandidate


def _make_candidate(
    inst_id: str = "INST_TCS",
    symbol: str = "TCS",
    signal_date: datetime.date = datetime.date(2024, 1, 1),
    state: SignalState = SignalState.BUY,
    is_valid: bool = True,
    entry_ref: Decimal = Decimal("200.00"),
    stop_loss: Decimal = Decimal("190.00"),
    target_price: Decimal = Decimal("225.00"),
) -> StrategyCandidate:
    risk = entry_ref - stop_loss
    reward = target_price - entry_ref
    rr = (reward / risk).quantize(Decimal("0.01")) if risk > Decimal("0") else Decimal("0.00")
    return StrategyCandidate(
        instrument_id=inst_id,
        symbol=symbol,
        signal_date=signal_date,
        signal_state=state,
        strategy_id="trend_pullback",
        strategy_version="v1.0",
        is_valid=is_valid,
        close_t=entry_ref,
        entry_reference=entry_ref,
        entry_zone_low=entry_ref * Decimal("0.99"),
        entry_zone_high=entry_ref * Decimal("1.01"),
        stop_loss=stop_loss,
        target_price=target_price,
        risk_per_share=risk,
        reward_per_share=reward,
        reward_to_risk=rr,
    )


def _make_market_context(bullish: bool = True) -> MarketContext:
    return MarketContext(
        as_of_date=datetime.date(2024, 1, 1),
        benchmark_symbol="NIFTY50",
        benchmark_close=Decimal("21500.00"),
        is_market_regime_bullish=bullish,
    )


def _make_portfolio(
    total_equity: Decimal = Decimal("1000000.00"),
    available_cash: Decimal = Decimal("1000000.00"),
    peak_equity: Decimal = Decimal("1000000.00"),
    open_positions=None,
) -> PortfolioState:
    return PortfolioState(
        as_of_date=datetime.date(2024, 1, 1),
        total_equity=total_equity,
        available_cash=available_cash,
        peak_equity=peak_equity,
        open_positions=open_positions or [],
    )


class TestPositionSizingMath:
    def test_hand_calculated_sizing_risk_budget_binding(self):
        """
        Equity: 10,00,000. Cash: 10,00,000.
        Entry: 200, Stop: 190. Risk/sh: 10.
        Risk Budget: 1% of 10L = 10,000.
        Q_risk = floor(10000 / 10) = 1,000.
        Cap Budget: 20% of 10L = 2,00,000.
        Q_cap = floor(200000 / 200) = 1,000.
        ADTV: 10 Cr. 2% = 20 Lakhs.
        Q_liq = floor(2000000 / 200) = 10,000.
        Q = 1000. Limiting: RISK_BUDGET.
        """
        res = calculate_position_sizing(
            entry_price=Decimal("200.00"),
            stop_loss=Decimal("190.00"),
            total_equity=Decimal("1000000.00"),
            available_cash=Decimal("1000000.00"),
            risk_per_trade_pct=Decimal("0.01"),
            max_capital_per_position_pct=Decimal("0.20"),
            adtv=Decimal("100000000.00"),
            max_adtv_participation_pct=Decimal("0.02"),
        )
        assert res.quantity == 1000
        assert res.planned_capital == Decimal("200000.00")
        assert res.planned_risk == Decimal("10000.00")
        assert res.planned_risk_pct == Decimal("0.0100")
        assert res.limiting_factor == "RISK_BUDGET"

    def test_hand_calculated_sizing_capital_cap_binding(self):
        """
        When stop is very tight (Risk/sh: 2), Q_risk would be 5,000 (10 Lakhs capital).
        Capital cap of 20% (2 Lakhs) limits quantity to 1,000.
        """
        res = calculate_position_sizing(
            entry_price=Decimal("200.00"),
            stop_loss=Decimal("198.00"),  # Risk = 2.00
            total_equity=Decimal("1000000.00"),
            available_cash=Decimal("1000000.00"),
            risk_per_trade_pct=Decimal("0.01"),
            max_capital_per_position_pct=Decimal("0.20"),  # 2,00,000 max
            adtv=Decimal("100000000.00"),
            max_adtv_participation_pct=Decimal("0.02"),
        )
        assert res.q_risk == 5000
        assert res.q_capital == 1000
        assert res.quantity == 1000
        assert res.limiting_factor == "CAPITAL_CAP"

    def test_hand_calculated_sizing_liquidity_cap_binding(self):
        """
        When stock is less liquid (ADTV = 50 Lakhs), 2% participation is 1 Lakh.
        Q_liq = floor(1,00,000 / 200) = 500.
        """
        res = calculate_position_sizing(
            entry_price=Decimal("200.00"),
            stop_loss=Decimal("190.00"),
            total_equity=Decimal("1000000.00"),
            available_cash=Decimal("1000000.00"),
            adtv=Decimal("5000000.00"),  # 50 Lakhs
            max_adtv_participation_pct=Decimal("0.02"),
        )
        assert res.q_liquidity == 500
        assert res.quantity == 500
        assert res.limiting_factor == "LIQUIDITY_CAP"


class TestRiskEngineCases:
    def test_case_1_clean_valid_setup(self):
        """Case 1: All rules pass, returns approved BUY setup with exact hand-calculated sizing."""
        engine = RiskEngine()
        cand = _make_candidate()
        port = _make_portfolio()
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),  # 10 Cr ADTV
            sector="IT",
            isin="INE999TCS01",
        )
        assert setup.is_approved is True
        assert setup.signal_state == SignalState.BUY
        assert setup.allocated_quantity == 1000
        assert setup.planned_capital_usage == Decimal("200000.00")
        assert setup.planned_risk_amount == Decimal("10000.00")
        assert setup.primary_rejection_reason is None

    def test_case_2_opening_gap_exceeds_tolerance(self):
        """Case 2: Next day opens at 206 (3% gap up > 2% max deviation). Vetoed."""
        engine = RiskEngine()
        cand = _make_candidate(entry_ref=Decimal("200.00"))
        port = _make_portfolio()
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),
            next_open=Decimal("206.00"),  # 3% gap
        )
        assert setup.is_approved is False
        assert setup.signal_state == SignalState.AVOID
        assert setup.allocated_quantity == 0
        assert any(f.check_id == "OPENING_GAP_EXCEEDS_TOLERANCE" for f in setup.failed_checks)

    def test_case_3_opening_gapped_below_stop(self):
        """Case 3: Next day opens at 188 (below stop 190). Vetoed."""
        engine = RiskEngine()
        cand = _make_candidate(entry_ref=Decimal("200.00"), stop_loss=Decimal("190.00"))
        port = _make_portfolio()
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),
            next_open=Decimal("188.00"),
        )
        assert setup.is_approved is False
        assert any(f.check_id == "GAPPED_BELOW_STOP" for f in setup.failed_checks)

    def test_case_4_invalid_inverted_stop_loss(self):
        """Case 4: Stop loss (205) is greater than entry (200). Vetoed."""
        engine = RiskEngine()
        cand = _make_candidate(entry_ref=Decimal("200.00"), stop_loss=Decimal("205.00"))
        port = _make_portfolio()
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),
        )
        assert setup.is_approved is False
        assert any(f.check_id == "INVALID_STOP_LOSS" for f in setup.failed_checks)

    def test_case_5_insufficient_available_cash(self):
        """Case 5: Portfolio has only ₹100 cash. Cannot buy 1 share of ₹200. Vetoed."""
        engine = RiskEngine()
        cand = _make_candidate(entry_ref=Decimal("200.00"))
        port = _make_portfolio(available_cash=Decimal("100.00"))
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),
        )
        assert setup.is_approved is False
        assert setup.allocated_quantity == 0
        assert any(f.check_id == "ZERO_ALLOCATED_QUANTITY" for f in setup.failed_checks)

    def test_case_6_insufficient_liquidity_adtv(self):
        """Case 6: ADTV is ₹2 Cr (below configured ₹5 Cr minimum). Vetoed."""
        engine = RiskEngine(RiskConfig(min_adtv=Decimal("50000000.00")))
        cand = _make_candidate()
        port = _make_portfolio()
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("20000000.00"),  # ₹2 Cr < ₹5 Cr
        )
        assert setup.is_approved is False
        assert any(f.check_id == "INSUFFICIENT_LIQUIDITY" for f in setup.failed_checks)

    def test_case_7_unknown_mandatory_data_blocks_setup(self):
        """Case 7: ADTV is None. Mandatory data missing policy blocks setup."""
        engine = RiskEngine()
        cand = _make_candidate()
        port = _make_portfolio()
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=None,  # Missing mandatory ADTV
        )
        assert setup.is_approved is False
        assert any(f.check_id == "MANDATORY_LIQUIDITY_DATA_MISSING" for f in setup.failed_checks)

    def test_case_8_unknown_non_mandatory_data_adds_warning(self):
        """Case 8: Surveillance is UNKNOWN and earnings is None. Setup passes with visible warnings."""
        engine = RiskEngine()
        cand = _make_candidate()
        port = _make_portfolio()
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),
            surveillance_status=SurveillanceStatus.UNKNOWN,
            days_to_earnings=None,
        )
        assert setup.is_approved is True
        assert len(setup.warnings) >= 2
        assert any("Surveillance data is UNKNOWN" in w for w in setup.warnings)
        assert any("Corporate earnings calendar is unavailable" in w for w in setup.warnings)

    def test_case_9_market_regime_rejection(self):
        """Case 9: Benchmark regime is bearish. Vetoed."""
        engine = RiskEngine()
        cand = _make_candidate()
        port = _make_portfolio()
        mkt = _make_market_context(bullish=False)

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),
        )
        assert setup.is_approved is False
        assert any(f.check_id == "MARKET_REGIME_UNFAVORABLE" for f in setup.failed_checks)

    def test_case_10_max_concurrent_positions_reached(self):
        """Case 10: Portfolio already holds 10 positions. Capacity reached. Vetoed."""
        engine = RiskEngine(RiskConfig(max_concurrent_positions=3))
        cand = _make_candidate(inst_id="NEW_STOCK", symbol="NEW")
        positions = [
            OpenPositionRisk(
                instrument_id=f"POS_{i}",
                symbol=f"STOCK_{i}",
                entry_price=Decimal("100"),
                current_price=Decimal("105"),
                stop_loss=Decimal("95"),
                quantity=100,
                capital_allocated=Decimal("10000"),
                open_risk_amount=Decimal("500"),
            )
            for i in range(3)
        ]
        port = _make_portfolio(open_positions=positions)
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),
        )
        assert setup.is_approved is False
        assert any(f.check_id == "MAX_CONCURRENT_POSITIONS_REACHED" for f in setup.failed_checks)

    def test_case_11_max_total_open_risk_exceeded(self):
        """
        Case 11: Portfolio equity 10L. Max open risk = 6% (₹60,000).
        Existing positions have ₹55,000 open risk.
        New trade risk is ₹10,000 (total ₹65,000 > ₹60,000). Vetoed.
        """
        engine = RiskEngine(RiskConfig(max_total_open_risk_pct=Decimal("0.06")))
        cand = _make_candidate()
        pos = OpenPositionRisk(
            instrument_id="EXISTING",
            symbol="OLD",
            entry_price=Decimal("100"),
            current_price=Decimal("105"),
            stop_loss=Decimal("90"),
            quantity=5500,
            capital_allocated=Decimal("550000"),
            open_risk_amount=Decimal("55000.00"),  # 5.5% open risk
        )
        port = _make_portfolio(open_positions=[pos])
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),
        )
        assert setup.is_approved is False
        assert any(f.check_id == "MAX_TOTAL_OPEN_RISK_EXCEEDED" for f in setup.failed_checks)

    def test_case_12_sector_concentration_limit_exceeded(self):
        """Case 12: IT sector already has ₹3,00,000 allocated (30% ceiling). Vetoed."""
        engine = RiskEngine(RiskConfig(max_sector_exposure_pct=Decimal("0.30")))
        cand = _make_candidate()
        pos = OpenPositionRisk(
            instrument_id="INFY",
            symbol="INFY",
            sector="IT",
            entry_price=Decimal("1500"),
            current_price=Decimal("1550"),
            stop_loss=Decimal("1450"),
            quantity=200,
            capital_allocated=Decimal("300000.00"),  # ₹3L = 30% of 10L
            open_risk_amount=Decimal("10000.00"),
        )
        port = _make_portfolio(open_positions=[pos])
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),
            sector="IT",
        )
        assert setup.is_approved is False
        assert any(f.check_id == "SECTOR_CONCENTRATION_EXCEEDED" for f in setup.failed_checks)

    def test_case_13_surveillance_asm_stage_veto(self):
        """Case 13: Stock is under ASM Stage 1. Hard regulatory veto."""
        engine = RiskEngine()
        cand = _make_candidate()
        port = _make_portfolio()
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),
            surveillance_status=SurveillanceStatus.ASM_STAGE_1,
        )
        assert setup.is_approved is False
        assert any(f.check_id == "SURVEILLANCE_RESTRICTION_VETO" for f in setup.failed_checks)

    def test_case_14_corporate_earnings_blackout_window(self):
        """Case 14: Earnings scheduled in 2 days (within 5-day blackout). Vetoed."""
        engine = RiskEngine(RiskConfig(block_on_upcoming_earnings_days=5))
        cand = _make_candidate()
        port = _make_portfolio()
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),
            days_to_earnings=2,
        )
        assert setup.is_approved is False
        assert any(f.check_id == "UPCOMING_EARNINGS_ANNOUNCEMENT" for f in setup.failed_checks)

    def test_case_15_drawdown_killswitch_active(self):
        """Case 15: Portfolio peak 10L, current equity 8.8L (12% drawdown >= 10% limit). Vetoed."""
        engine = RiskEngine(RiskConfig(drawdown_killswitch_pct=Decimal("10.00")))
        cand = _make_candidate()
        port = _make_portfolio(
            total_equity=Decimal("880000.00"),
            available_cash=Decimal("880000.00"),
            peak_equity=Decimal("1000000.00"),
        )
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),
        )
        assert setup.is_approved is False
        assert any(f.check_id == "DRAWDOWN_KILLSWITCH_ACTIVE" for f in setup.failed_checks)

    def test_case_16_duplicate_holding_veto(self):
        """Case 16: Instrument is already open in portfolio. Duplicate entry vetoed."""
        engine = RiskEngine()
        cand = _make_candidate(inst_id="TCS_ID")
        pos = OpenPositionRisk(
            instrument_id="TCS_ID",
            symbol="TCS",
            entry_price=Decimal("200"),
            current_price=Decimal("202"),
            stop_loss=Decimal("190"),
            quantity=500,
            capital_allocated=Decimal("100000"),
            open_risk_amount=Decimal("5000"),
        )
        port = _make_portfolio(open_positions=[pos])
        mkt = _make_market_context()

        setup = engine.evaluate_trade_setup(
            candidate=cand,
            portfolio=port,
            market_context=mkt,
            adtv=Decimal("100000000.00"),
        )
        assert setup.is_approved is False
        assert any(f.check_id == "ALREADY_HOLDING_POSITION" for f in setup.failed_checks)
