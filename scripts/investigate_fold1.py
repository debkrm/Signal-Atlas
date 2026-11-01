"""
investigate_fold1.py - Task D: Fold 1 Deep-Dive & Comparison (2023-01-02 to 2023-06-30)

Compares v1 and v2 for Fold 1 test window:
1. Benchmark (NIFTYBEES) performance, regime distribution (Bullish vs Bearish sessions).
2. Universe size per month.
3. Daily signals generated vs filled.
4. Detailed analysis of the 24 trades (entries, exits, holding, stop vs target).
5. Equal-weight universe buy-and-hold return for 2023-H1.
6. Explanation of the 8.33% win rate.
"""

import datetime
from decimal import Decimal
import json
from pathlib import Path
import numpy as np

from signal_atlas.backtest.engine import BacktestEngine, BacktestEngineConfig, EntryVariant
from signal_atlas.backtest.pipeline import FastSimulationRunner, load_development_dataset
from signal_atlas.strategy.trend_pullback import TrendPullbackParameters

def investigate():
    print("=" * 80)
    print("TASK D: FOLD 1 INVESTIGATION (2023-01-02 to 2023-06-30)")
    print("=" * 80)

    f1_start = datetime.date(2023, 1, 2)
    f1_end = datetime.date(2023, 6, 30)

    # 1. Load PIT dataset
    dataset_pit = load_development_dataset(end_date=f1_end, use_point_in_time_universe=True)
    runner_pit = FastSimulationRunner(dataset_pit)

    # 2. Benchmark NIFTYBEES in Fold 1
    bench_recs = [b for b in dataset_pit.benchmark_prices if f1_start <= b.trade_date <= f1_end]
    bench_closes = [float(b.close) for b in bench_recs]
    bench_start = bench_closes[0]
    bench_end = bench_closes[-1]
    bench_ret = (bench_end - bench_start) / bench_start * 100.0

    # Benchmark regime distribution
    bullish_sessions = 0
    bearish_sessions = 0
    for b in bench_recs:
        ema50 = dataset_pit.bench_ema_by_date.get(b.trade_date)
        if ema50 and b.close > ema50:
            bullish_sessions += 1
        else:
            bearish_sessions += 1

    total_sessions = len(bench_recs)
    print(f"\n--- 1. BENCHMARK & REGIME (2023-H1) ---")
    print(f"Total Trading Sessions : {total_sessions}")
    print(f"NIFTYBEES Start Price  : Rs. {bench_start:.2f} (2023-01-02)")
    print(f"NIFTYBEES End Price    : Rs. {bench_end:.2f} (2023-06-30)")
    print(f"NIFTYBEES Return (H1)  : {bench_ret:+.2f}%")
    print(f"Bullish Sessions (Gate): {bullish_sessions} ({bullish_sessions/total_sessions*100:.1f}%)")
    print(f"Bearish Sessions (Gate): {bearish_sessions} ({bearish_sessions/total_sessions*100:.1f}%)")

    # Quarterly split of NIFTYBEES
    q1_recs = [b for b in bench_recs if b.trade_date <= datetime.date(2023, 3, 31)]
    q2_recs = [b for b in bench_recs if b.trade_date > datetime.date(2023, 3, 31)]
    q1_ret = (float(q1_recs[-1].close) - float(q1_recs[0].close)) / float(q1_recs[0].close) * 100.0
    q2_ret = (float(q2_recs[-1].close) - float(q2_recs[0].close)) / float(q2_recs[0].close) * 100.0
    print(f"  * Q1 2023 (Jan-Mar) NIFTYBEES Return: {q1_ret:+.2f}% (Correction & Chop)")
    print(f"  * Q2 2023 (Apr-Jun) NIFTYBEES Return: {q2_ret:+.2f}% (Rally)")

    # 3. Universe size per month in Fold 1
    print(f"\n--- 2. UNIVERSE SIZE PER MONTH (PIT) ---")
    monthly_rebals = sorted(set(dataset_pit.universe_by_date.keys()))
    f1_rebals = [d for d in monthly_rebals if f1_start <= d <= f1_end]
    for d in f1_rebals:
        members = dataset_pit.universe_by_date[d]
        print(f"  {d.isoformat()}: {len(members)} members")

    # 4. Run baseline on Fold 1
    res_f1 = runner_pit.run(
        params=TrendPullbackParameters(),
        start_date=f1_start,
        end_date=f1_end,
        entry_variant=EntryVariant.A,
    )
    trades_f1 = res_f1["trades"]
    m_f1 = res_f1["metrics"]

    print(f"\n--- 3. FOLD 1 SIMULATION RESULTS ---")
    print(f"Total Signals Generated: {res_f1.get('total_signals_generated')}")
    print(f"Total Signals Filled   : {res_f1.get('total_signals_filled')}")
    print(f"Total Completed Trades : {len(trades_f1)}")
    print(f"Win Count / Loss Count : {m_f1['winning_trades']} / {m_f1['losing_trades']} (Win Rate: {m_f1['win_rate_pct']:.2f}%)")
    print(f"Expectancy (R)         : {m_f1['expectancy_r']:+.3f} R")
    print(f"Net P&L (Rupees)       : Rs. {m_f1['net_pnl']:,.2f}")
    print(f"Net Return             : {m_f1['total_return_pct']:.2f}%")
    print(f"Max Drawdown           : {m_f1['max_drawdown_pct']:.2f}%")

    # Exit reason breakdown
    print(f"\nExit Reasons in Fold 1:")
    for reason, stats in m_f1["exit_breakdown"].items():
        print(f"  * {reason}: {stats['count']} trades ({stats['pct']:.1f}%)")

    # Print all 24 trades
    print(f"\nAll {len(trades_f1)} Trades in Fold 1:")
    print(f"{'#':<3} {'Symbol':<12} {'Entry Date':<11} {'Exit Date':<11} {'Entry P':<8} {'Exit P':<8} {'Qty':<5} {'Risk (Rs)':<9} {'PnL (Rs)':<10} {'R':<7} {'Exit Reason'}")
    print("-" * 95)
    for i, t in enumerate(trades_f1, 1):
        risk = float(t.initial_risk_per_share * Decimal(t.quantity))
        print(f"{i:<3} {t.symbol:<12} {t.entry_date.isoformat():<11} {t.exit_date.isoformat():<11} {float(t.entry_price):<8.2f} {float(t.exit_price):<8.2f} {t.quantity:<5} {risk:<9.2f} {float(t.net_pnl):<+10.2f} {float(t.realized_r_multiple):<+7.2f} {t.exit_reason.value if hasattr(t.exit_reason, 'value') else t.exit_reason}")

    # 5. Equal-Weight Buy & Hold in Fold 1
    from signal_atlas.backtest.robustness import run_buy_and_hold_equal_weight_baseline
    eq_f1 = run_buy_and_hold_equal_weight_baseline(dataset_pit, f1_start, f1_end)
    print(f"\n--- 4. EQUAL-WEIGHT UNIVERSE BUY-AND-HOLD (Fold 1) ---")
    print(f"Equal-Weight Universe Return: {eq_f1['total_return_pct']:+.2f}% (Max DD: {eq_f1['max_drawdown_pct']:.2f}%)")

    # Save results to data/fold1_investigation.json
    f1_summary = {
        "dates": f"{f1_start} to {f1_end}",
        "total_sessions": total_sessions,
        "niftybees_return_pct": bench_ret,
        "q1_return_pct": q1_ret,
        "q2_return_pct": q2_ret,
        "bullish_sessions": bullish_sessions,
        "bearish_sessions": bearish_sessions,
        "total_trades": len(trades_f1),
        "win_rate_pct": m_f1["win_rate_pct"],
        "expectancy_r": m_f1["expectancy_r"],
        "net_pnl": float(m_f1["net_pnl"]),
        "net_return_pct": m_f1["total_return_pct"],
        "max_drawdown_pct": m_f1["max_drawdown_pct"],
        "exit_breakdown": m_f1["exit_breakdown"],
        "equal_weight_universe_return_pct": eq_f1["total_return_pct"],
    }
    Path("data/fold1_investigation.json").write_text(json.dumps(f1_summary, indent=2), encoding="utf-8")
    print(f"\n[OK] Saved Fold 1 investigation to data/fold1_investigation.json")

if __name__ == "__main__":
    investigate()

