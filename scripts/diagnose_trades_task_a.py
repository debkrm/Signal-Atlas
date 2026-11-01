"""
diagnose_trades_task_a.py - Task A: Trade-Level Export & Metric Reconciliation

Exports all v2 baseline trades to CSV:
symbol, entry_date, exit_date, entry_price, exit_price, quantity,
stop_loss, target_price, atr_pct, stop_distance_pct, rupee_risk,
rupee_risk_pct_equity, gross_pnl, costs_rupees, costs_r, net_pnl,
realized_r, exit_reason.

Performs and prints:
1. Sum(net_pnl) / Sum(realized_r)
2. Mean rupee risk per trade vs intended 1% of equity (Rs 10,000)
3. Average win, average loss, win rate, and payoff in both R and rupees
4. Verification: win% * avg_win_R - loss% * avg_loss_R == reported expectancy
5. Distribution of stop distance %, position value, and rupee risk (flagging anomalies)
6. Top 10 trades by absolute R
7. Full reconciliation between rupee P&L and R-multiples
"""

import csv
import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import sys
import numpy as np

from signal_atlas.backtest.engine import EntryVariant
from signal_atlas.backtest.pipeline import FastSimulationRunner, load_development_dataset
from signal_atlas.strategy.trend_pullback import TrendPullbackParameters

def run_diagnostics():
    print("=" * 80)
    print("TASK A: TRADE-LEVEL EXPORT & RECONCILIATION DIAGNOSTIC")
    print("=" * 80)

    dataset = load_development_dataset(end_date=datetime.date(2024, 12, 31), use_point_in_time_universe=True)
    runner = FastSimulationRunner(dataset)

    start_dt = datetime.date(2022, 1, 3)
    end_dt = datetime.date(2024, 12, 31)
    params = TrendPullbackParameters()

    print("\nRunning clean baseline simulation...")
    res = runner.run(
        params=params,
        start_date=start_dt,
        end_date=end_dt,
        entry_variant=EntryVariant.A,
        ignore_regime=False,
    )

    trades = res["trades"]
    metrics = res["metrics"]
    print(f"Total trades: {len(trades)}")
    print(f"Reported Expectancy (R): {metrics['expectancy_r']:+.4f} R")
    print(f"Reported Net P&L: Rs. {metrics['net_pnl']:,.2f}")
    print(f"Reported Net Return: {metrics['total_return_pct']:.2f}%")
    print(f"Reported Net Profit Factor: {metrics['net_profit_factor']:.2f}")

    # Export to CSV
    csv_path = Path("reports/v2_baseline_trades.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    initial_cap = Decimal("1000000.00")

    for t in trades:
        entry_p = t.entry_price
        exit_p = t.exit_price
        qty = t.quantity
        stop_p = t.initial_stop_loss
        target_p = t.initial_target_price
        risk_per_sh = t.initial_risk_per_share
        
        # Stop distance %
        stop_dist_pct = float((entry_p - stop_p) / entry_p * 100) if entry_p > 0 else 0.0
        
        # Rupee risk planned
        rupee_risk = float(risk_per_sh * Decimal(qty))
        rupee_risk_pct_equity = (rupee_risk / float(initial_cap)) * 100.0

        # Costs
        total_costs = float(t.entry_fees + t.exit_fees)
        costs_r = float(Decimal(str(total_costs)) / (risk_per_sh * Decimal(qty))) if (risk_per_sh * Decimal(qty)) > 0 else 0.0

        row = {
            "trade_id": t.trade_id,
            "symbol": t.symbol,
            "instrument_id": t.instrument_id,
            "entry_date": t.entry_date.isoformat(),
            "exit_date": t.exit_date.isoformat(),
            "entry_price": float(entry_p),
            "exit_price": float(exit_p),
            "quantity": qty,
            "position_value": float(entry_p * Decimal(qty)),
            "stop_loss": float(stop_p),
            "target_price": float(target_p),
            "stop_distance_pct": round(stop_dist_pct, 2),
            "initial_risk_per_share": float(risk_per_sh),
            "rupee_risk": round(rupee_risk, 2),
            "rupee_risk_pct_equity": round(rupee_risk_pct_equity, 3),
            "gross_pnl": float(t.gross_pnl),
            "costs_rupees": round(total_costs, 2),
            "costs_r": round(costs_r, 4),
            "net_pnl": float(t.net_pnl),
            "realized_r": float(t.realized_r_multiple),
            "net_return_pct": float(t.net_return_pct) * 100.0,
            "holding_sessions": t.holding_sessions_count,
            "exit_reason": t.exit_reason.value if hasattr(t.exit_reason, "value") else str(t.exit_reason),
        }
        rows.append(row)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n[OK] Exported {len(rows)} trades to {csv_path}")

    # -------------------------------------------------------------------------
    # ANALYSIS & RECONCILIATION
    # -------------------------------------------------------------------------
    r_list = [r["realized_r"] for r in rows]
    pnl_list = [r["net_pnl"] for r in rows]
    risk_list = [r["rupee_risk"] for r in rows]
    pos_val_list = [r["position_value"] for r in rows]
    stop_dist_list = [r["stop_distance_pct"] for r in rows]

    sum_pnl = sum(pnl_list)
    sum_r = sum(r_list)
    mean_rupee_risk = np.mean(risk_list)
    implied_rupee_per_r = sum_pnl / sum_r if sum_r != 0 else 0.0

    print("\n--- 1. OVERALL RECONCILIATION METRICS ---")
    print(f"Sum of Net P&L (Rupees) : Rs. {sum_pnl:,.2f}")
    print(f"Sum of Realized R       : {sum_r:+.3f} R")
    print(f"Sum(Net P&L) / Sum(R)   : Rs. {implied_rupee_per_r:,.2f} per 1.0 R")
    print(f"Mean Planned Rupee Risk : Rs. {mean_rupee_risk:,.2f} (Intended: Rs. 10,000.00 / 1% equity)")
    print(f"Mean Net P&L per Trade  : Rs. {np.mean(pnl_list):,.2f}")
    print(f"Mean Realized R per Trd : {np.mean(r_list):+.4f} R")

    # Wins vs Losses breakdown
    wins_r = [r["realized_r"] for r in rows if r["net_pnl"] > 0]
    losses_r = [r["realized_r"] for r in rows if r["net_pnl"] <= 0]
    wins_pnl = [r["net_pnl"] for r in rows if r["net_pnl"] > 0]
    losses_pnl = [r["net_pnl"] for r in rows if r["net_pnl"] <= 0]

    n_wins = len(wins_r)
    n_losses = len(losses_r)
    win_rate = n_wins / len(rows)
    loss_rate = n_losses / len(rows)

    avg_win_r = np.mean(wins_r) if wins_r else 0.0
    avg_loss_r = np.mean(losses_r) if losses_r else 0.0
    avg_win_pnl = np.mean(wins_pnl) if wins_pnl else 0.0
    avg_loss_pnl = np.mean(losses_pnl) if losses_pnl else 0.0

    payoff_r = abs(avg_win_r / avg_loss_r) if avg_loss_r != 0 else 0.0
    payoff_pnl = abs(avg_win_pnl / avg_loss_pnl) if avg_loss_pnl != 0 else 0.0

    formula_exp_r = (win_rate * avg_win_r) + (loss_rate * avg_loss_r) # note losses are negative

    print("\n--- 2. WINS, LOSSES & PAYOFFS ---")
    print(f"Win Count: {n_wins} ({win_rate*100:.2f}%) | Loss Count: {n_losses} ({loss_rate*100:.2f}%)")
    print(f"In R Multiples:")
    print(f"  * Avg Win (R)   : {avg_win_r:+.3f} R")
    print(f"  * Avg Loss (R)  : {avg_loss_r:+.3f} R")
    print(f"  * Payoff Ratio  : {payoff_r:.2f}")
    print(f"  * Formula Exp(R): {formula_exp_r:+.4f} R  [Mean R: {np.mean(r_list):+.4f} R]")
    print(f"In Rupees:")
    print(f"  * Avg Win (Rs)  : Rs. {avg_win_pnl:,.2f}")
    print(f"  * Avg Loss (Rs) : Rs. {avg_loss_pnl:,.2f}")
    print(f"  * Payoff Ratio  : {payoff_pnl:.2f}")
    print(f"  * Mean PnL (Rs) : Rs. {np.mean(pnl_list):,.2f}")

    print("\n--- 3. DISTRIBUTIONS & ANOMALY DETECTION ---")
    print(f"Stop Distance %:")
    print(f"  * Min: {np.min(stop_dist_list):.2f}% | p25: {np.percentile(stop_dist_list, 25):.2f}% | Med: {np.median(stop_dist_list):.2f}% | p75: {np.percentile(stop_dist_list, 75):.2f}% | Max: {np.max(stop_dist_list):.2f}%")
    print(f"Rupee Risk (per trade):")
    print(f"  * Min: Rs. {np.min(risk_list):,.2f} | Med: Rs. {np.median(risk_list):,.2f} | Max: Rs. {np.max(risk_list):,.2f}")
    print(f"Position Value:")
    print(f"  * Min: Rs. {np.min(pos_val_list):,.2f} | Med: Rs. {np.median(pos_val_list):,.2f} | Max: Rs. {np.max(pos_val_list):,.2f}")

    # Flag anomalies
    tiny_stops = [r for r in rows if r["stop_distance_pct"] < 1.0]
    tiny_risk = [r for r in rows if r["rupee_risk"] < 1000.0]
    large_r = [r for r in rows if abs(r["realized_r"]) > 3.0]

    print(f"\nAnomalies Flagged:")
    print(f"  * Trades with Stop Distance < 1.0%: {len(tiny_stops)}")
    for tr in tiny_stops[:5]:
        print(f"    - {tr['symbol']} on {tr['entry_date']}: Entry={tr['entry_price']}, Stop={tr['stop_loss']}, Dist={tr['stop_distance_pct']}%, Qty={tr['quantity']}, Risk=Rs.{tr['rupee_risk']}, R={tr['realized_r']}")

    print(f"  * Trades with Rupee Risk < Rs. 1,000 (10% of intended Rs 10k): {len(tiny_risk)}")
    for tr in tiny_risk[:5]:
        print(f"    - {tr['symbol']} on {tr['entry_date']}: Risk=Rs.{tr['rupee_risk']} ({tr['rupee_risk_pct_equity']:.2f}% eq), PosVal=Rs.{tr['position_value']:.2f}, Qty={tr['quantity']}, R={tr['realized_r']}")

    print(f"  * Trades with |Realized R| > 3.0: {len(large_r)}")

    print("\n--- 4. TOP 10 TRADES BY ABSOLUTE R ---")
    sorted_by_abs_r = sorted(rows, key=lambda x: abs(x["realized_r"]), reverse=True)
    for i, tr in enumerate(sorted_by_abs_r[:10], 1):
        print(f"  {i:2d}. {tr['symbol']:<12} Entry:{tr['entry_date']} Exit:{tr['exit_date']} | R={tr['realized_r']:+6.2f} R | Net PnL: Rs. {tr['net_pnl']:+9.2f} | Risk: Rs. {tr['rupee_risk']:7.2f} | Exit: {tr['exit_reason']}")

    # Save summary json
    diag_summary = {
        "total_trades": len(rows),
        "sum_net_pnl": float(sum_pnl),
        "sum_realized_r": float(sum_r),
        "implied_rupee_per_r": float(implied_rupee_per_r),
        "mean_rupee_risk": float(mean_rupee_risk),
        "mean_net_pnl": float(np.mean(pnl_list)),
        "mean_realized_r": float(np.mean(r_list)),
        "win_rate_pct": float(win_rate * 100),
        "avg_win_r": float(avg_win_r),
        "avg_loss_r": float(avg_loss_r),
        "avg_win_pnl": float(avg_win_pnl),
        "avg_loss_pnl": float(avg_loss_pnl),
        "payoff_r": float(payoff_r),
        "payoff_pnl": float(payoff_pnl),
        "stop_distance_stats": {
            "min": float(np.min(stop_dist_list)),
            "p25": float(np.percentile(stop_dist_list, 25)),
            "median": float(np.median(stop_dist_list)),
            "p75": float(np.percentile(stop_dist_list, 75)),
            "max": float(np.max(stop_dist_list)),
        },
        "tiny_stops_count": len(tiny_stops),
        "tiny_risk_count": len(tiny_risk),
        "top_10_abs_r": sorted_by_abs_r[:10],
    }
    Path("reports/v2_trade_diagnostics.json").write_text(json.dumps(diag_summary, indent=2, default=str), encoding="utf-8")
    print(f"\n[OK] Saved diagnostic summary to reports/v2_trade_diagnostics.json")

if __name__ == "__main__":
    run_diagnostics()

