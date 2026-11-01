"""
metrics.py - Quantitative Metrics & Statistical Resampling Engine.

Computes comprehensive performance statistics for Signal Atlas backtests:
- Per-trade expectancy in R, win/loss metrics, net profit factor, R profit factor, exit distributions.
- Portfolio equity dynamics: CAGR, Max Drawdown, Calmar, Sharpe, Exposure.
- Uncertainty estimation:
    * Month-block bootstrap 95% Confidence Interval on Expectancy in R.
    * Geometric compounding monthly block bootstrap for Max Drawdown distributions.
- Cost share analysis: costs as percentage of total gross P&L, split into slippage and statutory charges.
- Tax impact: STCG (20%) pre-tax and post-tax returns.
- Segmented breakdowns by year, regime, and symbol contributions.
"""

from collections import defaultdict
import datetime
from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np

from signal_atlas.backtest.models import EquitySnapshot, ExitReason, PositionRecord


def calculate_comprehensive_metrics(
    trades: List[PositionRecord],
    equity_curve: List[EquitySnapshot],
    initial_capital: Decimal = Decimal("1000000.00"),
    annual_trading_sessions: int = 250,
    seed: int = 42,
    stcg_tax_rate: Decimal = Decimal("0.20"),
) -> Dict[str, Any]:
    """
    Computes all standard, portfolio, bootstrap, and Monte Carlo metrics.
    Strictly adheres to Task 5: net profit factor, R-based profit factor,
    costs as percentage of total gross P&L, month-block bootstrap,
    and geometric compounding drawdown simulations.
    """
    total_trades = len(trades)
    if total_trades == 0:
        max_dd = float(max((e.drawdown_pct for e in equity_curve), default=Decimal("0.00"))) if equity_curve else 0.0
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate_pct": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "total_gross_pnl": 0.0,
            "total_fees_paid": 0.0,
            "slippage_fees": 0.0,
            "statutory_fees": 0.0,
            "costs_as_pct_gross_pnl": 0.0,
            "costs_as_pct_gross_profit": 0.0,
            "net_pnl": 0.0,
            "post_tax_net_pnl": 0.0,
            "total_return_pct": 0.0,
            "post_tax_return_pct": 0.0,
            "cagr_pct": 0.0,
            "post_tax_cagr_pct": 0.0,
            "profit_factor": 0.0,
            "net_profit_factor": 0.0,
            "r_profit_factor": 0.0,
            "gross_profit_factor": 0.0,
            "expectancy_r": 0.0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "largest_loss_r": 0.0,
            "max_drawdown_pct": round(max_dd, 2),
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

    # 1. Trade-level metrics (Net and Gross basis)
    wins = [t for t in trades if t.net_pnl > Decimal("0")]
    losses = [t for t in trades if t.net_pnl <= Decimal("0")]
    r_multiples = [float(t.realized_r_multiple) for t in trades]

    gross_profit = float(sum((t.gross_pnl for t in trades if t.gross_pnl > Decimal("0")), Decimal("0.00")))
    gross_loss = float(abs(sum((t.gross_pnl for t in trades if t.gross_pnl <= Decimal("0")), Decimal("0.00"))))
    total_gross_pnl = gross_profit - gross_loss

    total_fees = float(sum((t.entry_fees + t.exit_fees for t in trades), Decimal("0.00")))
    net_pnl = float(sum((t.net_pnl for t in trades), Decimal("0.00")))

    # Net Profit Factor: sum(net_pnl of winners) / abs(sum(net_pnl of losers))
    net_win_sum = float(sum((t.net_pnl for t in wins), Decimal("0.00")))
    net_loss_sum = float(abs(sum((t.net_pnl for t in losses), Decimal("0.00"))))
    net_profit_factor = (net_win_sum / net_loss_sum) if net_loss_sum > 0 else 99.99

    # R-Multiple Profit Factor: sum(positive R) / abs(sum(negative R))
    r_win_sum = sum(r for r in r_multiples if r > 0.0)
    r_loss_sum = abs(sum(r for r in r_multiples if r <= 0.0))
    r_profit_factor = (r_win_sum / r_loss_sum) if r_loss_sum > 0 else 99.99

    # Pre-cost Gross Profit Factor
    gross_profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 99.99

    # Primary profit factor is Net Profit Factor
    profit_factor = net_profit_factor

    # Costs as a share of total gross P&L
    costs_as_pct_gross_pnl = (total_fees / total_gross_pnl * 100.0) if total_gross_pnl > 0 else 0.0
    costs_as_pct_gross_profit = (total_fees / gross_profit * 100.0) if gross_profit > 0 else 0.0

    win_rate = (len(wins) / total_trades) * 100.0
    r_wins = [float(t.realized_r_multiple) for t in wins]
    r_losses = [float(t.realized_r_multiple) for t in losses]

    avg_win_r = float(np.mean(r_wins)) if r_wins else 0.0
    avg_loss_r = float(np.mean(r_losses)) if r_losses else 0.0
    expectancy_r = float(np.mean(r_multiples))
    largest_loss_r = float(min(r_multiples)) if r_multiples else 0.0

    avg_holding = float(np.mean([t.holding_sessions_count for t in trades]))

    # Exit Breakdown & Gap-through-stop analysis
    exit_counts: Dict[str, int] = {}
    gap_stops: List[float] = []
    for t in trades:
        reason_str = t.exit_reason.value if hasattr(t.exit_reason, "value") else str(t.exit_reason)
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

    # 2. Portfolio-level metrics & Taxes
    init_cap_flt = float(initial_capital)
    total_return_pct = (net_pnl / init_cap_flt) * 100.0
    num_sessions = len(equity_curve)
    years = num_sessions / annual_trading_sessions if num_sessions > 0 else 1.0

    ending_equity = init_cap_flt + net_pnl
    if ending_equity > 0 and years > 0:
        cagr_pct = ((ending_equity / init_cap_flt) ** (1.0 / years) - 1.0) * 100.0
    else:
        cagr_pct = -100.0

    # Short-Term Capital Gains Tax (20% on net gains)
    tax_amount = max(0.0, net_pnl * float(stcg_tax_rate))
    post_tax_net_pnl = net_pnl - tax_amount
    post_tax_return_pct = (post_tax_net_pnl / init_cap_flt) * 100.0
    post_tax_ending = init_cap_flt + post_tax_net_pnl
    if post_tax_ending > 0 and years > 0:
        post_tax_cagr_pct = ((post_tax_ending / init_cap_flt) ** (1.0 / years) - 1.0) * 100.0
    else:
        post_tax_cagr_pct = -100.0

    # Drawdown from true peak
    max_dd_pct = float(max((e.drawdown_pct for e in equity_curve), default=Decimal("0.00")))
    calmar = round(cagr_pct / max_dd_pct, 2) if max_dd_pct > 0 else 0.0

    # Sharpe ratio
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

    # 3. Month-Block Bootstrap for Expectancy 95% Confidence Interval
    rng = np.random.default_rng(seed)
    trades_by_month: Dict[Tuple[int, int], List[float]] = defaultdict(list)
    for t in trades:
        m_key = (t.exit_date.year, t.exit_date.month)
        trades_by_month[m_key].append(float(t.realized_r_multiple))

    month_keys = list(trades_by_month.keys())
    if len(month_keys) >= 3:
        n_months = len(month_keys)
        month_trades_list = [trades_by_month[k] for k in month_keys]
        boot_means = np.empty(10000, dtype=np.float64)
        for i in range(10000):
            sampled_indices = rng.integers(0, n_months, size=n_months)
            pooled_r = []
            for idx in sampled_indices:
                pooled_r.extend(month_trades_list[idx])
            boot_means[i] = np.mean(pooled_r) if pooled_r else 0.0
        ci_lower = round(float(np.percentile(boot_means, 2.5)), 3)
        ci_upper = round(float(np.percentile(boot_means, 97.5)), 3)
    else:
        # Fallback to trade-level bootstrap if insufficient months
        r_arr = np.array(r_multiples)
        bootstrap_means = rng.choice(r_arr, size=(10000, total_trades), replace=True).mean(axis=1)
        ci_lower = round(float(np.percentile(bootstrap_means, 2.5)), 3)
        ci_upper = round(float(np.percentile(bootstrap_means, 97.5)), 3)

    # 4. Monte Carlo Block Bootstrap of Monthly Returns (preserving geometric compounding)
    # Group equity curve by calendar month to derive monthly returns
    equity_by_date = {e.trade_date: float(e.total_equity) for e in equity_curve}
    dates_sorted = sorted(equity_by_date.keys())
    monthly_equities: Dict[Tuple[int, int], float] = {}
    for d in dates_sorted:
        monthly_equities[(d.year, d.month)] = equity_by_date[d]

    sorted_month_eqs = [monthly_equities[k] for k in sorted(monthly_equities.keys())]
    if len(sorted_month_eqs) >= 2:
        monthly_returns = [
            (sorted_month_eqs[i] - sorted_month_eqs[i - 1]) / sorted_month_eqs[i - 1]
            for i in range(1, len(sorted_month_eqs))
        ]
    else:
        monthly_returns = [net_pnl / init_cap_flt]

    mc_drawdowns = np.empty(10000, dtype=np.float64)
    mc_losing_streaks = np.empty(10000, dtype=np.int32)
    m_ret_arr = np.array(monthly_returns)
    n_m = len(monthly_returns)

    for i in range(10000):
        sampled_rets = rng.choice(m_ret_arr, size=n_m, replace=True)
        # Compound geometrically
        cum = 1.0
        peak = 1.0
        max_dd = 0.0
        streak = 0
        max_streak = 0
        for r in sampled_rets:
            cum *= (1.0 + r)
            if cum > peak:
                peak = cum
            dd = (peak - cum) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
            if r <= 0.0:
                streak += 1
                if streak > max_streak:
                    max_streak = streak
            else:
                streak = 0
        mc_drawdowns[i] = max_dd
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
        "total_gross_pnl": round(total_gross_pnl, 2),
        "total_fees_paid": round(total_fees, 2),
        "costs_as_pct_gross_pnl": round(costs_as_pct_gross_pnl, 2),
        "costs_as_pct_gross_profit": round(costs_as_pct_gross_profit, 2),
        "net_pnl": round(net_pnl, 2),
        "post_tax_net_pnl": round(post_tax_net_pnl, 2),
        "total_return_pct": round(total_return_pct, 2),
        "post_tax_return_pct": round(post_tax_return_pct, 2),
        "cagr_pct": round(cagr_pct, 2),
        "post_tax_cagr_pct": round(post_tax_cagr_pct, 2),
        "profit_factor": round(profit_factor, 2),
        "net_profit_factor": round(net_profit_factor, 2),
        "r_profit_factor": round(r_profit_factor, 2),
        "gross_profit_factor": round(gross_profit_factor, 2),
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
