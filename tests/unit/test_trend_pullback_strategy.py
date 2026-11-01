import datetime
from decimal import Decimal
import pytest

from signal_atlas.features.models import TechnicalFeatures
from signal_atlas.strategy import (
    MarketContext,
    SignalState,
    StrategyCandidate,
    TrendPullbackParameters,
    TrendPullbackStrategy,
)
from signal_atlas.universe.models import UniverseMember


def create_sample_features(
    close: Decimal = Decimal("102.00"),
    ema_20: Decimal = Decimal("100.00"),
    ema_50: Decimal = Decimal("90.00"),
    rsi_14: Decimal = Decimal("50.00"),
    atr_14: Decimal = Decimal("4.00"),
    weekly_bullish: bool = True,
    sufficient: bool = True,
) -> TechnicalFeatures:
    """Helper creating valid TechnicalFeatures baseline."""
    return TechnicalFeatures(
        instrument_id="inst-1",
        symbol="TESTCO",
        as_of_date=datetime.date(2024, 6, 14),
        close=close,
        open=close - Decimal("1.00"),
        high=close + Decimal("2.00"),
        low=close - Decimal("2.00"),
        raw_close=close,
        ema_20=ema_20,
        ema_50=ema_50,
        rsi_14=rsi_14,
        atr_14=atr_14,
        avg_volume_20=50000,
        rolling_adtv_20=Decimal("5000000.00"),
        weekly_trend_bullish=weekly_bullish,
        sufficient_history=sufficient,
        history_sessions_count=126,
    )


def test_valid_buy_candidate():
    strategy = TrendPullbackStrategy()
    context = MarketContext(as_of_date=datetime.date(2024, 6, 14), is_market_regime_bullish=True)
    features = create_sample_features(
        close=Decimal("102.00"),  # 2% above EMA 20 (within 4% threshold)
        ema_20=Decimal("100.00"),
        ema_50=Decimal("90.00"),  # Strong uptrend
        rsi_14=Decimal("48.00"),  # Reset zone
        atr_14=Decimal("4.00"),
        weekly_bullish=True,
    )

    candidate = strategy.evaluate_candidate(features, context)

    assert candidate.signal_state == SignalState.BUY
    assert candidate.is_valid is True
    assert candidate.rejection_reason is None
    assert candidate.strategy_id == "trend_pullback"
    assert candidate.strategy_version == "v1.0"

    # Stop = Close - 1.5 * ATR = 102 - 6 = 96.00
    assert candidate.stop_loss == Decimal("96.00")
    # Target = Close + 3.0 * ATR = 102 + 12 = 114.00
    assert candidate.target_price == Decimal("114.00")
    assert candidate.risk_per_share == Decimal("6.00")
    assert candidate.reward_per_share == Decimal("12.00")
    # R:R = 12 / 6 = 2.00
    assert candidate.reward_to_risk == Decimal("2.00")


def test_bearish_market_regime_rejects_setup():
    strategy = TrendPullbackStrategy()
    context = MarketContext(as_of_date=datetime.date(2024, 6, 14), is_market_regime_bullish=False)
    features = create_sample_features()

    candidate = strategy.evaluate_candidate(features, context)
    assert candidate.signal_state == SignalState.AVOID
    assert candidate.is_valid is False
    assert candidate.rejection_reason == "MARKET_REGIME_BEARISH"


def test_insufficient_history_rejects_setup():
    strategy = TrendPullbackStrategy()
    context = MarketContext(as_of_date=datetime.date(2024, 6, 14), is_market_regime_bullish=True)
    features = create_sample_features(sufficient=False)

    candidate = strategy.evaluate_candidate(features, context)
    assert candidate.signal_state == SignalState.AVOID
    assert candidate.rejection_reason == "INSUFFICIENT_HISTORY"


def test_trend_breakdown_below_ema50_rejects_setup():
    strategy = TrendPullbackStrategy()
    context = MarketContext(as_of_date=datetime.date(2024, 6, 14), is_market_regime_bullish=True)
    features = create_sample_features(
        close=Decimal("85.00"),  # Below EMA 50
        ema_20=Decimal("92.00"),
        ema_50=Decimal("90.00"),
    )

    candidate = strategy.evaluate_candidate(features, context)
    assert candidate.signal_state == SignalState.AVOID
    assert candidate.rejection_reason == "NOT_ABOVE_EMA50"


def test_ema_inversion_rejects_setup():
    strategy = TrendPullbackStrategy()
    context = MarketContext(as_of_date=datetime.date(2024, 6, 14), is_market_regime_bullish=True)
    features = create_sample_features(
        close=Decimal("95.00"),
        ema_20=Decimal("88.00"),  # Inverted: EMA 20 < EMA 50
        ema_50=Decimal("90.00"),
    )

    candidate = strategy.evaluate_candidate(features, context)
    assert candidate.signal_state == SignalState.AVOID
    assert candidate.rejection_reason == "EMA_NOT_ALIGNED"


def test_extended_price_above_ema20_rejects_setup():
    strategy = TrendPullbackStrategy()
    context = MarketContext(as_of_date=datetime.date(2024, 6, 14), is_market_regime_bullish=True)
    features = create_sample_features(
        close=Decimal("110.00"),  # 10% above EMA 20 (exceeds 4% cap)
        ema_20=Decimal("100.00"),
        ema_50=Decimal("90.00"),
    )

    candidate = strategy.evaluate_candidate(features, context)
    assert candidate.signal_state == SignalState.AVOID
    assert candidate.rejection_reason == "EXTENDED_ABOVE_EMA20"


def test_rsi_extremes_reject_setup():
    strategy = TrendPullbackStrategy()
    context = MarketContext(as_of_date=datetime.date(2024, 6, 14), is_market_regime_bullish=True)

    # Overbought (> 60)
    overbought = create_sample_features(rsi_14=Decimal("68.00"))
    cand1 = strategy.evaluate_candidate(overbought, context)
    assert cand1.signal_state == SignalState.AVOID
    assert cand1.rejection_reason == "OVERBOUGHT_RSI_TOO_HIGH"

    # Momentum broken (< 40)
    oversold = create_sample_features(rsi_14=Decimal("35.00"))
    cand2 = strategy.evaluate_candidate(oversold, context)
    assert cand2.signal_state == SignalState.AVOID
    assert cand2.rejection_reason == "MOMENTUM_BROKEN_RSI_TOO_LOW"


def test_weekly_trend_bearish_rejects_setup():
    strategy = TrendPullbackStrategy()
    context = MarketContext(as_of_date=datetime.date(2024, 6, 14), is_market_regime_bullish=True)
    features = create_sample_features(weekly_bullish=False)

    candidate = strategy.evaluate_candidate(features, context)
    assert candidate.signal_state == SignalState.AVOID
    assert candidate.rejection_reason == "WEEKLY_TREND_BEARISH"


def test_next_day_entry_execution_timing():
    strategy = TrendPullbackStrategy()
    context = MarketContext(as_of_date=datetime.date(2024, 6, 14), is_market_regime_bullish=True)
    features = create_sample_features(close=Decimal("100.00"), atr_14=Decimal("4.00"))
    cand = strategy.evaluate_candidate(features, context)
    assert cand.signal_state == SignalState.BUY
    # Stop: 94.00, Target: 112.00, Entry ref: 100.00

    # 1. Normal opening: opens at 100.50 (0.5% gap) -> fills successfully
    is_valid, fill_price, reason = strategy.evaluate_next_session_entry(
        cand, next_open=Decimal("100.50"), next_high=Decimal("103.00"), next_low=Decimal("99.00")
    )
    assert is_valid is True
    assert fill_price == Decimal("100.50")
    assert reason is None

    # 2. Excessive gap up: opens at 104.00 (4% gap > 2% cap) -> skipped
    is_valid, fill_price, reason = strategy.evaluate_next_session_entry(
        cand, next_open=Decimal("104.00"), next_high=Decimal("106.00"), next_low=Decimal("103.00")
    )
    assert is_valid is False
    assert "OPENING_GAP_TOO_LARGE" in reason

    # 3. Gap below stop loss: opens at 93.00 (below stop 94.00) -> invalidated
    is_valid, fill_price, reason = strategy.evaluate_next_session_entry(
        cand, next_open=Decimal("93.00"), next_high=Decimal("95.00"), next_low=Decimal("90.00")
    )
    assert is_valid is False
    assert "GAPPED_BELOW_STOP" in reason

    # 4. Gap to target: opens at 113.00 (above target 112.00) -> skipped
    is_valid, fill_price, reason = strategy.evaluate_next_session_entry(
        cand, next_open=Decimal("113.00"), next_high=Decimal("115.00"), next_low=Decimal("112.00")
    )
    assert is_valid is False
    assert "GAPPED_TO_TARGET" in reason


def test_evaluate_universe_ranking():
    strategy = TrendPullbackStrategy()
    context = MarketContext(as_of_date=datetime.date(2024, 6, 14), is_market_regime_bullish=True)

    # Candidate 1: R:R = 2.0 (Target +12, Risk -6)
    f1 = create_sample_features(close=Decimal("100.00"), atr_14=Decimal("4.00"))
    f1.instrument_id = "inst-1"
    f1.symbol = "STOCK_A"

    # Candidate 2: R:R = 2.0 (Target +15, Risk -7.5) -> Equal RR, symbol tiebreak
    f2 = create_sample_features(
        close=Decimal("202.00"),
        ema_20=Decimal("200.00"),
        ema_50=Decimal("180.00"),
        atr_14=Decimal("5.00"),
    )
    f2.instrument_id = "inst-2"
    f2.symbol = "STOCK_B"

    # Candidate 3: Inverted trend -> AVOID
    f3 = create_sample_features(close=Decimal("80.00"), ema_50=Decimal("90.00"))
    f3.instrument_id = "inst-3"
    f3.symbol = "STOCK_C"

    members = [
        UniverseMember(
            instrument_id="inst-1", symbol="STOCK_A", isin="INE001A01010", series="EQ",
            observed_sessions_count=126, missing_sessions_count=0,
            trading_completeness=Decimal("1.0"), expected_lookback_sessions=126,
            valid_turnover_sessions_count=126, turnover_data_completeness=Decimal("1.0"),
            total_turnover=Decimal("1000000"), is_eligible=True,
        ),
        UniverseMember(
            instrument_id="inst-2", symbol="STOCK_B", isin="INE002B01020", series="EQ",
            observed_sessions_count=126, missing_sessions_count=0,
            trading_completeness=Decimal("1.0"), expected_lookback_sessions=126,
            valid_turnover_sessions_count=126, turnover_data_completeness=Decimal("1.0"),
            total_turnover=Decimal("2000000"), is_eligible=True,
        ),
        UniverseMember(
            instrument_id="inst-3", symbol="STOCK_C", isin="INE003C01030", series="EQ",
            observed_sessions_count=126, missing_sessions_count=0,
            trading_completeness=Decimal("1.0"), expected_lookback_sessions=126,
            valid_turnover_sessions_count=126, turnover_data_completeness=Decimal("1.0"),
            total_turnover=Decimal("500000"), is_eligible=True,
        ),
    ]

    features_map = {"inst-1": f1, "inst-2": f2, "inst-3": f3}
    candidates = strategy.evaluate_universe(features_map, members, context)

    assert len(candidates) == 3
    # Top 2 must be BUY, ranked by reward-to-risk and symbol
    assert candidates[0].signal_state == SignalState.BUY
    assert candidates[0].symbol == "STOCK_A"
    assert candidates[1].signal_state == SignalState.BUY
    assert candidates[1].symbol == "STOCK_B"
    # Third must be AVOID
    assert candidates[2].signal_state == SignalState.AVOID
    assert candidates[2].symbol == "STOCK_C"


def test_rejection_preserves_technical_geometry():
    """
    Verifies that when a setup is rejected (e.g. bearish market regime or technical filter),
    authentic ATR-based stop loss and profit targets are preserved rather than collapsing to close price.
    """
    strategy = TrendPullbackStrategy()
    context = MarketContext(as_of_date=datetime.date(2024, 6, 14), is_market_regime_bullish=False)
    features = create_sample_features(
        close=Decimal("100.00"),
        atr_14=Decimal("4.00"),
    )

    candidate = strategy.evaluate_candidate(features, context)

    # Signal state is AVOID because macro regime is bearish
    assert candidate.signal_state == SignalState.AVOID
    assert candidate.is_valid is False
    assert candidate.rejection_reason == "MARKET_REGIME_BEARISH"

    # Crucial architectural assertion: Geometry does NOT collapse to entry price!
    assert candidate.entry_reference == Decimal("100.00")
    assert candidate.stop_loss == Decimal("94.00")  # 100 - (4 * 1.5)
    assert candidate.target_price == Decimal("112.00")  # 100 + (4 * 3.0)
    assert candidate.risk_per_share == Decimal("6.00")
    assert candidate.reward_per_share == Decimal("12.00")
    assert candidate.reward_to_risk == Decimal("2.00")

