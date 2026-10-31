import datetime
from decimal import Decimal
from typing import Optional
import pytest

from signal_atlas.backtest.costs import TransactionCostModel
from signal_atlas.backtest.models import BacktestConfig, ExitReason
from signal_atlas.backtest.simulator import BacktestSimulator
from signal_atlas.features.models import TechnicalFeatures
from signal_atlas.quality.adjustment import AdjustedPriceRecord
from signal_atlas.strategy.base import Strategy
from signal_atlas.strategy.models import MarketContext, SignalState, StrategyCandidate


def _make_bar(
    trade_date: datetime.date,
    open_: str,
    high: str,
    low: str,
    close: str,
    volume: int = 100000,
    inst_id: str = "INST_1",
    symbol: str = "TCS",
) -> AdjustedPriceRecord:
    p_close = Decimal(close)
    return AdjustedPriceRecord(
        instrument_id=inst_id,
        symbol=symbol,
        trade_date=trade_date,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=p_close,
        prev_close=p_close,
        volume=volume,
        raw_volume=volume,
        traded_value=p_close * Decimal(volume),
        cumulative_multiplier=Decimal("1.0"),
        prev_close_multiplier=Decimal("1.0"),
        raw_prev_close=p_close,
    )


def _make_candidate(
    inst_id: str = "INST_1",
    symbol: str = "TCS",
    signal_date: datetime.date = datetime.date(2024, 1, 1),
    state: SignalState = SignalState.BUY,
    is_valid: bool = True,
    close_t: Decimal = Decimal("100.00"),
    entry_ref: Decimal = Decimal("100.00"),
    stop_loss: Decimal = Decimal("95.00"),
    target_price: Decimal = Decimal("110.00"),
    reason: Optional[str] = None,
) -> StrategyCandidate:
    risk = entry_ref - stop_loss
    reward = target_price - entry_ref
    rr = (reward / risk).quantize(Decimal("0.01")) if risk > Decimal("0") else Decimal("0.00")
    return StrategyCandidate(
        instrument_id=inst_id,
        symbol=symbol,
        signal_date=signal_date,
        signal_state=state,
        strategy_id="mock_strategy",
        strategy_version="v1.0",
        is_valid=is_valid,
        rejection_reason=reason if not is_valid else None,
        close_t=close_t,
        entry_reference=entry_ref,
        entry_zone_low=entry_ref * Decimal("0.99"),
        entry_zone_high=entry_ref * Decimal("1.01"),
        stop_loss=stop_loss,
        target_price=target_price,
        risk_per_share=risk,
        reward_per_share=reward,
        reward_to_risk=rr,
    )


class MockStrategy(Strategy):
    """Deterministic strategy for testing backtest simulator branches."""
    def __init__(self, candidates_by_date=None):
        self.candidates_by_date = candidates_by_date or {}

    @property
    def strategy_id(self) -> str:
        return "mock_strategy"

    @property
    def strategy_version(self) -> str:
        return "v1.0"

    def evaluate_candidate(
        self,
        features: TechnicalFeatures,
        market_context: MarketContext,
        universe_member=None,
    ) -> StrategyCandidate:
        c = self.candidates_by_date.get(features.as_of_date)
        if c:
            return c
        return _make_candidate(
            inst_id=features.instrument_id,
            symbol=features.symbol,
            signal_date=features.as_of_date,
            state=SignalState.AVOID,
            is_valid=False,
            reason="NO_MOCK_SIGNAL",
        )


class TestTransactionCostModel:
    def test_buy_cost_breakdown(self):
        model = TransactionCostModel(
            brokerage_per_order=Decimal("20.00"),
            brokerage_pct=Decimal("0.0003"),
            stt_rate=Decimal("0.0010"),
            exchange_rate=Decimal("0.00003"),
            sebi_rate=Decimal("0.000001"),
            stamp_duty_buy_rate=Decimal("0.00015"),
            gst_rate=Decimal("0.18"),
            slippage_bps=Decimal("0.0005"),
        )
        # Price 1000, quantity 100 -> gross = 100,000
        breakdown = model.calculate_buy_costs(price=Decimal("1000.00"), quantity=100)
        assert breakdown.gross_amount == Decimal("100000.00")
        assert breakdown.slippage == Decimal("50.00")  # 5 bps on 100,000 = 50.00
        # Exec gross = 100,050.00
        # Brokerage = min(20, 100050 * 0.0003 = 30.015) = 20.00
        assert breakdown.brokerage == Decimal("20.00")
        # STT = 100050 * 0.001 = 100.05
        assert breakdown.stt == Decimal("100.05")
        # Stamp duty = 100050 * 0.00015 = 15.01
        assert breakdown.stamp_duty == Decimal("15.01")
        # Total charges > 0
        assert breakdown.total_charges > Decimal("0.00")
        # Net cash flow is negative (cash outflow)
        assert breakdown.net_cash_flow < Decimal("-100000.00")

    def test_sell_cost_breakdown_no_stamp_duty(self):
        model = TransactionCostModel()
        breakdown = model.calculate_sell_costs(price=Decimal("1100.00"), quantity=100)
        # In India, stamp duty is payable on BUY only for delivery
        assert breakdown.stamp_duty == Decimal("0.00")
        assert breakdown.stt > Decimal("0.00")
        assert breakdown.brokerage > Decimal("0.00")
        # Net cash flow is positive (gross minus slippage and charges)
        assert breakdown.net_cash_flow > Decimal("100000.00")


class TestBacktestSimulator:
    def test_empty_dates_raises(self):
        sim = BacktestSimulator()
        strategy = MockStrategy()
        with pytest.raises(ValueError, match="trading_dates cannot be empty"):
            sim.run(strategy, [], {})

    def test_normal_win_profit_target_exit(self):
        """
        Day 1: Signal generated at close.
        Day 2: Order executed at Open (100.00). High reaches 110.00 (target).
        Exit on Day 2 with PROFIT_TARGET.
        """
        d1 = datetime.date(2024, 1, 1)
        d2 = datetime.date(2024, 1, 2)
        dates = [d1, d2]

        cand = _make_candidate(
            inst_id="INST_1",
            symbol="TCS",
            signal_date=d1,
            state=SignalState.BUY,
            is_valid=True,
            entry_ref=Decimal("100.00"),
            stop_loss=Decimal("95.00"),
            target_price=Decimal("110.00"),
        )
        strategy = MockStrategy({d1: cand})

        bars = [
            _make_bar(d1, "98.00", "101.00", "97.50", "100.00"),
            _make_bar(d2, "100.00", "111.00", "99.00", "108.00"),
        ]

        cfg = BacktestConfig(initial_capital=Decimal("100000.00"), min_history_sessions=1)
        sim = BacktestSimulator(cfg)
        res = sim.run(strategy, dates, {"INST_1": bars})

        assert len(res.trades) == 1
        trade = res.trades[0]
        assert trade.exit_reason == ExitReason.PROFIT_TARGET
        assert trade.exit_price == Decimal("110.00")
        assert trade.net_pnl > Decimal("0.00")
        assert res.metrics.winning_trades == 1
        assert res.metrics.losing_trades == 0
        assert res.metrics.win_rate_pct == Decimal("100.00")

    def test_normal_loss_stop_loss_exit(self):
        """
        Day 1: Signal BUY.
        Day 2: Fill at 100.00. Low touches 94.00 (below stop 95.00).
        Exit on Day 2 at stop price 95.00.
        """
        d1 = datetime.date(2024, 1, 1)
        d2 = datetime.date(2024, 1, 2)
        dates = [d1, d2]

        cand = _make_candidate(
            inst_id="INST_1",
            symbol="TCS",
            signal_date=d1,
            state=SignalState.BUY,
            is_valid=True,
            entry_ref=Decimal("100.00"),
            stop_loss=Decimal("95.00"),
            target_price=Decimal("110.00"),
        )
        strategy = MockStrategy({d1: cand})

        bars = [
            _make_bar(d1, "98.00", "101.00", "97.50", "100.00"),
            _make_bar(d2, "100.00", "101.00", "94.00", "94.50"),
        ]

        cfg = BacktestConfig(initial_capital=Decimal("100000.00"), min_history_sessions=1)
        sim = BacktestSimulator(cfg)
        res = sim.run(strategy, dates, {"INST_1": bars})

        assert len(res.trades) == 1
        trade = res.trades[0]
        assert trade.exit_reason == ExitReason.STOP_LOSS
        assert trade.exit_price == Decimal("95.00")
        assert trade.net_pnl < Decimal("0.00")
        assert res.metrics.losing_trades == 1

    def test_gap_down_below_stop_fills_at_open(self):
        """
        Crucial realism rule: If day 3 opens at 90.00 (below stop of 95.00),
        the fill must occur at 90.00, NOT 95.00.
        """
        d1 = datetime.date(2024, 1, 1)
        d2 = datetime.date(2024, 1, 2)
        d3 = datetime.date(2024, 1, 3)
        dates = [d1, d2, d3]

        cand = _make_candidate(
            inst_id="INST_1",
            symbol="TCS",
            signal_date=d1,
            state=SignalState.BUY,
            is_valid=True,
            entry_ref=Decimal("100.00"),
            stop_loss=Decimal("95.00"),
            target_price=Decimal("110.00"),
        )
        strategy = MockStrategy({d1: cand})

        bars = [
            _make_bar(d1, "98.00", "101.00", "97.50", "100.00"),
            _make_bar(d2, "100.00", "101.50", "98.00", "99.00"),  # Holding day
            _make_bar(d3, "90.00", "92.00", "89.00", "91.00"),    # Gap down at open to 90.00
        ]

        cfg = BacktestConfig(initial_capital=Decimal("100000.00"), min_history_sessions=1)
        sim = BacktestSimulator(cfg)
        res = sim.run(strategy, dates, {"INST_1": bars})

        assert len(res.trades) == 1
        trade = res.trades[0]
        assert trade.exit_reason == ExitReason.STOP_LOSS
        # Must be filled at open (90.00), not at the stop loss price (95.00)
        assert trade.exit_price == Decimal("90.00")
        assert trade.net_pnl < Decimal("0.00")

    def test_conservative_stop_first_dual_touch(self):
        """
        Ambiguity rule: When a daily bar touches both stop loss (low <= 95)
        and profit target (high >= 110), conservative execution must assume stop loss first.
        """
        d1 = datetime.date(2024, 1, 1)
        d2 = datetime.date(2024, 1, 2)
        d3 = datetime.date(2024, 1, 3)
        dates = [d1, d2, d3]

        cand = _make_candidate(
            inst_id="INST_1",
            symbol="TCS",
            signal_date=d1,
            state=SignalState.BUY,
            is_valid=True,
            entry_ref=Decimal("100.00"),
            stop_loss=Decimal("95.00"),
            target_price=Decimal("110.00"),
        )
        strategy = MockStrategy({d1: cand})

        bars = [
            _make_bar(d1, "98.00", "101.00", "97.50", "100.00"),
            _make_bar(d2, "100.00", "102.00", "99.00", "101.00"),
            # Day 3 has low 94.00 and high 112.00 (dual touch)
            _make_bar(d3, "101.00", "112.00", "94.00", "105.00"),
        ]

        cfg = BacktestConfig(initial_capital=Decimal("100000.00"), min_history_sessions=1)
        sim = BacktestSimulator(cfg)
        res = sim.run(strategy, dates, {"INST_1": bars})

        assert len(res.trades) == 1
        trade = res.trades[0]
        assert trade.exit_reason == ExitReason.STOP_LOSS
        assert trade.exit_price == Decimal("95.00")

    def test_max_holding_sessions_exit(self):
        """
        Positions exceeding max_holding_sessions must be liquidated at close.
        """
        dates = [datetime.date(2024, 1, i) for i in range(1, 6)]

        cand = _make_candidate(
            inst_id="INST_1",
            symbol="TCS",
            signal_date=dates[0],
            state=SignalState.BUY,
            is_valid=True,
            entry_ref=Decimal("100.00"),
            stop_loss=Decimal("90.00"),
            target_price=Decimal("120.00"),
        )
        strategy = MockStrategy({dates[0]: cand})

        # Bars stay between 98 and 102 (no stop, no target hit)
        bars = [
            _make_bar(dates[0], "100.00", "102.00", "98.00", "100.00"),
            _make_bar(dates[1], "100.00", "102.00", "98.00", "100.00"),
            _make_bar(dates[2], "100.00", "102.00", "98.00", "100.00"),
            _make_bar(dates[3], "100.00", "102.00", "98.00", "101.00"),
            _make_bar(dates[4], "101.00", "103.00", "99.00", "102.00"),
        ]

        # Configure max holding sessions to 3 sessions
        cfg = BacktestConfig(
            initial_capital=Decimal("100000.00"),
            max_holding_sessions=3,
            min_history_sessions=1,
        )
        sim = BacktestSimulator(cfg)
        res = sim.run(strategy, dates, {"INST_1": bars})

        assert len(res.trades) == 1
        trade = res.trades[0]
        assert trade.exit_reason == ExitReason.MAX_HOLDING_TIME
        assert trade.holding_sessions_count == 3
        assert trade.exit_price == Decimal("101.00")  # Day 4 close

    def test_opening_gap_too_large_skips_entry(self):
        """
        If next day opens > 2% away from expected entry price, order is not entered.
        """
        d1 = datetime.date(2024, 1, 1)
        d2 = datetime.date(2024, 1, 2)
        dates = [d1, d2]

        cand = _make_candidate(
            inst_id="INST_1",
            symbol="TCS",
            signal_date=d1,
            state=SignalState.BUY,
            is_valid=True,
            entry_ref=Decimal("100.00"),
            stop_loss=Decimal("95.00"),
            target_price=Decimal("110.00"),
        )
        strategy = MockStrategy({d1: cand})

        bars = [
            _make_bar(d1, "98.00", "101.00", "97.50", "100.00"),
            # Opens at 105.00 (5% gap up, exceeds default 2% tolerance)
            _make_bar(d2, "105.00", "112.00", "104.00", "108.00"),
        ]

        cfg = BacktestConfig(initial_capital=Decimal("100000.00"), min_history_sessions=1)
        sim = BacktestSimulator(cfg)
        res = sim.run(strategy, dates, {"INST_1": bars})

        # Trade should have been skipped due to excessive opening gap
        assert len(res.trades) == 0

    def test_baseline_comparison_generation(self):
        """
        Tests that baseline comparisons (Buy & Hold and Random Entry) are populated.
        """
        d1 = datetime.date(2024, 1, 1)
        d2 = datetime.date(2024, 1, 2)
        dates = [d1, d2]

        strategy = MockStrategy()
        bench_bars = [
            _make_bar(d1, "100.00", "102.00", "99.00", "100.00", inst_id="NIFTY", symbol="NIFTY"),
            _make_bar(d2, "100.00", "105.00", "99.50", "105.00", inst_id="NIFTY", symbol="NIFTY"),
        ]

        cfg = BacktestConfig(min_history_sessions=1)
        sim = BacktestSimulator(cfg)
        res = sim.run(strategy, dates, {"NIFTY": bench_bars}, benchmark_prices=bench_bars)

        assert res.baseline_comparison is not None
        # Buy & Hold return from 100 to 105 is +5.00%
        assert res.baseline_comparison.buy_and_hold_return_pct == Decimal("5.00")
