import datetime
from decimal import Decimal
import pytest

from signal_atlas.features import (
    TechnicalFeatureEngine,
    TechnicalFeatures,
    aggregate_daily_to_weekly,
    compute_atr,
    compute_ema,
    compute_macd,
    compute_relative_strength,
    compute_rsi,
    compute_sma,
    compute_weekly_trend,
)
from signal_atlas.quality.adjustment import AdjustedPriceRecord


def test_sma_calculation():
    series = [10, 20, 30, 40, 50]
    # SMA(3):
    # idx 0: None, idx 1: None
    # idx 2: (10+20+30)/3 = 20.0
    # idx 3: (20+30+40)/3 = 30.0
    # idx 4: (30+40+50)/3 = 40.0
    res = compute_sma(series, 3)
    assert len(res) == 5
    assert res[0] is None
    assert res[1] is None
    assert res[2] == Decimal("20.000000")
    assert res[3] == Decimal("30.000000")
    assert res[4] == Decimal("40.000000")


def test_sma_insufficient_length():
    series = [10, 20]
    res = compute_sma(series, 3)
    assert res == [None, None]


def test_ema_mathematical_precision():
    # 5-period EMA on simple series
    # alpha = 2 / (5 + 1) = 2/6 = 1/3
    series = [10, 11, 12, 13, 14, 15, 16]
    ema = compute_ema(series, 5)
    # Indices 0 to 3 should be None
    assert ema[:4] == [None, None, None, None]
    # Index 4: initial SMA = (10+11+12+13+14)/5 = 60/5 = 12.0
    assert ema[4] == Decimal("12.000000")
    # Index 5: alpha * 15 + (1 - alpha) * 12 = 5 + 8 = 13.0
    assert ema[5] == Decimal("13.000000")
    # Index 6: alpha * 16 + (1 - alpha) * 13 = 16/3 + 26/3 = 42/3 = 14.0
    assert ema[6] == Decimal("14.000000")


def test_rsi_wilder_smoothing_and_extremes():
    # Constant gains: RSI must be 100
    all_gains = [Decimal(100 + i * 2) for i in range(25)]
    rsi_gains = compute_rsi(all_gains, 14)
    assert rsi_gains[14] == Decimal("100.00")
    assert rsi_gains[-1] == Decimal("100.00")

    # Constant losses: RSI must be 0
    all_losses = [Decimal(200 - i * 2) for i in range(25)]
    rsi_losses = compute_rsi(all_losses, 14)
    assert rsi_losses[14] == Decimal("0.00")
    assert rsi_losses[-1] == Decimal("0.00")

    # Flat series: change = 0, RSI = 50.00
    flat = [Decimal("100.00")] * 20
    rsi_flat = compute_rsi(flat, 14)
    assert rsi_flat[14] == Decimal("50.00")


def test_atr_true_range_components():
    # Day 0: H=105, L=95, C=100 -> TR=10
    # Day 1: Gap Up: H=120, L=115, C=118, PrevClose=100 -> TR=max(120-115, |120-100|, |115-100|) = 20
    # Day 2: Gap Down: H=85, L=80, C=82, PrevClose=118 -> TR=max(85-80, |85-118|, |80-118|) = 38
    highs = [105, 120, 85]
    lows = [95, 115, 80]
    closes = [100, 118, 82]

    # ATR(2)
    # TR: [10, 20, 38]
    # ATR initial (index 1): (10 + 20) / 2 = 15.0
    # ATR index 2: (15 * 1 + 38) / 2 = 53 / 2 = 26.5
    atr = compute_atr(highs, lows, closes, 2)
    assert atr[0] is None
    assert atr[1] == Decimal("15.000000")
    assert atr[2] == Decimal("26.500000")


def test_macd_computation():
    # Generate 40 sessions of increasing prices
    prices = [Decimal(100 + i) for i in range(40)]
    macd_line, signal_line, histogram = compute_macd(prices, fast_period=12, slow_period=26, signal_period=9)
    assert len(macd_line) == 40
    # Fast 12 and Slow 26 means first valid MACD line is at index 25
    assert macd_line[24] is None
    assert macd_line[25] is not None
    # Signal line requires 9 MACD values: 25 + 8 = index 33
    assert signal_line[32] is None
    assert signal_line[33] is not None
    assert histogram[33] is not None
    assert histogram[33] == macd_line[33] - signal_line[33]


def test_weekly_bar_aggregation():
    # 5 daily sessions in Week 1, 3 daily sessions in Week 2
    dates = [
        datetime.date(2024, 1, 1),  # Mon W1
        datetime.date(2024, 1, 2),  # Tue W1
        datetime.date(2024, 1, 3),  # Wed W1
        datetime.date(2024, 1, 4),  # Thu W1
        datetime.date(2024, 1, 5),  # Fri W1
        datetime.date(2024, 1, 8),  # Mon W2
        datetime.date(2024, 1, 9),  # Tue W2
        datetime.date(2024, 1, 10), # Wed W2
    ]
    opens = [100, 102, 104, 101, 103, 110, 112, 111]
    highs = [105, 108, 107, 106, 109, 115, 118, 114]
    lows = [99, 101, 102, 98, 102, 108, 110, 109]
    closes = [103, 106, 105, 104, 108, 114, 113, 112]
    volumes = [1000, 1200, 1100, 1500, 2000, 3000, 2500, 2800]

    weekly = aggregate_daily_to_weekly(dates, opens, highs, lows, closes, volumes)
    assert len(weekly) == 2

    # Week 1
    w1 = weekly[0]
    assert w1.session_count == 5
    assert w1.start_date == datetime.date(2024, 1, 1)
    assert w1.end_date == datetime.date(2024, 1, 5)
    assert w1.open == Decimal("100")
    assert w1.high == Decimal("109")
    assert w1.low == Decimal("98")
    assert w1.close == Decimal("108")
    assert w1.volume == 6800

    # Week 2
    w2 = weekly[1]
    assert w2.session_count == 3
    assert w2.open == Decimal("110")
    assert w2.high == Decimal("118")
    assert w2.low == Decimal("108")
    assert w2.close == Decimal("112")
    assert w2.volume == 8300


def test_relative_strength_vs_benchmark():
    # Stock up 20% over 50 sessions, Benchmark up 10% -> RS = +0.1000 (1000 bps)
    stock = [Decimal("100")] * 51
    bench = [Decimal("200")] * 51
    stock[-1] = Decimal("120")  # +20%
    bench[-1] = Decimal("220")  # +10%

    rs = compute_relative_strength(stock, bench, lookback_sessions=50)
    assert rs is not None
    # r_stock = 0.20, r_bench = 0.10 => RS = +0.1000
    assert rs == Decimal("0.1000")


def test_feature_engine_point_in_time_boundary():
    engine = TechnicalFeatureEngine(min_required_sessions=50)
    base_date = datetime.date(2024, 1, 1)

    records = []
    for i in range(60):
        dt = base_date + datetime.timedelta(days=i)
        p = Decimal(100 + i)
        records.append(
            AdjustedPriceRecord(
                trade_date=dt,
                open=p,
                high=p + Decimal("2"),
                low=p - Decimal("2"),
                close=p,
                prev_close=p - Decimal("1"),
                raw_prev_close=p - Decimal("1"),
                volume=Decimal("10000"),
                raw_volume=10000,
                traded_value=p * Decimal("10000"),
                raw_traded_value=p * Decimal("10000"),
                cumulative_multiplier=Decimal("1.000000"),
                prev_close_multiplier=Decimal("1.000000"),
                adjustment_version="v1.4",
            )
        )

    # Evaluate at index 49 (as_of_date = base_date + 49 days, 50 sessions)
    as_of = base_date + datetime.timedelta(days=49)
    features = engine.extract_features(
        instrument_id="inst-1",
        symbol="TEST",
        as_of_date=as_of,
        records=records,  # Contains 60 records, but engine must bound to as_of
    )

    assert features.as_of_date == as_of
    assert features.history_sessions_count == 50
    assert features.sufficient_history is True
    assert features.close == Decimal("149")
    assert features.ema_20 is not None
    assert features.ema_50 is not None
    assert features.rsi_14 is not None
    assert features.atr_14 is not None
    assert features.avg_volume_20 == 10000


def test_feature_engine_time_series_consistency():
    engine = TechnicalFeatureEngine(min_required_sessions=20)
    base_date = datetime.date(2024, 1, 1)

    records = []
    for i in range(30):
        dt = base_date + datetime.timedelta(days=i)
        p = Decimal(100 + i * 2)
        records.append(
            AdjustedPriceRecord(
                trade_date=dt,
                open=p,
                high=p + Decimal("1"),
                low=p - Decimal("1"),
                close=p,
                prev_close=p - Decimal("2"),
                raw_prev_close=p - Decimal("2"),
                volume=Decimal(5000 + i * 100),
                raw_volume=5000 + i * 100,
                traded_value=p * Decimal(5000 + i * 100),
                raw_traded_value=p * Decimal(5000 + i * 100),
                cumulative_multiplier=Decimal("1.000000"),
                prev_close_multiplier=Decimal("1.000000"),
                adjustment_version="v1.4",
            )
        )

    ts_features = engine.extract_time_series_features("inst-1", "TEST", records)
    assert len(ts_features) == 30

    # Spot check: point-in-time extraction at index 25 must match ts_features[25] exactly
    pit_features = engine.extract_features(
        "inst-1", "TEST", as_of_date=records[25].trade_date, records=records[:26]
    )

    assert ts_features[25].as_of_date == pit_features.as_of_date
    assert ts_features[25].close == pit_features.close
    assert ts_features[25].ema_20 == pit_features.ema_20
    assert ts_features[25].rsi_14 == pit_features.rsi_14
    assert ts_features[25].atr_14 == pit_features.atr_14
    assert ts_features[25].avg_volume_20 == pit_features.avg_volume_20
