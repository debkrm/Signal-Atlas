"""
indicators.py - Pure mathematical technical indicator formulas for Signal Atlas.

All functions are pure, deterministic, and free of I/O.
Computations preserve decimal safety without floating-point representation drift.
"""

import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence, Tuple


PRECISION_6 = Decimal("0.000001")
PRECISION_4 = Decimal("0.0001")
PRECISION_2 = Decimal("0.01")


def to_decimal(val: Decimal | float | int | str) -> Decimal:
    """Helper to convert numeric inputs safely to Decimal."""
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def compute_sma(series: Sequence[Decimal | float | int], period: int) -> List[Optional[Decimal]]:
    """
    Computes Simple Moving Average (SMA).
    Returns None for indices 0 to period - 2.
    """
    n = len(series)
    if period <= 0:
        raise ValueError(f"Period must be positive, got {period}")
    if n < period:
        return [None] * n

    dec_series = [to_decimal(x) for x in series]
    result: List[Optional[Decimal]] = [None] * (period - 1)

    window_sum = sum(dec_series[:period])
    result.append((window_sum / Decimal(period)).quantize(PRECISION_6, rounding=ROUND_HALF_UP))

    for i in range(period, n):
        window_sum += dec_series[i] - dec_series[i - period]
        result.append((window_sum / Decimal(period)).quantize(PRECISION_6, rounding=ROUND_HALF_UP))

    return result


def compute_ema(series: Sequence[Decimal | float | int], period: int) -> List[Optional[Decimal]]:
    """
    Computes Exponential Moving Average (EMA).
    - Initial value at index period - 1 is the arithmetic mean (SMA) of the first 'period' values.
    - Subsequent values: EMA_t = alpha * Price_t + (1 - alpha) * EMA_{t-1}
      where alpha = 2 / (period + 1).
    - Returns None for indices prior to period - 1.
    """
    n = len(series)
    if period <= 0:
        raise ValueError(f"Period must be positive, got {period}")
    if n < period:
        return [None] * n

    dec_series = [to_decimal(x) for x in series]
    result: List[Optional[Decimal]] = [None] * (period - 1)

    # Initial seed is SMA of first 'period' bars
    initial_sma = sum(dec_series[:period]) / Decimal(period)
    current_ema = initial_sma.quantize(PRECISION_6, rounding=ROUND_HALF_UP)
    result.append(current_ema)

    alpha = Decimal("2") / Decimal(period + 1)
    one_minus_alpha = Decimal("1") - alpha

    for i in range(period, n):
        current_ema = (alpha * dec_series[i] + one_minus_alpha * current_ema).quantize(
            PRECISION_6, rounding=ROUND_HALF_UP
        )
        result.append(current_ema)

    return result


def compute_rsi(series: Sequence[Decimal | float | int], period: int = 14) -> List[Optional[Decimal]]:
    """
    Computes Relative Strength Index (RSI) using J. Welles Wilder's smoothing method.
    - Period defaults to 14 sessions.
    - Initial average gain/loss at index 'period' is the arithmetic mean of gains/losses.
    - Subsequent smoothed values:
        AvgGain_t = (AvgGain_{t-1} * (period - 1) + Gain_t) / period
        AvgLoss_t = (AvgLoss_{t-1} * (period - 1) + Loss_t) / period
    - RSI = 100 - (100 / (1 + RS)) where RS = AvgGain / AvgLoss.
    - Returns None for indices < period.
    """
    n = len(series)
    if period <= 0:
        raise ValueError(f"Period must be positive, got {period}")
    if n <= period:
        return [None] * n

    dec_series = [to_decimal(x) for x in series]
    result: List[Optional[Decimal]] = [None] * period

    gains: List[Decimal] = []
    losses: List[Decimal] = []

    for i in range(1, n):
        change = dec_series[i] - dec_series[i - 1]
        if change > Decimal("0"):
            gains.append(change)
            losses.append(Decimal("0"))
        else:
            gains.append(Decimal("0"))
            losses.append(-change)

    # Initial average gain & loss over first 'period' price changes
    avg_gain = sum(gains[:period]) / Decimal(period)
    avg_loss = sum(losses[:period]) / Decimal(period)

    def _calc_rsi(g: Decimal, l: Decimal) -> Decimal:
        if l == Decimal("0"):
            return Decimal("100.00") if g > Decimal("0") else Decimal("50.00")
        if g == Decimal("0"):
            return Decimal("0.00")
        rs = g / l
        rsi = Decimal("100") - (Decimal("100") / (Decimal("1") + rs))
        return rsi.quantize(PRECISION_2, rounding=ROUND_HALF_UP)

    result.append(_calc_rsi(avg_gain, avg_loss))

    # Wilder smoothing for subsequent bars
    period_dec = Decimal(period)
    weight_prev = period_dec - Decimal("1")

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * weight_prev + gains[i]) / period_dec
        avg_loss = (avg_loss * weight_prev + losses[i]) / period_dec
        result.append(_calc_rsi(avg_gain, avg_loss))

    return result


def compute_macd(
    series: Sequence[Decimal | float | int],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Tuple[List[Optional[Decimal]], List[Optional[Decimal]], List[Optional[Decimal]]]:
    """
    Computes standard MACD (Moving Average Convergence Divergence).
    - macd_line = EMA(fast) - EMA(slow)
    - signal_line = EMA(signal_period) of macd_line
    - histogram = macd_line - signal_line
    """
    n = len(series)
    if fast_period >= slow_period:
        raise ValueError(f"fast_period ({fast_period}) must be less than slow_period ({slow_period})")

    fast_ema = compute_ema(series, fast_period)
    slow_ema = compute_ema(series, slow_period)

    macd_line: List[Optional[Decimal]] = [None] * n
    for i in range(n):
        if fast_ema[i] is not None and slow_ema[i] is not None:
            macd_line[i] = (fast_ema[i] - slow_ema[i]).quantize(PRECISION_6, rounding=ROUND_HALF_UP)

    # Calculate signal line over valid MACD line values
    valid_macd_indices = [i for i, v in enumerate(macd_line) if v is not None]
    signal_line: List[Optional[Decimal]] = [None] * n
    histogram: List[Optional[Decimal]] = [None] * n

    if len(valid_macd_indices) >= signal_period:
        valid_macd_values = [macd_line[i] for i in valid_macd_indices]
        sig_ema = compute_ema(valid_macd_values, signal_period)

        for sub_idx, original_idx in enumerate(valid_macd_indices):
            s_val = sig_ema[sub_idx]
            signal_line[original_idx] = s_val
            if s_val is not None and macd_line[original_idx] is not None:
                histogram[original_idx] = (macd_line[original_idx] - s_val).quantize(
                    PRECISION_6, rounding=ROUND_HALF_UP
                )

    return macd_line, signal_line, histogram


def compute_atr(
    highs: Sequence[Decimal | float | int],
    lows: Sequence[Decimal | float | int],
    closes: Sequence[Decimal | float | int],
    period: int = 14,
) -> List[Optional[Decimal]]:
    """
    Computes Average True Range (ATR) using J. Welles Wilder's smoothing method.
    True Range:
      TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)
      For bar 0: TR_0 = H_0 - L_0.
    Initial ATR at index period - 1 is arithmetic mean of first 'period' TRs.
    Subsequent ATR:
      ATR_t = (ATR_{t-1} * (period - 1) + TR_t) / period
    """
    n = len(closes)
    if len(highs) != n or len(lows) != n:
        raise ValueError("Highs, lows, and closes must have identical lengths")
    if period <= 0:
        raise ValueError(f"Period must be positive, got {period}")
    if n < period:
        return [None] * n

    dec_h = [to_decimal(x) for x in highs]
    dec_l = [to_decimal(x) for x in lows]
    dec_c = [to_decimal(x) for x in closes]

    true_ranges: List[Decimal] = []
    # Bar 0
    true_ranges.append(dec_h[0] - dec_l[0])

    for i in range(1, n):
        tr1 = dec_h[i] - dec_l[i]
        tr2 = abs(dec_h[i] - dec_c[i - 1])
        tr3 = abs(dec_l[i] - dec_c[i - 1])
        true_ranges.append(max(tr1, tr2, tr3))

    result: List[Optional[Decimal]] = [None] * (period - 1)

    initial_atr = sum(true_ranges[:period]) / Decimal(period)
    current_atr = initial_atr.quantize(PRECISION_6, rounding=ROUND_HALF_UP)
    result.append(current_atr)

    period_dec = Decimal(period)
    weight_prev = period_dec - Decimal("1")

    for i in range(period, n):
        current_atr = ((current_atr * weight_prev + true_ranges[i]) / period_dec).quantize(
            PRECISION_6, rounding=ROUND_HALF_UP
        )
        result.append(current_atr)

    return result


def compute_relative_strength(
    stock_closes: Sequence[Decimal | float | int],
    benchmark_closes: Sequence[Decimal | float | int],
    lookback_sessions: int = 50,
) -> Optional[Decimal]:
    """
    Computes comparative Relative Strength (excess return) of stock vs benchmark
    over trailing lookback_sessions:
      R_stock = (Close_t - Close_{t-lookback}) / Close_{t-lookback}
      R_bench = (Bench_t - Bench_{t-lookback}) / Bench_{t-lookback}
      RS = R_stock - R_bench
    Returns None if insufficient history in either series.
    """
    if len(stock_closes) < lookback_sessions + 1 or len(benchmark_closes) < lookback_sessions + 1:
        return None

    s_curr = to_decimal(stock_closes[-1])
    s_past = to_decimal(stock_closes[-1 - lookback_sessions])
    b_curr = to_decimal(benchmark_closes[-1])
    b_past = to_decimal(benchmark_closes[-1 - lookback_sessions])

    if s_past <= Decimal("0") or b_past <= Decimal("0"):
        return None

    r_stock = (s_curr - s_past) / s_past
    r_bench = (b_curr - b_past) / b_past

    return (r_stock - r_bench).quantize(PRECISION_4, rounding=ROUND_HALF_UP)


class WeeklyBar:
    """Consolidated weekly bar derived deterministically from daily trading sessions."""
    def __init__(self, year: int, week: int, start_date: datetime.date, end_date: datetime.date):
        self.year = year
        self.week = week
        self.start_date = start_date
        self.end_date = end_date
        self.open: Decimal = Decimal("0")
        self.high: Decimal = Decimal("-Infinity")
        self.low: Decimal = Decimal("Infinity")
        self.close: Decimal = Decimal("0")
        self.volume: int = 0
        self.session_count: int = 0


def aggregate_daily_to_weekly(
    dates: Sequence[datetime.date],
    opens: Sequence[Decimal | float | int],
    highs: Sequence[Decimal | float | int],
    lows: Sequence[Decimal | float | int],
    closes: Sequence[Decimal | float | int],
    volumes: Sequence[int],
) -> List[WeeklyBar]:
    """
    Aggregates daily bars into standard calendar weekly bars (ISO calendar year/week).
    Preserves exact chronological order and handles holidays / truncated weeks.
    """
    n = len(dates)
    if not (n == len(opens) == len(highs) == len(lows) == len(closes) == len(volumes)):
        raise ValueError("All daily price arrays must have identical length")
    if n == 0:
        return []

    weekly_bars: List[WeeklyBar] = []
    current_key: Optional[Tuple[int, int]] = None
    current_bar: Optional[WeeklyBar] = None

    for i in range(n):
        dt = dates[i]
        iso_year, iso_week, _ = dt.isocalendar()
        key = (iso_year, iso_week)

        o = to_decimal(opens[i])
        h = to_decimal(highs[i])
        l = to_decimal(lows[i])
        c = to_decimal(closes[i])
        v = int(volumes[i])

        if key != current_key:
            current_key = key
            current_bar = WeeklyBar(year=iso_year, week=iso_week, start_date=dt, end_date=dt)
            current_bar.open = o
            current_bar.high = h
            current_bar.low = l
            current_bar.close = c
            current_bar.volume = v
            current_bar.session_count = 1
            weekly_bars.append(current_bar)
        else:
            assert current_bar is not None
            current_bar.end_date = dt
            current_bar.high = max(current_bar.high, h)
            current_bar.low = min(current_bar.low, l)
            current_bar.close = c
            current_bar.volume += v
            current_bar.session_count += 1

    return weekly_bars


def compute_weekly_trend(
    dates: Sequence[datetime.date],
    opens: Sequence[Decimal | float | int],
    highs: Sequence[Decimal | float | int],
    lows: Sequence[Decimal | float | int],
    closes: Sequence[Decimal | float | int],
    volumes: Sequence[int],
    weekly_ema_period: int = 10,
) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[bool]]:
    """
    Computes latest weekly trend derived from daily data:
    - Aggregates daily records into weekly candles.
    - Computes weekly EMA (default: 10-week EMA, ~50 daily sessions).
    - Returns (latest_weekly_close, latest_weekly_ema, is_bullish).
    """
    weekly_bars = aggregate_daily_to_weekly(dates, opens, highs, lows, closes, volumes)
    if len(weekly_bars) < weekly_ema_period:
        return (
            weekly_bars[-1].close if weekly_bars else None,
            None,
            None,
        )

    w_closes = [b.close for b in weekly_bars]
    w_emas = compute_ema(w_closes, weekly_ema_period)

    latest_close = w_closes[-1]
    latest_ema = w_emas[-1]
    is_bullish = (latest_close > latest_ema) if latest_ema is not None else None

    return latest_close, latest_ema, is_bullish
