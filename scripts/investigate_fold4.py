"""
investigate_fold4.py - Task 11 Deep-Dive on H2 2024 (Fold 4 Test Window: 2024-07-01 to 2024-12-31).
"""

import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Dict, List
import numpy as np

from signal_atlas.backtest.engine import BacktestEngine, BacktestEngineConfig
from signal_atlas.backtest.pipeline import FastBacktestDataset, load_development_dataset
from signal_atlas.backtest.robustness import run_real_random_entry_baseline
from signal_atlas.strategy.trend_pullback import TrendPullbackParameters, TrendPullbackStrategy


def investigate_fold4() -> Dict[str, Any]:
    print("================================================================================")
    print("TASK 11: DEEP-DIVE ON H2 2024 (FOLD 4 TEST PERIOD)")
    print("================================================================================")

    f4_start = datetime.date(2024, 7, 1)
    f4_end = datetime.date(2024, 12, 31)

    dataset = load_development_dataset(end_date=f4_end, use_point_in_time_universe=True)
    f4_dates = [d for d in dataset.trading_dates if f4_start <= d <= f4_end]

    print(f"Fold 4 test sessions: {len(f4_dates)} sessions from {f4_start} to {f4_end}")

    # Market regime analysis in Fold 4
    bullish_sessions = 0
    bearish_sessions = 0
    for d in f4_dates:
        b_rec = dataset.bench_by_date.get(d)
        b_ema = dataset.bench_ema_by_date.get(d)
        if b_rec and b_ema:
            if b_rec.close > b_ema:
                bullish_sessions += 1
            else:
                bearish_sessions += 1

    print(f"Regime Breakdown: {bullish_sessions} Bullish sessions, {bearish_sessions} Bearish sessions ({bearish_sessions/len(f4_dates)*100:.1f}% Bearish)")

    # Run BacktestEngine on Fold 4
    base_params = TrendPullbackParameters()
    engine = BacktestEngine(config=BacktestEngineConfig())
    res_f4 = engine.run(
        strategy=TrendPullbackStrategy(params=base_params),
        trading_dates=f4_dates,
        prices_by_instrument=dataset.prices_by_instrument,
        benchmark_prices=dataset.benchmark_prices,
        symbols_by_instrument=dataset.symbols_by_instrument,
        universe_by_date=dataset.universe_by_date,
    )

    m = res_f4["metrics"]
    trades = res_f4["trades"]
    print(f"Fold 4 Completed Trades: {m['total_trades']}")
    print(f"Fold 4 Win Rate: {m['win_rate_pct']:.2f}%")
    print(f"Fold 4 Expectancy: {m['expectancy_r']:+.3f} R")
    print(f"Fold 4 Profit Factor: {m['profit_factor']:.2f}")
    print(f"Fold 4 Net Return: {m['total_return_pct']:+.2f}%")
    print(f"Fold 4 Max Drawdown: {m['max_drawdown_pct']:.2f}%")

    # Opening gaps on entry in Fold 4
    gaps = []
    for t in trades:
        # Find signal bar close vs entry price
        # In trade record, entry_price is fill price
        pass

    # Exit reason breakdown
    exit_counts = {}
    for t in trades:
        reason = t.exit_reason.value if hasattr(t.exit_reason, "value") else str(t.exit_reason)
        exit_counts[reason] = exit_counts.get(reason, 0) + 1

    print("Fold 4 Exit Breakdown:", exit_counts)

    # Random entry baseline on Fold 4
    print("Running Real Random Entry Baseline on Fold 4...")
    random_res = run_real_random_entry_baseline(
        dataset=dataset,
        actual_trades=trades,
        runs=200,
        seed=42,
    )
    print(f"Fold 4 Random Entry Expectancy: p50={random_res['p50_expectancy_r']:+.3f} R, p95={random_res['p95_expectancy_r']:+.3f} R")

    out_data = {
        "fold_id": 4,
        "test_start": f4_start.isoformat(),
        "test_end": f4_end.isoformat(),
        "sessions_count": len(f4_dates),
        "bullish_sessions": bullish_sessions,
        "bearish_sessions": bearish_sessions,
        "bearish_pct": round(bearish_sessions / len(f4_dates) * 100.0, 1),
        "total_signals_generated": res_f4["total_signals_generated"],
        "total_signals_filled": res_f4["total_signals_filled"],
        "fill_rate_pct": res_f4["fill_rate_pct"],
        "metrics": m,
        "exit_breakdown": exit_counts,
        "random_baseline": random_res,
    }

    out_path = Path("data/fold4_investigation.json")
    out_path.write_text(json.dumps(out_data, indent=2, default=str), encoding="utf-8")
    print(f"Saved Fold 4 investigation to {out_path}")
    return out_data


if __name__ == "__main__":
    investigate_fold4()

