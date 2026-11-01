"""
test_grid_candidate_baseline_equivalence.py - Task E Equivalence Unit Test.

Verifies that a grid point equal to baseline (Candidate 1: stop_atr 1.5, target_r 2.0)
reproduces the baseline strategy configuration and output exactly.
"""

from decimal import Decimal
import datetime
from signal_atlas.backtest.walkforward import PARAM_GRID, apply_grid_params
from signal_atlas.features.models import TechnicalFeatures
from signal_atlas.strategy.models import MarketContext, TrendPullbackParameters
from signal_atlas.strategy.trend_pullback import TrendPullbackStrategy


def test_grid_candidate_1_equals_baseline_configuration():
    base_params = TrendPullbackParameters()
    candidate_1_grid = PARAM_GRID[1]  # {"stop_atr_multiplier": Decimal("1.5"), "target_r_multiple": Decimal("2.0")}
    candidate_1_params = apply_grid_params(base_params, candidate_1_grid)

    assert candidate_1_params.stop_atr_multiplier == base_params.stop_atr_multiplier, (
        f"Stop ATR multiplier mismatch: {candidate_1_params.stop_atr_multiplier} != {base_params.stop_atr_multiplier}"
    )
    assert candidate_1_params.target_r_multiple == base_params.target_r_multiple, (
        f"Target R multiple mismatch: {candidate_1_params.target_r_multiple} != {base_params.target_r_multiple}"
    )


def test_grid_candidate_1_evaluates_identically_to_baseline():
    base_params = TrendPullbackParameters()
    candidate_1_params = apply_grid_params(base_params, PARAM_GRID[1])

    strat_base = TrendPullbackStrategy(params=base_params)
    strat_cand = TrendPullbackStrategy(params=candidate_1_params)

    # Test across various price and ATR values
    test_cases = [
        (Decimal("100.00"), Decimal("2.50")),
        (Decimal("254.35"), Decimal("6.15")),
        (Decimal("1450.00"), Decimal("22.80")),
        (Decimal("15.20"), Decimal("0.45")),
    ]

    ctx = MarketContext(
        as_of_date=datetime.date(2023, 6, 1),
        benchmark_symbol="NIFTY50",
        benchmark_close=Decimal("18500.00"),
        benchmark_ema_200=Decimal("18000.00"),
        is_market_regime_bullish=True,
    )

    for close_p, atr in test_cases:
        feat = TechnicalFeatures(
            instrument_id="TEST-001",
            symbol="TESTSYM",
            as_of_date=datetime.date(2023, 6, 1),
            raw_close=close_p,
            open=close_p,
            high=close_p * Decimal("1.01"),
            low=close_p * Decimal("0.99"),
            close=close_p,
            ema_20=close_p * Decimal("0.98"),
            ema_50=close_p * Decimal("0.95"),
            rsi_14=Decimal("52.00"),
            atr_14=atr,
            weekly_trend_bullish=True,
            history_sessions_count=100,
            sufficient_history=True,
        )

        res_base = strat_base.evaluate_candidate(feat, market_context=ctx)
        res_cand = strat_cand.evaluate_candidate(feat, market_context=ctx)

        assert res_base.signal_state == res_cand.signal_state
        assert res_base.stop_loss == res_cand.stop_loss
        assert res_base.target_price == res_cand.target_price
        assert res_base.risk_per_share == res_cand.risk_per_share
        assert res_base.reward_per_share == res_cand.reward_per_share
        assert res_base.reward_to_risk == res_cand.reward_to_risk
