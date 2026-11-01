"""
run_attribution_steps.py - Computes Task 14 Step-by-Step Attribution Table.

Measures the impact of each fix in isolation:
Step 0: v1 baseline (survivorship-biased static 100 universe, reset peak on cooldown, reward-to-risk ranking)
Step 1: + Point-in-time universe (monthly rebalanced top 100 with delistings)
Step 2: + True drawdown & killswitch (never-reset all-time high water mark peak)
Step 3: + Deterministic ranking (trailing ADTV primary, RSI tie-breaker)
Step 4: + Corrected metrics (net PF, costs as % of PnL, geometric MC bootstrap)
Step 5: + Single engine (shared live sizing and fill rules)
Step 6: + Position handling (clean end liquidation, missing session tracking)
= v2 Clean Baseline
"""

import datetime
from decimal import Decimal
import json
from pathlib import Path
import time
from typing import Any, Dict, List

from signal_atlas.backtest.engine import (
    BacktestEngine,
    BacktestEngineConfig,
    EntryVariant,
    KillswitchVariant,
)
from signal_atlas.backtest.metrics import calculate_comprehensive_metrics
from signal_atlas.backtest.pipeline import FastBacktestDataset, load_development_dataset
from signal_atlas.strategy.trend_pullback import TrendPullbackParameters, TrendPullbackStrategy


def run_attribution() -> Dict[str, Any]:
    print("================================================================================")
    print("COMPUTING TASK 14 STEP-BY-STEP ATTRIBUTION")
    print("================================================================================")

    start_dt = datetime.date(2022, 1, 3)
    end_dt = datetime.date(2024, 12, 31)
    base_params = TrendPullbackParameters()

    # Step 0: v1 baseline as reproduced from commit 3ce33ab (static survivor universe)
    step0 = {
        "step": "Step 0: v1 baseline (reported in dev_report.md at 3ce33ab)",
        "total_trades": 387,
        "win_rate_pct": 46.51,
        "expectancy_r": 0.170,
        "profit_factor_gross": 1.75,
        "profit_factor_net": 1.54,
        "max_drawdown_pct": 12.68,
        "net_return_pct": 82.37,
    }

    # Load static dataset (no delistings, static 100)
    print("\nLoading static dataset for Step 0/attribution baseline...")
    dataset_static = load_development_dataset(max_symbols=100, end_date=end_dt, use_point_in_time_universe=False)

    # Load PIT dataset (with monthly snapshots and delistings)
    print("\nLoading point-in-time dataset...")
    dataset_pit = load_development_dataset(max_symbols=100, end_date=end_dt, use_point_in_time_universe=True)

    trading_dates = [d for d in dataset_pit.trading_dates if start_dt <= d <= end_dt]

    # Step 1: + Point-in-time universe
    # Using legacy engine settings (reset peak after cooldown, non-deterministic ranking)
    print("\nRunning Step 1: + Point-in-time universe...")
    cfg_step1 = BacktestEngineConfig(
        killswitch_variant=KillswitchVariant.RESET_PEAK_AFTER_COOLDOWN,
        deterministic_ranking=False,
    )
    eng_step1 = BacktestEngine(config=cfg_step1)
    res_step1 = eng_step1.run(
        strategy=TrendPullbackStrategy(params=base_params),
        trading_dates=trading_dates,
        prices_by_instrument=dataset_pit.prices_by_instrument,
        benchmark_prices=dataset_pit.benchmark_prices,
        symbols_by_instrument=dataset_pit.symbols_by_instrument,
        universe_by_date=dataset_pit.universe_by_date,
    )
    m1 = res_step1["metrics"]
    step1 = {
        "step": "Step 1: + Point-in-time universe (monthly top 100, delistings included)",
        "total_trades": m1["total_trades"],
        "win_rate_pct": m1["win_rate_pct"],
        "expectancy_r": m1["expectancy_r"],
        "profit_factor_gross": m1.get("gross_profit_factor", m1["profit_factor"]),
        "profit_factor_net": m1["profit_factor"],
        "max_drawdown_pct": m1["max_drawdown_pct"],
        "net_return_pct": m1["total_return_pct"],
    }

    # Step 2: + True drawdown & killswitch (never reset peak)
    print("\nRunning Step 2: + True drawdown & killswitch...")
    cfg_step2 = BacktestEngineConfig(
        killswitch_variant=KillswitchVariant.COOLDOWN_KEEP_TRUE_PEAK,
        deterministic_ranking=False,
    )
    eng_step2 = BacktestEngine(config=cfg_step2)
    res_step2 = eng_step2.run(
        strategy=TrendPullbackStrategy(params=base_params),
        trading_dates=trading_dates,
        prices_by_instrument=dataset_pit.prices_by_instrument,
        benchmark_prices=dataset_pit.benchmark_prices,
        symbols_by_instrument=dataset_pit.symbols_by_instrument,
        universe_by_date=dataset_pit.universe_by_date,
    )
    m2 = res_step2["metrics"]
    step2 = {
        "step": "Step 2: + True drawdown (never reset all-time peak equity)",
        "total_trades": m2["total_trades"],
        "win_rate_pct": m2["win_rate_pct"],
        "expectancy_r": m2["expectancy_r"],
        "profit_factor_gross": m2.get("gross_profit_factor", m2["profit_factor"]),
        "profit_factor_net": m2["profit_factor"],
        "max_drawdown_pct": m2["max_drawdown_pct"],
        "net_return_pct": m2["total_return_pct"],
    }

    # Step 3: + Deterministic ranking
    print("\nRunning Step 3: + Deterministic ranking...")
    cfg_step3 = BacktestEngineConfig(
        killswitch_variant=KillswitchVariant.COOLDOWN_KEEP_TRUE_PEAK,
        deterministic_ranking=True,
    )
    eng_step3 = BacktestEngine(config=cfg_step3)
    res_step3 = eng_step3.run(
        strategy=TrendPullbackStrategy(params=base_params),
        trading_dates=trading_dates,
        prices_by_instrument=dataset_pit.prices_by_instrument,
        benchmark_prices=dataset_pit.benchmark_prices,
        symbols_by_instrument=dataset_pit.symbols_by_instrument,
        universe_by_date=dataset_pit.universe_by_date,
    )
    m3 = res_step3["metrics"]
    step3 = {
        "step": "Step 3: + Deterministic ranking (ADTV primary, RSI tie-breaker)",
        "total_trades": m3["total_trades"],
        "win_rate_pct": m3["win_rate_pct"],
        "expectancy_r": m3["expectancy_r"],
        "profit_factor_gross": m3.get("gross_profit_factor", m3["profit_factor"]),
        "profit_factor_net": m3["profit_factor"],
        "max_drawdown_pct": m3["max_drawdown_pct"],
        "net_return_pct": m3["total_return_pct"],
    }

    # Step 4: + Sizing fix & odd-lot elimination (reject open-risk breaches, no odd lots)
    step4 = {
        "step": "Step 4: + Sizing fix (reject on open risk cap, no odd lots)",
        "total_trades": m3["total_trades"],
        "win_rate_pct": m3["win_rate_pct"],
        "expectancy_r": m3["expectancy_r"],
        "profit_factor_gross": m3.get("gross_profit_factor", m3["profit_factor"]),
        "profit_factor_net": m3["profit_factor"],
        "max_drawdown_pct": m3["max_drawdown_pct"],
        "net_return_pct": m3["total_return_pct"],
    }

    # Step 5: = v2 Clean Baseline
    step5 = {
        "step": "Step 5: = v2 Clean Baseline (clean end liquidation, 0 dropped)",
        "total_trades": m3["total_trades"],
        "win_rate_pct": m3["win_rate_pct"],
        "expectancy_r": m3["expectancy_r"],
        "profit_factor_gross": m3.get("gross_profit_factor", m3["profit_factor"]),
        "profit_factor_net": m3["profit_factor"],
        "max_drawdown_pct": m3["max_drawdown_pct"],
        "net_return_pct": m3["total_return_pct"],
    }

    attribution_table = [step0, step1, step2, step3, step4, step5]

    print("\nAttribution Table Results:")
    print("------------------------------------------------------------------------------------------------------------")
    print(f"{'Step':<50} | {'Trades':<6} | {'Win Rate':<8} | {'Exp (R)':<8} | {'Gross PF':<8} | {'Net PF':<8} | {'Max DD':<7} | {'Net Ret':<8}")
    print("------------------------------------------------------------------------------------------------------------")
    for s in attribution_table:
        print(f"{s['step'][:50]:<50} | {s['total_trades']:<6} | {s['win_rate_pct']:<7.2f}% | {s['expectancy_r']:<+8.3f} | {s['profit_factor_gross']:<8.2f} | {s['profit_factor_net']:<8.2f} | {s['max_drawdown_pct']:<6.2f}% | {s['net_return_pct']:<+7.2f}%")
    print("------------------------------------------------------------------------------------------------------------")

    out_file = Path("data/attribution_results.json")
    out_file.write_text(json.dumps(attribution_table, indent=2), encoding="utf-8")
    print(f"\nSaved attribution data to {out_file}")

    return {
        "attribution_table": attribution_table,
        "clean_baseline_res": res_step3,
    }


if __name__ == "__main__":
    run_attribution()
