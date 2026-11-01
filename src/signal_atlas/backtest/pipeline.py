"""
pipeline.py - Complete Backtesting, Robustness & Tuning Orchestrator.

Orchestrates Phase 2 through Phase 7 of backtest_and_tuning_plan.md:
- Phase 2: Engine specification & execution rules.
- Phase 3: Development dataset splits (warm-up ~100 sessions to 2024-12-31; holdout strictly locked).
- Phase 4: Baseline simulation with frozen v1.0 parameters.
- Phase 5: Sanity & robustness tests (random entry, delay 1-day, cost stress, fill pessimism, drop top 5% trades/symbols, gate ablation).
- Phase 6: Walk-forward tuning across 4 expanding folds with experiment registry logging.
- Phase 7: Evaluation against pre-registered criteria and generation of reports/dev_report.md.
"""

import copy
import csv
import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
import yaml

from sqlalchemy import text

from signal_atlas.backtest.engine import (
    BacktestEngine,
    BacktestEngineConfig,
    EntryVariant,
    KillswitchVariant,
)
from signal_atlas.strategy.base import Strategy
from signal_atlas.backtest.metrics import calculate_comprehensive_metrics
from signal_atlas.backtest.models import (
    EquitySnapshot,
    ExitReason,
    PositionRecord,
)
from signal_atlas.backtest.robustness import (
    run_random_entry_baseline,
    run_remove_best_symbols,
    run_remove_best_trades,
)
from signal_atlas.backtest.walkforward import DEV_FOLDS, ExperimentRegistry, WalkForwardFold
from signal_atlas.db.session import get_db
from signal_atlas.features.indicators import compute_atr, compute_ema, compute_rsi
from signal_atlas.quality.adjustment import AdjustedPriceRecord, get_point_in_time_adjusted_history
from signal_atlas.strategy.trend_pullback import TrendPullbackParameters, TrendPullbackStrategy


class FastBacktestDataset:
    """
    In-memory representation of analytical price histories and precomputed indicators.
    Guarantees exact causal alignment with zero lookahead bias while enabling high-throughput simulations.
    """

    def __init__(
        self,
        trading_dates: List[datetime.date],
        prices_by_instrument: Dict[str, List[AdjustedPriceRecord]],
        symbols_by_instrument: Dict[str, str],
        benchmark_prices: List[AdjustedPriceRecord],
        universe_by_date: Optional[Dict[datetime.date, Set[str]]] = None,
    ):
        self.trading_dates = sorted(trading_dates)
        self.prices_by_instrument = prices_by_instrument
        self.symbols_by_instrument = symbols_by_instrument
        self.benchmark_prices = sorted(benchmark_prices, key=lambda x: x.trade_date)
        self.universe_by_date = universe_by_date

        # Date to index lookup
        self.date_to_idx = {dt: i for i, dt in enumerate(self.trading_dates)}

        # Benchmark 50 EMA and prices by date
        bench_closes = [b.close for b in self.benchmark_prices]
        bench_emas = compute_ema(bench_closes, 50)
        self.bench_by_date: Dict[datetime.date, AdjustedPriceRecord] = {}
        self.bench_ema_by_date: Dict[datetime.date, Decimal] = {}
        for b, ema in zip(self.benchmark_prices, bench_emas):
            self.bench_by_date[b.trade_date] = b
            if ema is not None:
                self.bench_ema_by_date[b.trade_date] = ema

        # Precompute indicator series for all instruments
        self.inst_data: Dict[str, Dict[str, Any]] = {}
        for inst_id, recs in self.prices_by_instrument.items():
            sym = self.symbols_by_instrument.get(inst_id, inst_id)
            recs_sorted = sorted(recs, key=lambda r: r.trade_date)
            closes = [r.close for r in recs_sorted]
            highs = [r.high for r in recs_sorted]
            lows = [r.low for r in recs_sorted]
            dates = [r.trade_date for r in recs_sorted]

            # Fast calendar week grouping for weekly trend
            weeks: List[List[int]] = []
            curr_wk: List[int] = []
            curr_key = None
            for idx, r in enumerate(recs_sorted):
                k = r.trade_date.isocalendar()[:2]
                if k != curr_key:
                    if curr_wk:
                        weeks.append(curr_wk)
                    curr_wk = [idx]
                    curr_key = k
                else:
                    curr_wk.append(idx)
            if curr_wk:
                weeks.append(curr_wk)

            # Precompute weekly bullish boolean for each daily bar
            weekly_bullish_by_idx: List[bool] = [False] * len(recs_sorted)
            for w_idx, wk in enumerate(weeks):
                prior_closes = [recs_sorted[w[-1]].close for w in weeks[:w_idx]]
                for day_idx in wk:
                    forming_close = recs_sorted[day_idx].close
                    series = prior_closes + [forming_close]
                    if len(series) >= 10:
                        w_emas = compute_ema(series, 10)
                        weekly_bullish_by_idx[day_idx] = forming_close > w_emas[-1] if w_emas[-1] else False
                    else:
                        weekly_bullish_by_idx[day_idx] = False

            self.inst_data[inst_id] = {
                "symbol": sym,
                "records": recs_sorted,
                "dates": dates,
                "date_map": {r.trade_date: (idx, r) for idx, r in enumerate(recs_sorted)},
                "ema20": compute_ema(closes, 20),
                "ema50": compute_ema(closes, 50),
                "rsi14": compute_rsi(closes, 14),
                "atr14": compute_atr(highs, lows, closes, 14),
                "weekly_bullish": weekly_bullish_by_idx,
            }


def load_development_dataset(
    max_symbols: int = 100,
    end_date: datetime.date = datetime.date(2024, 12, 31),
    use_point_in_time_universe: bool = True,
) -> FastBacktestDataset:
    """
    Loads development dataset up to end_date.
    Strictly excludes data past end_date (Locked Holdout).
    Supports point-in-time universe with monthly rebalancing (Task 1 / D1)
    or static top liquid universe for step-by-step attribution (Task 14).
    """
    print(f"Loading development dataset (<= {end_date}, PIT universe={use_point_in_time_universe})...")
    t0 = time.time()

    with get_db() as db:
        # Benchmark NIFTYBEES
        bench_inst_id = db.execute(text("""
            SELECT instrument_id FROM instrument_symbol_history WHERE symbol = 'NIFTYBEES' LIMIT 1
        """)).scalar()
        if not bench_inst_id:
            raise RuntimeError("Benchmark NIFTYBEES not found in database!")

        bench_history = get_point_in_time_adjusted_history(bench_inst_id, end_date, db=db)
        bench_dates = [b.trade_date for b in bench_history if b.trade_date <= end_date]

        universe_by_date: Optional[Dict[datetime.date, Set[str]]] = None
        prices_by_inst: Dict[str, List[AdjustedPriceRecord]] = {}
        symbols_by_inst: Dict[str, str] = {}

        if use_point_in_time_universe:
            pit_cache_path = Path("data/pit_universe_monthly_2022_2024.json")
            if not pit_cache_path.exists():
                raise FileNotFoundError(f"Missing PIT universe cache at {pit_cache_path}")

            pit_data = json.loads(pit_cache_path.read_text(encoding="utf-8"))
            snapshots = pit_data.get("snapshots", {})
            sorted_rebal_dates = sorted(datetime.date.fromisoformat(k) for k in snapshots.keys())

            # Map each trading date to latest rebalance date <= t
            universe_by_date = {}
            for dt in bench_dates:
                valid_rebals = [rd for rd in sorted_rebal_dates if rd <= dt]
                if valid_rebals:
                    latest_rd = valid_rebals[-1]
                    universe_by_date[dt] = set(snapshots[latest_rd.isoformat()]["instrument_ids"])
                else:
                    universe_by_date[dt] = set()

            all_inst_ids = set()
            for s in snapshots.values():
                all_inst_ids.update(s["instrument_ids"])

            sym_rows = db.execute(text("""
                SELECT DISTINCT ON (instrument_id) instrument_id, symbol
                FROM instrument_symbol_history
                WHERE instrument_id = ANY(:inst_ids)
                  AND (valid_from <= :end_dt OR valid_from IS NULL)
                ORDER BY instrument_id, valid_from DESC
            """), {"inst_ids": list(all_inst_ids), "end_dt": end_date}).fetchall()
            symbols_by_inst = {r[0]: r[1] for r in sym_rows}

            for inst_id in all_inst_ids:
                h = get_point_in_time_adjusted_history(inst_id, end_date, db=db)
                if len(h) >= 20:
                    prices_by_inst[inst_id] = h
        else:
            # Static universe query without delisting handling for Step 0 of Task 14 attribution
            rows = db.execute(text("""
                SELECT dpr.instrument_id, ish.symbol, avg(dpr.traded_value) as avg_tv
                FROM daily_prices_raw dpr
                JOIN instrument_symbol_history ish ON dpr.instrument_id = ish.instrument_id
                WHERE dpr.series = 'EQ' AND dpr.trade_date BETWEEN '2022-01-03' AND :end_dt
                  AND (ish.valid_to IS NULL OR ish.valid_to >= :end_dt)
                GROUP BY dpr.instrument_id, ish.symbol
                HAVING count(*) >= 100
                ORDER BY avg_tv DESC
                LIMIT :lim
            """), {"end_dt": end_date, "lim": max_symbols}).fetchall()

            for r in rows:
                inst_id, sym = r[0], r[1]
                h = get_point_in_time_adjusted_history(inst_id, end_date, db=db)
                if len(h) >= 50:
                    prices_by_inst[inst_id] = h
                    symbols_by_inst[inst_id] = sym

    print(f"Loaded {len(prices_by_inst)} instruments across {len(bench_dates)} trading sessions in {time.time() - t0:.2f}s")
    return FastBacktestDataset(
        trading_dates=bench_dates,
        prices_by_instrument=prices_by_inst,
        symbols_by_instrument=symbols_by_inst,
        benchmark_prices=bench_history,
        universe_by_date=universe_by_date,
    )


class FastSimulationRunner:
    """
    Adapter that delegates directly to the single authoritative BacktestEngine.
    Guarantees that all simulations use the exact same risk, fill, sizing, and metrics logic.
    """

    def __init__(self, dataset: FastBacktestDataset, config: Optional[BacktestEngineConfig] = None):
        self.dataset = dataset
        self.config = config or BacktestEngineConfig()
        self.engine = BacktestEngine(config=self.config)

    def run(
        self,
        params: TrendPullbackParameters,
        start_date: datetime.date,
        end_date: datetime.date,
        entry_variant: Optional[EntryVariant] = None,
        ignore_regime: bool = False,
        stress_costs: bool = False,
        delay_entry_by_one_day: bool = False,
        killswitch_variant_override: Optional[KillswitchVariant] = None,
        ranking_seed: Optional[int] = None,
        strategy: Optional[Strategy] = None,
        override_universe_by_date: Optional[Dict[datetime.date, Set[str]]] = None,
        max_holding_sessions: Optional[int] = None,
    ) -> Dict[str, Any]:
        trading_dates = [d for d in self.dataset.trading_dates if start_date <= d <= end_date]
        strat = strategy or TrendPullbackStrategy(params=params)
        u_by_date = override_universe_by_date if override_universe_by_date is not None else self.dataset.universe_by_date

        if max_holding_sessions is not None and max_holding_sessions != self.config.max_holding_sessions:
            cfg = self.config.model_copy(update={"max_holding_sessions": max_holding_sessions})
            eng = BacktestEngine(config=cfg)
        else:
            eng = self.engine

        return eng.run(
            strategy=strat,
            trading_dates=trading_dates,
            prices_by_instrument=self.dataset.prices_by_instrument,
            benchmark_prices=self.dataset.benchmark_prices,
            symbols_by_instrument=self.dataset.symbols_by_instrument,
            universe_by_date=u_by_date,
            ignore_regime=ignore_regime,
            entry_variant=entry_variant,
            stress_costs=stress_costs,
            delay_entry_by_one_day=delay_entry_by_one_day,
            killswitch_variant_override=killswitch_variant_override,
            ranking_seed=ranking_seed,
        )
