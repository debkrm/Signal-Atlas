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
from typing import Any, Dict, List, Optional, Sequence, Tuple
import yaml

from sqlalchemy import text

from signal_atlas.backtest.engine import BacktestEngine, BacktestEngineConfig, EntryVariant
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
    ):
        self.trading_dates = sorted(trading_dates)
        self.prices_by_instrument = prices_by_instrument
        self.symbols_by_instrument = symbols_by_instrument
        self.benchmark_prices = sorted(benchmark_prices, key=lambda x: x.trade_date)

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
) -> FastBacktestDataset:
    """
    Loads top liquid cash equities from PostgreSQL development dataset up to end_date.
    Strictly excludes data past end_date (Locked Holdout).
    """
    print(f"Loading development dataset (<= {end_date}, top {max_symbols} liquid symbols)...")
    t0 = time.time()

    with get_db() as db:
        # 1. Query top liquid EQ instruments in dev period
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

        # 2. Query benchmark NIFTYBEES
        bench_inst_id = db.execute(text("""
            SELECT instrument_id FROM instrument_symbol_history WHERE symbol = 'NIFTYBEES' LIMIT 1
        """)).scalar()
        if not bench_inst_id:
            raise RuntimeError("Benchmark NIFTYBEES not found in database!")

        bench_history = get_point_in_time_adjusted_history(bench_inst_id, end_date, db=db)
        bench_dates = [b.trade_date for b in bench_history if b.trade_date <= end_date]

        prices_by_inst: Dict[str, List[AdjustedPriceRecord]] = {}
        symbols_by_inst: Dict[str, str] = {}

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
    )


class FastSimulationRunner:
    """
    High-performance pure execution simulator executing exact live risk and sizing rules.
    """

    def __init__(self, dataset: FastBacktestDataset, config: Optional[BacktestEngineConfig] = None):
        self.dataset = dataset
        self.config = config or BacktestEngineConfig()

    def run(
        self,
        params: TrendPullbackParameters,
        start_date: datetime.date,
        end_date: datetime.date,
        entry_variant: EntryVariant = EntryVariant.A,
        ignore_regime: bool = False,
        stress_costs: bool = False,
        delay_entry_by_one_day: bool = False,
        max_holding_sessions: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Runs single deterministic simulation over [start_date, end_date]."""
        dates = [d for d in self.dataset.trading_dates if start_date <= d <= end_date]
        if not dates:
            raise ValueError(f"No dates in range {start_date} to {end_date}")

        holding_limit = max_holding_sessions or self.config.max_holding_sessions

        # Transaction cost model
        slip_bps = Decimal("0.0025") if stress_costs else Decimal("0.0010")
        stt_rate = Decimal("0.0010")
        exch_rate = Decimal("0.0000297")
        sebi_rate = Decimal("0.000001")
        stamp_rate = Decimal("0.00015")
        gst_rate = Decimal("0.18")
        dp_charge = Decimal("15.93") if not stress_costs else Decimal("31.86")

        def calc_buy_costs(price: Decimal, qty: int) -> Tuple[Decimal, Decimal]:
            gross = price * Decimal(qty)
            slip = (gross * slip_bps).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            exec_p = gross + slip
            stt = (exec_p * stt_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            exch = (exec_p * exch_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            sebi = (exec_p * sebi_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            stamp = (exec_p * stamp_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            gst = ((exch + sebi) * gst_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_fees = slip + stt + exch + sebi + stamp + gst
            return total_fees, -(exec_p + stt + exch + sebi + stamp + gst)

        def calc_sell_costs(price: Decimal, qty: int) -> Tuple[Decimal, Decimal]:
            gross = price * Decimal(qty)
            slip = (gross * slip_bps).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            exec_p = gross - slip
            stt = (exec_p * stt_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            exch = (exec_p * exch_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            sebi = (exec_p * sebi_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            gst = ((exch + sebi) * gst_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_fees = slip + stt + exch + sebi + gst + dp_charge
            net_proceeds = exec_p - (stt + exch + sebi + gst + dp_charge)
            return total_fees, net_proceeds

        cash: Decimal = self.config.initial_capital
        peak_equity: Decimal = cash
        active_positions: Dict[str, Dict[str, Any]] = {}
        completed_trades: List[PositionRecord] = []
        equity_curve: List[EquitySnapshot] = []

        total_signals = 0
        filled_signals = 0
        killswitch_triggers = 0
        regime_blocks = 0

        pending_queue: List[Tuple[int, Dict[str, Any]]] = []  # (days_delayed, candidate_dict)
        killswitch_cooldown = 0

        for d_idx, curr_date in enumerate(dates):
            # 1a. Gap-down exits at Open (open <= stop_loss)
            closed_this_day: List[str] = []
            for inst_id, pos in list(active_positions.items()):
                inst_info = self.dataset.inst_data.get(inst_id)
                if not inst_info or curr_date not in inst_info["date_map"]:
                    continue
                _, bar = inst_info["date_map"][curr_date]

                if bar.open <= pos["stop_loss"]:
                    fees, net_proceeds = calc_sell_costs(bar.open, pos["qty"])
                    cash += net_proceeds
                    gross_entry = pos["entry_price"] * Decimal(pos["qty"])
                    gross_exit = bar.open * Decimal(pos["qty"])
                    gross_pnl = gross_exit - gross_entry
                    net_pnl = gross_pnl - pos["entry_fees"] - fees
                    net_ret = (net_pnl / gross_entry).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                    total_risk = pos["risk_per_share"] * Decimal(pos["qty"])
                    r_mult = (net_pnl / total_risk).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if total_risk > 0 else Decimal("0.00")

                    completed_trades.append(
                        PositionRecord(
                            trade_id=pos["trade_id"],
                            instrument_id=inst_id,
                            symbol=pos["symbol"],
                            entry_date=pos["entry_date"],
                            entry_price=pos["entry_price"],
                            quantity=pos["qty"],
                            entry_gross_value=gross_entry,
                            entry_fees=pos["entry_fees"],
                            initial_stop_loss=pos["stop_loss"],
                            initial_target_price=pos["target_price"],
                            initial_risk_per_share=pos["risk_per_share"],
                            exit_date=curr_date,
                            exit_price=bar.open,
                            exit_gross_value=gross_exit,
                            exit_fees=fees,
                            exit_reason=ExitReason.STOP_LOSS,
                            holding_sessions_count=pos["holding"],
                            gross_pnl=gross_pnl,
                            net_pnl=net_pnl,
                            net_return_pct=net_ret,
                            realized_r_multiple=r_mult,
                        )
                    )
                    closed_this_day.append(inst_id)

            for inst_id in closed_this_day:
                del active_positions[inst_id]

            # 1b. Mark-to-open equity
            open_val = Decimal("0.00")
            open_risk = Decimal("0.00")
            for inst_id, pos in active_positions.items():
                inst_info = self.dataset.inst_data.get(inst_id)
                ref_p = pos["entry_price"]
                if inst_info and curr_date in inst_info["date_map"]:
                    ref_p = inst_info["date_map"][curr_date][1].open
                open_val += ref_p * Decimal(pos["qty"])
                open_risk += pos["risk_per_share"] * Decimal(pos["qty"])

            curr_equity = cash + open_val
            drawdown = ((peak_equity - curr_equity) / peak_equity) if peak_equity > Decimal("0") else Decimal("0.00")
            killswitch_on = False
            if drawdown >= self.config.drawdown_killswitch_pct:
                killswitch_triggers += 1
                if self.config.killswitch_cooldown_sessions is None:
                    killswitch_on = True
                else:
                    if killswitch_cooldown == 0:
                        killswitch_cooldown = self.config.killswitch_cooldown_sessions
                        killswitch_on = True
                    else:
                        killswitch_cooldown -= 1
                        if killswitch_cooldown == 0:
                            # Re-enable by resetting peak to current equity
                            peak_equity = curr_equity
                            killswitch_on = False
                        else:
                            killswitch_on = True

            # 1c. Process entries from pending queue
            new_pending_queue = []
            if not killswitch_on and pending_queue:
                max_allowed_risk = curr_equity * self.config.max_total_open_risk_pct

                for days_left, cand in pending_queue:
                    if days_left > 0:
                        new_pending_queue.append((days_left - 1, cand))
                        continue

                    if len(active_positions) >= self.config.max_concurrent_positions:
                        continue
                    inst_id = cand["inst_id"]
                    if inst_id in active_positions:
                        continue

                    inst_info = self.dataset.inst_data.get(inst_id)
                    if not inst_info or curr_date not in inst_info["date_map"]:
                        continue
                    _, bar = inst_info["date_map"][curr_date]

                    # Fill price determination
                    fill_p: Optional[Decimal] = None
                    if entry_variant == EntryVariant.A:
                        # Variant A: Open fill with R:R recheck
                        if bar.open <= cand["stop_loss"] or bar.open >= cand["target_price"]:
                            continue
                        gap_pct = abs(bar.open - cand["entry_ref"]) / cand["entry_ref"]
                        if gap_pct > Decimal("0.015"):
                            continue
                        # Recalculate R:R
                        eff_risk = bar.open - cand["stop_loss"]
                        eff_reward = cand["target_price"] - bar.open
                        if eff_risk <= 0:
                            continue
                        eff_rr = (eff_reward / eff_risk).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        if eff_rr < params.min_reward_to_risk:
                            continue
                        fill_p = bar.open
                    elif entry_variant == EntryVariant.B:
                        if bar.open <= cand["entry_ref"]:
                            fill_p = bar.open
                        elif bar.low <= cand["entry_ref"]:
                            fill_p = cand["entry_ref"]
                    elif entry_variant == EntryVariant.C:
                        if bar.open < cand["entry_ref"]:
                            fill_p = bar.open
                        elif bar.low <= (cand["entry_ref"] - Decimal("0.05")):
                            fill_p = cand["entry_ref"]

                    if fill_p is None:
                        continue

                    risk_per_sh = fill_p - cand["stop_loss"]
                    if risk_per_sh <= Decimal("0"):
                        continue

                    # Sizing
                    risk_bud = curr_equity * self.config.risk_per_trade_pct
                    q_risk = int((risk_bud / risk_per_sh).quantize(Decimal("1"), rounding=ROUND_DOWN))
                    cap_bud = min(cash, curr_equity * self.config.max_capital_per_position_pct)
                    q_cap = int((cap_bud / fill_p).quantize(Decimal("1"), rounding=ROUND_DOWN))
                    q_adtv = q_cap
                    if bar.traded_value and bar.traded_value > 0:
                        max_vol = int((bar.traded_value * self.config.max_adtv_participation_pct / fill_p).quantize(Decimal("1"), rounding=ROUND_DOWN))
                        q_adtv = max(1, max_vol)

                    qty = min(q_risk, q_cap, q_adtv)
                    if qty <= 0:
                        continue

                    # 6% open risk limit: strictly matches live RiskEngine (block if prospective risk > 6%)
                    t_risk = risk_per_sh * Decimal(qty)
                    if (open_risk + t_risk) > max_allowed_risk:
                        continue

                    # Minimum trade value threshold (₹10,000) to prevent micro-lot DP charge distortion
                    if (Decimal(qty) * fill_p) < Decimal("10000.00"):
                        continue

                    fees, net_flow = calc_buy_costs(fill_p, qty)
                    req_cash = -net_flow
                    if req_cash > cash:
                        qty = int((cash / (fill_p * Decimal("1.01"))).quantize(Decimal("1"), rounding=ROUND_DOWN))
                        if qty <= 0:
                            continue
                        fees, net_flow = calc_buy_costs(fill_p, qty)
                        req_cash = -net_flow
                        if req_cash > cash:
                            continue

                    cash -= req_cash
                    open_risk += risk_per_sh * Decimal(qty)
                    filled_signals += 1

                    active_positions[inst_id] = {
                        "trade_id": f"TRD-{len(completed_trades)+len(active_positions)+1:04d}",
                        "symbol": cand["symbol"],
                        "entry_date": curr_date,
                        "entry_price": fill_p,
                        "qty": qty,
                        "entry_fees": fees,
                        "stop_loss": cand["stop_loss"],
                        "target_price": cand["target_price"],
                        "risk_per_share": risk_per_sh,
                        "holding": 0,
                    }

            pending_queue = new_pending_queue

            # -----------------------------------------------------------------
            # STEP 2: Intraday Exits
            # -----------------------------------------------------------------
            closed_this_day = []
            for inst_id, pos in list(active_positions.items()):
                pos["holding"] += 1
                inst_info = self.dataset.inst_data.get(inst_id)
                if not inst_info or curr_date not in inst_info["date_map"]:
                    continue
                _, bar = inst_info["date_map"][curr_date]

                exit_trig = False
                exit_p = bar.close
                reason = ExitReason.MAX_HOLDING_TIME

                # Rule 1: Dual touch -> Stop first
                if bar.low <= pos["stop_loss"] and bar.high >= pos["target_price"]:
                    exit_trig = True
                    exit_p = pos["stop_loss"]
                    reason = ExitReason.STOP_LOSS
                elif bar.low <= pos["stop_loss"]:
                    exit_trig = True
                    exit_p = pos["stop_loss"]
                    reason = ExitReason.STOP_LOSS
                elif bar.high >= pos["target_price"]:
                    exit_trig = True
                    exit_p = pos["target_price"]
                    reason = ExitReason.PROFIT_TARGET
                elif pos["holding"] >= holding_limit:
                    exit_trig = True
                    exit_p = bar.close
                    reason = ExitReason.MAX_HOLDING_TIME
                elif d_idx == len(dates) - 1:
                    exit_trig = True
                    exit_p = bar.close
                    reason = ExitReason.END_OF_SIMULATION

                if exit_trig:
                    fees, net_proceeds = calc_sell_costs(exit_p, pos["qty"])
                    cash += net_proceeds
                    gross_entry = pos["entry_price"] * Decimal(pos["qty"])
                    gross_exit = exit_p * Decimal(pos["qty"])
                    gross_pnl = gross_exit - gross_entry
                    net_pnl = gross_pnl - pos["entry_fees"] - fees
                    net_ret = (net_pnl / gross_entry).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                    total_risk = pos["risk_per_share"] * Decimal(pos["qty"])
                    r_mult = (net_pnl / total_risk).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if total_risk > 0 else Decimal("0.00")

                    completed_trades.append(
                        PositionRecord(
                            trade_id=pos["trade_id"],
                            instrument_id=inst_id,
                            symbol=pos["symbol"],
                            entry_date=pos["entry_date"],
                            entry_price=pos["entry_price"],
                            quantity=pos["qty"],
                            entry_gross_value=gross_entry,
                            entry_fees=pos["entry_fees"],
                            initial_stop_loss=pos["stop_loss"],
                            initial_target_price=pos["target_price"],
                            initial_risk_per_share=pos["risk_per_share"],
                            exit_date=curr_date,
                            exit_price=exit_p,
                            exit_gross_value=gross_exit,
                            exit_fees=fees,
                            exit_reason=reason,
                            holding_sessions_count=pos["holding"],
                            gross_pnl=gross_pnl,
                            net_pnl=net_pnl,
                            net_return_pct=net_ret,
                            realized_r_multiple=r_mult,
                        )
                    )
                    closed_this_day.append(inst_id)

            for inst_id in closed_this_day:
                del active_positions[inst_id]

            # -----------------------------------------------------------------
            # STEP 3: Mark to Market at Close & Equity Snapshot
            # -----------------------------------------------------------------
            eod_val = Decimal("0.00")
            for inst_id, pos in active_positions.items():
                inst_info = self.dataset.inst_data.get(inst_id)
                cp = pos["entry_price"]
                if inst_info and curr_date in inst_info["date_map"]:
                    cp = inst_info["date_map"][curr_date][1].close
                eod_val += cp * Decimal(pos["qty"])

            eod_equity = cash + eod_val
            if eod_equity > peak_equity:
                peak_equity = eod_equity

            dd = ((peak_equity - eod_equity) / peak_equity * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if peak_equity > 0 else Decimal("0.00")
            equity_curve.append(
                EquitySnapshot(
                    trade_date=curr_date,
                    cash=cash.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    portfolio_value=eod_val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    total_equity=eod_equity.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    drawdown_pct=dd,
                    open_positions_count=len(active_positions),
                )
            )

            # -----------------------------------------------------------------
            # STEP 4: Day t Close Strategy Screening for Next Session
            # -----------------------------------------------------------------
            # Check market regime gate
            is_bullish = True
            if self.config.gate_enabled and not ignore_regime:
                b_rec = self.dataset.bench_by_date.get(curr_date)
                b_ema = self.dataset.bench_ema_by_date.get(curr_date)
                if b_rec and b_ema:
                    is_bullish = b_rec.close > b_ema

            if not is_bullish and not ignore_regime:
                regime_blocks += 1
                continue

            day_candidates = []
            for inst_id, data in self.dataset.inst_data.items():
                if curr_date not in data["date_map"]:
                    continue
                bar_idx, bar = data["date_map"][curr_date]
                if bar_idx < 50:
                    continue

                c = bar.close
                ema20 = data["ema20"][bar_idx]
                ema50 = data["ema50"][bar_idx]
                rsi14 = data["rsi14"][bar_idx]
                atr14 = data["atr14"][bar_idx]
                w_bull = data["weekly_bullish"][bar_idx]

                if ema20 is None or ema50 is None or rsi14 is None or atr14 is None:
                    continue

                # Strategy filters
                if params.require_price_above_ema50 and c <= ema50:
                    continue
                if params.require_ema_alignment and ema20 <= ema50:
                    continue
                if params.require_weekly_trend_bullish and not w_bull:
                    continue

                dist_ema20 = (c - ema20) / ema20 if ema20 > 0 else None
                if dist_ema20 is None or dist_ema20 > params.max_ema20_distance_pct:
                    continue
                if c < ema50:
                    continue

                if rsi14 < params.min_rsi or rsi14 > params.max_rsi:
                    continue

                # Stop and Target calculation
                stop_p = (c - (atr14 * params.stop_atr_multiplier)).quantize(Decimal("0.05"), rounding=ROUND_HALF_UP)
                target_p = (c + (atr14 * params.target_atr_multiplier)).quantize(Decimal("0.05"), rounding=ROUND_HALF_UP)

                risk = c - stop_p
                reward = target_p - c
                if risk <= Decimal("0") or reward <= Decimal("0"):
                    continue

                rr = (reward / risk).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if rr < params.min_reward_to_risk:
                    continue

                cand_dict = {
                    "inst_id": inst_id,
                    "symbol": data["symbol"],
                    "signal_date": curr_date,
                    "entry_ref": c,
                    "stop_loss": stop_p,
                    "target_price": target_p,
                    "reward_to_risk": rr,
                }
                day_candidates.append(cand_dict)
                total_signals += 1

            # Rank by reward-to-risk descending
            day_candidates.sort(key=lambda x: -x["reward_to_risk"])
            delay_days = 1 if delay_entry_by_one_day else 0
            for cand in day_candidates:
                pending_queue.append((delay_days, cand))

        metrics = calculate_comprehensive_metrics(completed_trades, equity_curve, self.config.initial_capital)
        fill_rate = (filled_signals / total_signals * 100.0) if total_signals > 0 else 0.0

        return {
            "metrics": metrics,
            "trades": completed_trades,
            "equity_curve": equity_curve,
            "total_signals": total_signals,
            "filled_signals": filled_signals,
            "fill_rate_pct": round(fill_rate, 2),
            "killswitch_triggers": killswitch_triggers,
            "regime_blocks": regime_blocks,
        }
