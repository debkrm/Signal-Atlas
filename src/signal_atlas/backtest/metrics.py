"""
metrics.py - Quantitative Metrics & Statistical Resampling Engine.

Computes comprehensive performance statistics for Signal Atlas backtests:
- Per-trade expectancy in R, win/loss metrics, profit factor, exit distributions.
- Portfolio equity dynamics: CAGR, Max Drawdown, Calmar, Sharpe, Exposure.
- Uncertainty estimation:
    * 10,000-iteration Bootstrap 95% Confidence Interval on Expectancy in R.
    * 10,000-iteration Monte Carlo trade order reshuffling for Max Drawdown distributions.
- Segmented breakdowns by year, regime, and symbol contributions.
"""

from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from signal_atlas.backtest.models import EquitySnapshot, ExitReason, PositionRecord


def calculate_comprehensive_metrics(
    trades: List[PositionRecord],
    equity_curve: List[EquitySnapshot],
    initial_capital: Decimal = Decimal("1000000.00"),
    annual_trading_sessions: int = 250,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Computes all standard, portfolio, bootstrap, and Monte Carlo metrics.
    """
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate_pct": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "total_fees_paid": 0.0,
            "net_pnl": 0.0,
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "profit_factor": 0.0,
            "expectancy_r": 0.0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "largest_loss_r": 0.0,
            "max_drawdown_pct": 0.0,
            "calmar_ratio": 0.0,
            "sharpe_ratio": 0.0,
            "exposure_time_pct": 0.0,
            "avg_holding_sessions": 0.0,
            "exit_breakdown": {},
            "gap_through_stop": {"count": 0, "avg_r": 0.0},
            "bootstrap_expectancy_ci_95": (0.0, 0.0),
            "monte_carlo": {"median_max_dd_pct": 0.0, "p95_max_dd_pct": 0.0, "p95_losing_streak": 0},
            "yearly_breakdown": {},
            "top_symbols": [],
        }

    # 1. Trade-level metrics
    wins = [t for t in trades if t.net_pnl > Decimal("0")]
    losses = [t for t in trades if t.net_pnl <= Decimal("0")]
    r_multiples = [float(t.realized_r_multiple) for t in trades]

    gross_profit = float(sum((t.gross_pnl for t in wins), Decimal("0.00")))
    gross_loss = float(abs(sum((t.gross_pnl for t in losses), Decimal("0.00"))))
    total_fees = float(sum((t.entry_fees + t.exit_fees for t in trades), Decimal("0.00")))
    net_pnl = float(sum((t.net_pnl for t in trades), Decimal("0.00")))

    win_rate = (len(wins) / total_trades) * 100.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 99.99

    r_wins = [float(t.realized_r_multiple) for t in wins]
    r_losses = [float(t.realized_r_multiple) for t in losses]

    avg_win_r = float(np.mean(r_wins)) if r_wins else 0.0
    avg_loss_r = float(np.mean(r_losses)) if r_losses else 0.0
    expectancy_r = float(np.mean(r_multiples))
    largest_loss_r = float(min(r_multiples)) if r_multiples else 0.0

    avg_holding = float(np.mean([t.holding_sessions_count for t in trades]))

    # Exit Breakdown
    exit_counts: Dict[str, int] = {}
    gap_stops: List[float] = []
    for t in trades:
        reason_str = t.exit_reason.value if hasattr(t.exit_reason, "value") else str(t.exit_reason)
        # Check if gap through stop occurred (exit price worse than initial stop loss)
        is_gap = (
            t.exit_reason == ExitReason.STOP_LOSS
            and t.exit_price < t.initial_stop_loss
        )
        if is_gap:
            reason_str = "GAP_THROUGH_STOP"
            gap_stops.append(float(t.realized_r_multiple))

        exit_counts[reason_str] = exit_counts.get(reason_str, 0) + 1

    exit_breakdown = {
        reason: {
            "count": cnt,
            "pct": round(cnt / total_trades * 100.0, 2),
        }
        for reason, cnt in exit_counts.items()
    }

    gap_through_stats = {
        "count": len(gap_stops),
        "pct": round(len(gap_stops) / total_trades * 100.0, 2),
        "avg_r": round(float(np.mean(gap_stops)), 2) if gap_stops else 0.0,
    }

    # 2. Portfolio-level metrics
    total_return_pct = (net_pnl / float(initial_capital)) * 100.0
    num_sessions = len(equity_curve)
    years = num_sessions / annual_trading_sessions if num_sessions > 0 else 1.0

    ending_equity = float(initial_capital) + net_pnl
    if ending_equity > 0 and years > 0:
        cagr_pct = ((ending_equity / float(initial_capital)) ** (1.0 / years) - 1.0) * 100.0
    else:
        cagr_pct = -100.0

    max_dd_pct = float(max((e.drawdown_pct for e in equity_curve), default=Decimal("0.00")))
    calmar = round(cagr_pct / max_dd_pct, 2) if max_dd_pct > 0 else 0.0

    # Daily Sharpe
    sharpe = 0.0
    if len(equity_curve) > 1:
        equities = np.array([float(e.total_equity) for e in equity_curve])
        daily_returns = np.diff(equities) / equities[:-1]
        std_ret = float(np.std(daily_returns))
        if std_ret > 1e-8:
            mean_ret = float(np.mean(daily_returns))
            sharpe = round((mean_ret / std_ret) * math.sqrt(annual_trading_sessions), 2)

    # Exposure
    invested_sessions = sum(1 for e in equity_curve if e.open_positions_count > 0)
    exposure_pct = round((invested_sessions / num_sessions * 100.0), 2) if num_sessions > 0 else 0.0

    # 3. Bootstrap 95% Confidence Interval on Expectancy
    rng = np.random.default_rng(seed)
    r_arr = np.array(r_multiples)
    bootstrap_means = rng.choice(r_arr, size=(10000, total_trades), replace=True).mean(axis=1)
    ci_lower = round(float(np.percentile(bootstrap_means, 2.5)), 3)
    ci_upper = round(float(np.percentile(bootstrap_means, 97.5)), 3)

    # 4. Monte Carlo Trade Order Reshuffling (10,000 iterations)
    # Assumes compounding position risk with historical realized net return / risk
    mc_drawdowns = np.empty(10000, dtype=np.float64)
    mc_losing_streaks = np.empty(10000, dtype=np.int32)

    trade_returns = np.array([float(t.net_pnl) for t in trades])
    # Approximate trade returns as percentage of equity or fixed risk
    trade_pct_returns = trade_returns / float(initial_capital)

    for i in range(10000):
        shuffled = rng.permutation(trade_pct_returns)
        cum_equity = 1.0 + np.cumsum(shuffled)
        peaks = np.maximum.accumulate(cum_equity)
        dds = (peaks - cum_equity) / peaks * 100.0
        mc_drawdowns[i] = np.max(dds) if len(dds) > 0 else 0.0

        # Longest losing streak
        losses_bool = shuffled <= 0.0
        max_streak = 0
        curr_streak = 0
        for is_loss in losses_bool:
            if is_loss:
                curr_streak += 1
                if curr_streak > max_streak:
                    max_streak = curr_streak
            else:
                curr_streak = 0
        mc_losing_streaks[i] = max_streak

    mc_median_dd = round(float(np.median(mc_drawdowns)), 2)
    mc_p95_dd = round(float(np.percentile(mc_drawdowns, 95.0)), 2)
    mc_p95_streak = int(np.percentile(mc_losing_streaks, 95.0))

    # 5. Yearly Breakdown
    yearly: Dict[int, Dict[str, Any]] = {}
    for t in trades:
        yr = t.exit_date.year
        if yr not in yearly:
            yearly[yr] = {"trades": 0, "wins": 0, "pnl": Decimal("0.00"), "r_list": []}
        yearly[yr]["trades"] += 1
        if t.net_pnl > Decimal("0"):
            yearly[yr]["wins"] += 1
        yearly[yr]["pnl"] += t.net_pnl
        yearly[yr]["r_list"].append(float(t.realized_r_multiple))

    yearly_breakdown = {}
    for yr, data in sorted(yearly.items()):
        cnt = data["trades"]
        yearly_breakdown[yr] = {
            "trades": cnt,
            "win_rate_pct": round(data["wins"] / cnt * 100.0, 2) if cnt > 0 else 0.0,
            "net_pnl": round(float(data["pnl"]), 2),
            "expectancy_r": round(float(np.mean(data["r_list"])), 2) if data["r_list"] else 0.0,
        }

    # 6. Top Symbol Contributions
    symbols_pnl: Dict[str, Dict[str, Any]] = {}
    for t in trades:
        sym = t.symbol
        if sym not in symbols_pnl:
            symbols_pnl[sym] = {"trades": 0, "wins": 0, "net_pnl": Decimal("0.00"), "total_r": 0.0}
        symbols_pnl[sym]["trades"] += 1
        if t.net_pnl > Decimal("0"):
            symbols_pnl[sym]["wins"] += 1
        symbols_pnl[sym]["net_pnl"] += t.net_pnl
        symbols_pnl[sym]["total_r"] += float(t.realized_r_multiple)

    sorted_syms = sorted(symbols_pnl.items(), key=lambda x: x[1]["net_pnl"], reverse=True)
    top_symbols = [
        {
            "symbol": sym,
            "trades": d["trades"],
            "win_rate_pct": round(d["wins"] / d["trades"] * 100.0, 1),
            "net_pnl": round(float(d["net_pnl"]), 2),
            "total_r": round(d["total_r"], 2),
        }
        for sym, d in sorted_syms[:10]
    ]

    return {
        "total_trades": total_trades,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_pct": round(win_rate, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "total_fees_paid": round(total_fees, 2),
        "costs_as_pct_gross_profit": round(total_fees / gross_profit * 100.0, 2) if gross_profit > 0 else 0.0,
        "net_pnl": round(net_pnl, 2),
        "total_return_pct": round(total_return_pct, 2),
        "cagr_pct": round(cagr_pct, 2),
        "profit_factor": round(profit_factor, 2),
        "expectancy_r": round(expectancy_r, 3),
        "avg_win_r": round(avg_win_r, 2),
        "avg_loss_r": round(avg_loss_r, 2),
        "largest_loss_r": round(largest_loss_r, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "calmar_ratio": calmar,
        "sharpe_ratio": sharpe,
        "exposure_time_pct": exposure_pct,
        "avg_holding_sessions": round(avg_holding, 1),
        "exit_breakdown": exit_breakdown,
        "gap_through_stop": gap_through_stats,
        "bootstrap_expectancy_ci_95": (ci_lower, ci_upper),
        "monte_carlo": {
            "median_max_dd_pct": mc_median_dd,
            "p95_max_dd_pct": mc_p95_dd,
            "p95_losing_streak": mc_p95_streak,
        },
        "yearly_breakdown": yearly_breakdown,
        "top_symbols": top_symbols,
    }
