"""
engine.py - Technical Feature Extraction Engine for Signal Atlas.

Orchestrates point-in-time technical indicator calculations over adjusted analytical history.
Enforces that only records on or before as_of_date are evaluated, guaranteeing zero future leakage.
"""

import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from signal_atlas.features.indicators import (
    compute_atr,
    compute_ema,
    compute_macd,
    compute_relative_strength,
    compute_rsi,
    compute_sma,
    compute_weekly_trend,
    to_decimal,
)
from signal_atlas.features.models import TechnicalFeatures
from signal_atlas.quality.adjustment import AdjustedPriceRecord, get_point_in_time_adjusted_history


class TechnicalFeatureEngine:
    """
    Deterministic Feature Engine for NSE cash equities.
    Calculates technical indicators from point-in-time adjusted historical price records.
    """

    def __init__(
        self,
        ema_fast_period: int = 20,
        ema_slow_period: int = 50,
        rsi_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        atr_period: int = 14,
        volume_avg_period: int = 20,
        weekly_ema_period: int = 10,
        rs_lookback_sessions: int = 50,
        min_required_sessions: int = 50,
    ):
        self.ema_fast_period = ema_fast_period
        self.ema_slow_period = ema_slow_period
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.atr_period = atr_period
        self.volume_avg_period = volume_avg_period
        self.weekly_ema_period = weekly_ema_period
        self.rs_lookback_sessions = rs_lookback_sessions
        self.min_required_sessions = min_required_sessions

    def extract_features(
        self,
        instrument_id: str,
        symbol: str,
        as_of_date: datetime.date,
        records: Sequence[AdjustedPriceRecord],
        benchmark_records: Optional[Sequence[AdjustedPriceRecord]] = None,
    ) -> TechnicalFeatures:
        """
        Extracts point-in-time technical features for an instrument as of as_of_date.
        Precondition: records must already be bounded by trade_date <= as_of_date and sorted chronologically.
        """
        # Strictly verify boundary condition: no record can exceed as_of_date
        bounded_records = [r for r in records if r.trade_date <= as_of_date]
        if not bounded_records:
            raise ValueError(f"No price records available on or before {as_of_date} for {symbol} ({instrument_id})")

        latest_rec = bounded_records[-1]
        n_sessions = len(bounded_records)
        sufficient = n_sessions >= self.min_required_sessions

        dates = [r.trade_date for r in bounded_records]
        opens = [r.open for r in bounded_records]
        highs = [r.high for r in bounded_records]
        lows = [r.low for r in bounded_records]
        closes = [r.close for r in bounded_records]
        volumes = [r.volume for r in bounded_records]
        turnovers = [r.traded_value for r in bounded_records]

        # 1. EMAs
        ema_20_series = compute_ema(closes, self.ema_fast_period)
        ema_50_series = compute_ema(closes, self.ema_slow_period)
        latest_ema_20 = ema_20_series[-1]
        latest_ema_50 = ema_50_series[-1]

        # 2. RSI
        rsi_series = compute_rsi(closes, self.rsi_period)
        latest_rsi = rsi_series[-1]

        # 3. MACD
        macd_line, macd_sig, macd_hist = compute_macd(
            closes, self.macd_fast, self.macd_slow, self.macd_signal
        )
        latest_macd_line = macd_line[-1]
        latest_macd_sig = macd_sig[-1]
        latest_macd_hist = macd_hist[-1]

        # 4. ATR
        atr_series = compute_atr(highs, lows, closes, self.atr_period)
        latest_atr = atr_series[-1]

        # 5. Volume & ADTV
        vol_sma = compute_sma(volumes, self.volume_avg_period)
        latest_avg_vol = int(vol_sma[-1].quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if vol_sma[-1] is not None else None

        # Filter None turnovers when calculating rolling ADTV
        valid_turnovers = [t if t is not None else Decimal("0.00") for t in turnovers]
        adtv_sma = compute_sma(valid_turnovers, self.volume_avg_period)
        latest_adtv = adtv_sma[-1]

        vol_ratio: Optional[Decimal] = None
        if latest_avg_vol is not None and latest_avg_vol > 0:
            vol_ratio = (Decimal(latest_rec.volume) / Decimal(latest_avg_vol)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        # 6. Weekly Trend
        w_close, w_ema, is_bullish = compute_weekly_trend(
            dates, opens, highs, lows, closes, volumes, self.weekly_ema_period
        )

        # 7. Relative Strength vs Benchmark
        rel_strength: Optional[Decimal] = None
        if benchmark_records:
            b_bounded = [b for b in benchmark_records if b.trade_date <= as_of_date]
            b_closes = [b.close for b in b_bounded]
            rel_strength = compute_relative_strength(
                closes, b_closes, self.rs_lookback_sessions
            )

        raw_c = getattr(latest_rec, "raw_close", None)
        if raw_c is None:
            raw_c = (latest_rec.close * getattr(latest_rec, "cumulative_multiplier", Decimal("1"))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        return TechnicalFeatures(
            instrument_id=instrument_id,
            symbol=symbol,
            as_of_date=latest_rec.trade_date,
            close=latest_rec.close,
            open=latest_rec.open,
            high=latest_rec.high,
            low=latest_rec.low,
            raw_close=raw_c,
            ema_20=latest_ema_20,
            ema_50=latest_ema_50,
            rsi_14=latest_rsi,
            macd_line=latest_macd_line,
            macd_signal=latest_macd_sig,
            macd_hist=latest_macd_hist,
            atr_14=latest_atr,
            avg_volume_20=latest_avg_vol,
            rolling_adtv_20=latest_adtv,
            volume_ratio_20=vol_ratio,
            weekly_close=w_close,
            weekly_ema_10=w_ema,
            weekly_trend_bullish=is_bullish,
            relative_strength_50=rel_strength,
            sufficient_history=sufficient,
            history_sessions_count=n_sessions,
        )

    def extract_time_series_features(
        self,
        instrument_id: str,
        symbol: str,
        records: Sequence[AdjustedPriceRecord],
        benchmark_records: Optional[Sequence[AdjustedPriceRecord]] = None,
    ) -> List[TechnicalFeatures]:
        """
        Precomputes chronological TechnicalFeatures for each date t in records.
        Used by backtest simulation for vectorized / streaming signal evaluation without lookahead bias.
        """
        n = len(records)
        if n == 0:
            return []

        dates = [r.trade_date for r in records]
        opens = [r.open for r in records]
        highs = [r.high for r in records]
        lows = [r.low for r in records]
        closes = [r.close for r in records]
        volumes = [r.volume for r in records]
        turnovers = [r.traded_value if r.traded_value is not None else Decimal("0.00") for r in records]

        ema_20_series = compute_ema(closes, self.ema_fast_period)
        ema_50_series = compute_ema(closes, self.ema_slow_period)
        rsi_series = compute_rsi(closes, self.rsi_period)
        macd_line, macd_sig, macd_hist = compute_macd(
            closes, self.macd_fast, self.macd_slow, self.macd_signal
        )
        atr_series = compute_atr(highs, lows, closes, self.atr_period)
        vol_sma = compute_sma(volumes, self.volume_avg_period)
        adtv_sma = compute_sma(turnovers, self.volume_avg_period)

        # Precompute benchmark map if supplied
        bench_close_by_date: Dict[datetime.date, Decimal] = {}
        if benchmark_records:
            bench_close_by_date = {b.trade_date: b.close for b in benchmark_records}

        features_list: List[TechnicalFeatures] = []

        for i in range(n):
            rec = records[i]
            n_history = i + 1
            sufficient = n_history >= self.min_required_sessions

            avg_v = int(vol_sma[i].quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if vol_sma[i] is not None else None
            vol_r: Optional[Decimal] = None
            if avg_v is not None and avg_v > 0:
                vol_r = (Decimal(rec.volume) / Decimal(avg_v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # Trailing weekly trend up to index i
            w_close, w_ema, is_bullish = compute_weekly_trend(
                dates[: i + 1],
                opens[: i + 1],
                highs[: i + 1],
                lows[: i + 1],
                closes[: i + 1],
                volumes[: i + 1],
                self.weekly_ema_period,
            )

            # Relative strength up to index i
            rel_strength: Optional[Decimal] = None
            if benchmark_records and i >= self.rs_lookback_sessions:
                s_curr = closes[i]
                s_past = closes[i - self.rs_lookback_sessions]
                curr_date = dates[i]
                past_date = dates[i - self.rs_lookback_sessions]
                if curr_date in bench_close_by_date and past_date in bench_close_by_date:
                    b_curr = bench_close_by_date[curr_date]
                    b_past = bench_close_by_date[past_date]
                    if s_past > Decimal("0") and b_past > Decimal("0"):
                        r_s = (s_curr - s_past) / s_past
                        r_b = (b_curr - b_past) / b_past
                        rel_strength = (r_s - r_b).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

            raw_c = getattr(rec, "raw_close", None)
            if raw_c is None:
                raw_c = (rec.close * getattr(rec, "cumulative_multiplier", Decimal("1"))).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

            feat = TechnicalFeatures(
                instrument_id=instrument_id,
                symbol=symbol,
                as_of_date=rec.trade_date,
                close=rec.close,
                open=rec.open,
                high=rec.high,
                low=rec.low,
                raw_close=raw_c,
                ema_20=ema_20_series[i],
                ema_50=ema_50_series[i],
                rsi_14=rsi_series[i],
                macd_line=macd_line[i],
                macd_signal=macd_sig[i],
                macd_hist=macd_hist[i],
                atr_14=atr_series[i],
                avg_volume_20=avg_v,
                rolling_adtv_20=adtv_sma[i],
                volume_ratio_20=vol_r,
                weekly_close=w_close,
                weekly_ema_10=w_ema,
                weekly_trend_bullish=is_bullish,
                relative_strength_50=rel_strength,
                sufficient_history=sufficient,
                history_sessions_count=n_history,
            )
            features_list.append(feat)

        return features_list

    def get_point_in_time_features(
        self,
        instrument_id: str,
        as_of_date: datetime.date,
        symbol: str = "EQUITY",
        series: str = "EQ",
        db: Optional[Session] = None,
        benchmark_records: Optional[Sequence[AdjustedPriceRecord]] = None,
    ) -> TechnicalFeatures:
        """
        Queries dynamically adjusted historical price records up to as_of_date
        and extracts point-in-time TechnicalFeatures.
        """
        records = get_point_in_time_adjusted_history(
            instrument_id=instrument_id,
            as_of_date=as_of_date,
            series=series,
            db=db,
            adjustment_version="v1.4",
        )
        if not records:
            raise ValueError(f"No adjusted history found for {instrument_id} on or before {as_of_date}")

        return self.extract_features(
            instrument_id=instrument_id,
            symbol=symbol,
            as_of_date=as_of_date,
            records=records,
            benchmark_records=benchmark_records,
        )
