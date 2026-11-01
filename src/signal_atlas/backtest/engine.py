"""
engine.py - Production Backtesting Event Loop for Signal Atlas.

Strictly follows backtest_and_tuning_plan.md and Section 2.2 / 8.3 of Architecture:
- Single authoritative engine for all backtests, walk-forward folds, sweeps, and baselines (Task 2 / D8).
- Point-in-time universe compliance per date t (Task 1 / D1).
- Never-reset true high-water mark drawdown tracking across all kill-switch variants (Task 3 / D3).
- Deterministic candidate ranking based on trailing ADTV and RSI distance from 50 (Task 4 / D7).
- Position handling with missing bar tracking, force-exit on inactivity, and clean end-of-run liquidation (Task 10 / D10).
- Shared Strategy and Risk Engine functions for fills, sizing, and filters.
"""

from collections import deque
import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
import uuid

import numpy as np

from signal_atlas.backtest.costs import ExecutionCostBreakdown, TransactionCostModel
from signal_atlas.backtest.metrics import calculate_comprehensive_metrics
from signal_atlas.backtest.models import (
    BacktestConfig,
    EquitySnapshot,
    ExitReason,
    PositionRecord,
)
from signal_atlas.features.engine import TechnicalFeatureEngine
from signal_atlas.features.indicators import compute_ema
from signal_atlas.features.models import TechnicalFeatures
from signal_atlas.quality.adjustment import AdjustedPriceRecord
from signal_atlas.risk.sizing import calculate_position_sizing
from signal_atlas.strategy.base import Strategy
from signal_atlas.strategy.models import MarketContext, SignalState, StrategyCandidate
from signal_atlas.strategy.trend_pullback import TICK_SIZE, TrendPullbackStrategy, round_to_tick


class EntryVariant(str, Enum):
    A = "A"  # Primary: t+1 open + slippage, skip if R:R < min or open > entry_zone_high
    B = "B"  # Limit order: fill at open if open <= entry, else entry if low <= entry
    C = "C"  # Limit order, strict touch: require low <= entry - 1 tick
    PESSIMISTIC = "PESSIMISTIC"  # Limit order with gap check, R:R recheck, and adverse fill


class KillswitchVariant(str, Enum):
    NEVER_REENABLE = "never_reenable"
    COOLDOWN_KEEP_TRUE_PEAK = "cooldown_keep_true_peak"
    RESET_PEAK_AFTER_COOLDOWN = "reset_peak_after_cooldown"


class ActiveTrade:
    def __init__(
        self,
        trade_id: str,
        instrument_id: str,
        symbol: str,
        entry_date: datetime.date,
        entry_price: Decimal,
        quantity: int,
        entry_fees: Decimal,
        stop_loss: Decimal,
        target_price: Decimal,
        risk_per_share: Decimal,
        last_known_close: Decimal,
    ):
        self.trade_id = trade_id
        self.instrument_id = instrument_id
        self.symbol = symbol
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.quantity = quantity
        self.entry_fees = entry_fees
        self.stop_loss = stop_loss
        self.target_price = target_price
        self.risk_per_share = risk_per_share
        self.holding_sessions: int = 0
        self.missing_sessions_count: int = 0
        self.last_known_close: Decimal = last_known_close


class BacktestEngineConfig(BacktestConfig):
    entry_variant: EntryVariant = EntryVariant.A
    max_total_open_risk_pct: Decimal = Decimal("0.06")  # 6% open risk cap
    drawdown_killswitch_pct: Decimal = Decimal("0.10")   # 10% drawdown halt
    killswitch_cooldown_sessions: int = 20              # Cooldown period
    killswitch_variant: KillswitchVariant = KillswitchVariant.COOLDOWN_KEEP_TRUE_PEAK
    dp_charge_per_scrip: Decimal = Decimal("15.93")     # ₹13.50 + 18% GST on delivery sell
    gate_enabled: bool = True
    benchmark_ema_period: int = 50
    tick_size: Decimal = Decimal("0.05")
    max_missing_sessions: int = 5                       # Force exit after 5 missing sessions
    deterministic_ranking: bool = True
    ranking_seed: Optional[int] = None


class BacktestEngine:
    """
    Unified, deterministic simulation engine executing live risk and execution rules.
    """

    def __init__(self, config: Optional[BacktestEngineConfig] = None):
        self.config = config or BacktestEngineConfig()

    def run_simulation(
        self,
        strategy: Strategy,
        trading_dates: Sequence[datetime.date],
        prices_by_instrument: Dict[str, Sequence[AdjustedPriceRecord]],
        benchmark_prices: Optional[Sequence[AdjustedPriceRecord]] = None,
        symbols_by_instrument: Optional[Dict[str, str]] = None,
        universe_by_date: Optional[Dict[datetime.date, Set[str]]] = None,
        ignore_regime: bool = False,
        entry_variant: Optional[EntryVariant] = None,
        stress_costs: bool = False,
        delay_entry_by_one_day: bool = False,
        killswitch_variant_override: Optional[KillswitchVariant] = None,
        ranking_seed: Optional[int] = None,
        precomputed_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Executes backtest over chronological trading_dates.
        """
        if not trading_dates:
            raise ValueError("trading_dates cannot be empty")

        sorted_dates = sorted(trading_dates)
        variant = entry_variant or self.config.entry_variant
        ks_variant = killswitch_variant_override or self.config.killswitch_variant
        r_seed = ranking_seed if ranking_seed is not None else self.config.ranking_seed

        cost_model = TransactionCostModel(
            brokerage_per_order=Decimal("0.00"),
            brokerage_pct=Decimal("0.00"),
            stt_rate=Decimal("0.0010"),
            exchange_rate=Decimal("0.0000297") * (Decimal("2.0") if stress_costs else Decimal("1.0")),
            sebi_rate=Decimal("0.000001") * (Decimal("2.0") if stress_costs else Decimal("1.0")),
            stamp_duty_buy_rate=Decimal("0.00015"),
            gst_rate=Decimal("0.18"),
            slippage_bps=Decimal("0.0025") if stress_costs else Decimal("0.0010"),
        )
        dp_charge = self.config.dp_charge_per_scrip * (Decimal("2.0") if stress_costs else Decimal("1.0"))

        feature_engine = TechnicalFeatureEngine(min_required_sessions=self.config.min_history_sessions)

        # 1. Index instrument prices by (inst_id, date)
        price_lookup: Dict[str, Dict[datetime.date, AdjustedPriceRecord]] = {}
        for inst_id, recs in prices_by_instrument.items():
            price_lookup[inst_id] = {r.trade_date: r for r in recs}

        # Sorted histories per instrument
        sorted_inst_recs: Dict[str, List[AdjustedPriceRecord]] = {
            inst_id: sorted(recs, key=lambda r: r.trade_date)
            for inst_id, recs in prices_by_instrument.items()
        }

        # Fast date-to-index lookup per instrument
        inst_date_to_idx: Dict[str, Dict[datetime.date, int]] = {
            inst_id: {r.trade_date: i for i, r in enumerate(recs)}
            for inst_id, recs in sorted_inst_recs.items()
        }

        # 2. Benchmark regime evaluation series
        bench_by_date: Dict[datetime.date, AdjustedPriceRecord] = {}
        bench_ema_by_date: Dict[datetime.date, Decimal] = {}
        if benchmark_prices:
            bench_sorted = sorted(benchmark_prices, key=lambda x: x.trade_date)
            bench_closes = [b.close for b in bench_sorted]
            bench_emas = compute_ema(bench_closes, self.config.benchmark_ema_period)
            for b, ema in zip(bench_sorted, bench_emas):
                bench_by_date[b.trade_date] = b
                if ema is not None:
                    bench_ema_by_date[b.trade_date] = ema

        cash: Decimal = self.config.initial_capital
        true_peak_equity: Decimal = cash
        active_positions: Dict[str, ActiveTrade] = {}
        completed_trades: List[PositionRecord] = []
        equity_curve: List[EquitySnapshot] = []

        total_signals_generated = 0
        total_signals_filled = 0
        killswitch_triggered_days = 0
        regime_blocked_days = 0

        # Killswitch state machine: "ACTIVE" or "COOLDOWN"
        killswitch_state = "ACTIVE"
        cooldown_remaining = 0
        killswitch_triggers = 0
        legacy_reset_peak: Optional[Decimal] = None

        pending_queue: List[Tuple[int, StrategyCandidate, Decimal]] = []  # (delay_days_remaining, candidate, trailing_adtv)

        for d_idx, curr_date in enumerate(sorted_dates):
            is_final_session = (d_idx == len(sorted_dates) - 1)

            # -----------------------------------------------------------------
            # STEP 1: Morning Open Bell Fills (Gap Exits & Pending Entries)
            # -----------------------------------------------------------------
            closed_this_day: List[str] = []

            # 1a. Gap-down exits at Open (open <= stop_loss)
            for inst_id, pos in list(active_positions.items()):
                bar = price_lookup.get(inst_id, {}).get(curr_date)
                if not bar:
                    pos.missing_sessions_count += 1
                    if pos.missing_sessions_count >= self.config.max_missing_sessions:
                        # Force exit due to prolonged missing data/suspension
                        exit_price = pos.last_known_close
                        sell_breakdown = cost_model.calculate_sell_costs(exit_price, pos.quantity)
                        net_proceeds = sell_breakdown.net_cash_flow - dp_charge
                        cash += net_proceeds

                        gross_val_entry = pos.entry_price * Decimal(pos.quantity)
                        gross_val_exit = exit_price * Decimal(pos.quantity)
                        gross_pnl = gross_val_exit - gross_val_entry
                        total_exit_fees = sell_breakdown.total_charges + dp_charge
                        net_pnl = gross_pnl - pos.entry_fees - total_exit_fees
                        net_return = (net_pnl / gross_val_entry).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                        initial_total_risk = pos.risk_per_share * Decimal(pos.quantity)
                        realized_r = (
                            (net_pnl / initial_total_risk).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                            if initial_total_risk > Decimal("0")
                            else Decimal("0.00")
                        )
                        completed_trades.append(
                            PositionRecord(
                                trade_id=pos.trade_id, instrument_id=pos.instrument_id, symbol=pos.symbol,
                                entry_date=pos.entry_date, entry_price=pos.entry_price, quantity=pos.quantity,
                                entry_gross_value=gross_val_entry, entry_fees=pos.entry_fees,
                                initial_stop_loss=pos.stop_loss, initial_target_price=pos.target_price,
                                initial_risk_per_share=pos.risk_per_share, exit_date=curr_date,
                                exit_price=exit_price, exit_gross_value=gross_val_exit,
                                exit_fees=total_exit_fees, exit_reason=ExitReason.STOP_LOSS,
                                holding_sessions_count=pos.holding_sessions, gross_pnl=gross_pnl,
                                net_pnl=net_pnl, net_return_pct=net_return, realized_r_multiple=realized_r,
                            )
                        )
                        closed_this_day.append(inst_id)
                    continue

                pos.last_known_close = bar.close
                if bar.open <= pos.stop_loss:
                    sell_breakdown = cost_model.calculate_sell_costs(bar.open, pos.quantity)
                    net_proceeds = sell_breakdown.net_cash_flow - dp_charge
                    cash += net_proceeds
                    gross_val_entry = pos.entry_price * Decimal(pos.quantity)
                    gross_val_exit = bar.open * Decimal(pos.quantity)
                    gross_pnl = gross_val_exit - gross_val_entry
                    total_exit_fees = sell_breakdown.total_charges + dp_charge
                    net_pnl = gross_pnl - pos.entry_fees - total_exit_fees
                    net_return = (net_pnl / gross_val_entry).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                    initial_total_risk = pos.risk_per_share * Decimal(pos.quantity)
                    realized_r = (
                        (net_pnl / initial_total_risk).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        if initial_total_risk > Decimal("0")
                        else Decimal("0.00")
                    )
                    completed_trades.append(
                        PositionRecord(
                            trade_id=pos.trade_id, instrument_id=pos.instrument_id, symbol=pos.symbol,
                            entry_date=pos.entry_date, entry_price=pos.entry_price, quantity=pos.quantity,
                            entry_gross_value=gross_val_entry, entry_fees=pos.entry_fees,
                            initial_stop_loss=pos.stop_loss, initial_target_price=pos.target_price,
                            initial_risk_per_share=pos.risk_per_share, exit_date=curr_date,
                            exit_price=bar.open, exit_gross_value=gross_val_exit,
                            exit_fees=total_exit_fees, exit_reason=ExitReason.STOP_LOSS,
                            holding_sessions_count=pos.holding_sessions, gross_pnl=gross_pnl,
                            net_pnl=net_pnl, net_return_pct=net_return, realized_r_multiple=realized_r,
                        )
                    )
                    closed_this_day.append(inst_id)

            for inst_id in closed_this_day:
                del active_positions[inst_id]
            closed_this_day = []

            # 1b. Mark-to-open equity to check killswitch & portfolio open risk
            open_positions_val = Decimal("0.00")
            current_open_risk = Decimal("0.00")
            for inst_id, pos in active_positions.items():
                b = price_lookup.get(inst_id, {}).get(curr_date)
                ref_p = b.open if b else pos.last_known_close
                open_positions_val += ref_p * Decimal(pos.quantity)
                current_open_risk += pos.risk_per_share * Decimal(pos.quantity)

            current_equity = cash + open_positions_val

            # True peak tracking (never reset!)
            if current_equity > true_peak_equity:
                true_peak_equity = current_equity

            # Effective peak for drawdown calculation depending on variant
            eval_peak = legacy_reset_peak if (ks_variant == KillswitchVariant.RESET_PEAK_AFTER_COOLDOWN and legacy_reset_peak is not None) else true_peak_equity
            drawdown = (
                (eval_peak - current_equity) / eval_peak
                if eval_peak > Decimal("0")
                else Decimal("0.00")
            )

            # Killswitch state update (Task 3)
            if drawdown >= self.config.drawdown_killswitch_pct:
                killswitch_triggered_days += 1
                if killswitch_state == "ACTIVE":
                    killswitch_state = "COOLDOWN"
                    cooldown_remaining = self.config.killswitch_cooldown_sessions
                    killswitch_triggers += 1
            elif killswitch_state == "COOLDOWN":
                # Decrement cooldown counter every completed session
                cooldown_remaining -= 1
                if cooldown_remaining <= 0:
                    if ks_variant == KillswitchVariant.NEVER_REENABLE:
                        # Stays permanently in cooldown
                        pass
                    elif ks_variant == KillswitchVariant.COOLDOWN_KEEP_TRUE_PEAK:
                        killswitch_state = "ACTIVE"
                    elif ks_variant == KillswitchVariant.RESET_PEAK_AFTER_COOLDOWN:
                        killswitch_state = "ACTIVE"
                        legacy_reset_peak = current_equity

            is_killswitch_blocking = (killswitch_state == "COOLDOWN")

            # 1c. Process New Entries (if killswitch is not blocking)
            new_pending_queue = []
            if not is_killswitch_blocking and pending_queue:
                max_open_risk_allowed = current_equity * self.config.max_total_open_risk_pct

                for delay_days, cand, trailing_adtv in pending_queue:
                    if delay_days > 0:
                        new_pending_queue.append((delay_days - 1, cand, trailing_adtv))
                        continue

                    if len(active_positions) >= self.config.max_concurrent_positions:
                        continue
                    if cand.instrument_id in active_positions:
                        continue

                    bar = price_lookup.get(cand.instrument_id, {}).get(curr_date)
                    if not bar:
                        continue

                    # Evaluate Entry Variant using shared Strategy logic
                    fill_p: Optional[Decimal] = None
                    if variant == EntryVariant.A:
                        # Primary: Open + slippage with R:R recheck
                        is_valid, actual_p, _ = strategy.evaluate_next_session_entry(
                            cand, next_open=bar.open, next_high=bar.high, next_low=bar.low
                        )
                        if is_valid and actual_p is not None:
                            fill_p = actual_p
                    elif variant == EntryVariant.B:
                        # Limit order at planned entry
                        if bar.open <= cand.entry_reference:
                            fill_p = bar.open
                        elif bar.low <= cand.entry_reference:
                            fill_p = cand.entry_reference
                    elif variant == EntryVariant.C:
                        # Limit order, strict touch: require low <= entry - 1 tick
                        if bar.open < cand.entry_reference:
                            fill_p = bar.open
                        elif bar.low <= (cand.entry_reference - self.config.tick_size):
                            fill_p = cand.entry_reference
                    elif variant == EntryVariant.PESSIMISTIC:
                        # Pessimistic limit: strict touch + gap check + R:R recheck
                        is_valid, actual_p, _ = strategy.evaluate_next_session_entry(
                            cand, next_open=bar.open, next_high=bar.high, next_low=bar.low
                        )
                        if is_valid and actual_p is not None:
                            if bar.low <= (cand.entry_reference - self.config.tick_size):
                                fill_p = max(actual_p, cand.entry_reference)

                    if fill_p is None:
                        continue

                    risk_per_sh = fill_p - cand.stop_loss
                    if risk_per_sh <= Decimal("0"):
                        continue

                    # Sizing via shared calculate_position_sizing (Task 2, Task 10)
                    sizing_res = calculate_position_sizing(
                        entry_price=fill_p,
                        stop_loss=cand.stop_loss,
                        total_equity=current_equity,
                        available_cash=cash,
                        risk_per_trade_pct=self.config.risk_per_trade_pct,
                        max_capital_per_position_pct=self.config.max_capital_per_position_pct,
                        adtv=trailing_adtv,
                        max_adtv_participation_pct=self.config.max_adtv_participation_pct,
                    )
                    qty = sizing_res.quantity
                    if qty <= 0:
                        continue

                    # Portfolio open risk constraint (max 6%)
                    trade_risk = risk_per_sh * Decimal(qty)
                    if (current_open_risk + trade_risk) > max_open_risk_allowed:
                        rem_risk = max_open_risk_allowed - current_open_risk
                        if rem_risk <= Decimal("0"):
                            continue
                        qty = int((rem_risk / risk_per_sh).quantize(Decimal("1"), rounding=ROUND_DOWN))
                        if qty <= 0:
                            continue

                    buy_breakdown = cost_model.calculate_buy_costs(fill_p, qty)
                    required_cash = -buy_breakdown.net_cash_flow
                    if required_cash > cash:
                        qty = int((cash / (fill_p * Decimal("1.01"))).quantize(Decimal("1"), rounding=ROUND_DOWN))
                        if qty <= 0:
                            continue
                        buy_breakdown = cost_model.calculate_buy_costs(fill_p, qty)
                        required_cash = -buy_breakdown.net_cash_flow
                        if required_cash > cash:
                            continue

                    cash -= required_cash
                    current_open_risk += risk_per_sh * Decimal(qty)
                    total_signals_filled += 1

                    active_positions[cand.instrument_id] = ActiveTrade(
                        trade_id=f"TRD-{len(completed_trades)+len(active_positions)+1:04d}",
                        instrument_id=cand.instrument_id,
                        symbol=cand.symbol,
                        entry_date=curr_date,
                        entry_price=fill_p,
                        quantity=qty,
                        entry_fees=buy_breakdown.total_charges,
                        stop_loss=cand.stop_loss,
                        target_price=cand.target_price,
                        risk_per_share=risk_per_sh,
                        last_known_close=bar.close,
                    )

            pending_queue = new_pending_queue

            # -----------------------------------------------------------------
            # STEP 2: Intraday Price Action & Session Exits
            # -----------------------------------------------------------------
            for inst_id, pos in list(active_positions.items()):
                pos.holding_sessions += 1
                bar = price_lookup.get(inst_id, {}).get(curr_date)
                if not bar:
                    continue

                pos.last_known_close = bar.close
                exit_triggered = False
                exit_price = bar.close
                exit_reason = ExitReason.MAX_HOLDING_TIME

                # Rule 1: Dual touch ambiguity -> Stop loss first (pessimistic)
                if bar.low <= pos.stop_loss and bar.high >= pos.target_price:
                    exit_triggered = True
                    exit_price = pos.stop_loss
                    exit_reason = ExitReason.STOP_LOSS
                # Rule 2: Stop loss hit
                elif bar.low <= pos.stop_loss:
                    exit_triggered = True
                    exit_price = pos.stop_loss
                    exit_reason = ExitReason.STOP_LOSS
                # Rule 3: Target touched
                elif bar.high >= pos.target_price:
                    exit_triggered = True
                    exit_price = pos.target_price
                    exit_reason = ExitReason.PROFIT_TARGET
                # Rule 4: Max holding duration reached
                elif pos.holding_sessions >= self.config.max_holding_sessions:
                    exit_triggered = True
                    exit_price = bar.close
                    exit_reason = ExitReason.MAX_HOLDING_TIME
                # Rule 5: Final session liquidation (assert no positions remain at end - Task 10)
                elif is_final_session:
                    exit_triggered = True
                    exit_price = bar.close
                    exit_reason = ExitReason.END_OF_SIMULATION

                if exit_triggered:
                    sell_breakdown = cost_model.calculate_sell_costs(exit_price, pos.quantity)
                    net_proceeds = sell_breakdown.net_cash_flow - dp_charge
                    cash += net_proceeds

                    gross_val_entry = pos.entry_price * Decimal(pos.quantity)
                    gross_val_exit = exit_price * Decimal(pos.quantity)
                    gross_pnl = gross_val_exit - gross_val_entry
                    total_exit_fees = sell_breakdown.total_charges + dp_charge
                    net_pnl = gross_pnl - pos.entry_fees - total_exit_fees
                    net_return = (net_pnl / gross_val_entry).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

                    initial_total_risk = pos.risk_per_share * Decimal(pos.quantity)
                    realized_r = (
                        (net_pnl / initial_total_risk).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        if initial_total_risk > Decimal("0")
                        else Decimal("0.00")
                    )

                    completed_trades.append(
                        PositionRecord(
                            trade_id=pos.trade_id, instrument_id=pos.instrument_id, symbol=pos.symbol,
                            entry_date=pos.entry_date, entry_price=pos.entry_price, quantity=pos.quantity,
                            entry_gross_value=gross_val_entry, entry_fees=pos.entry_fees,
                            initial_stop_loss=pos.stop_loss, initial_target_price=pos.target_price,
                            initial_risk_per_share=pos.risk_per_share, exit_date=curr_date,
                            exit_price=exit_price, exit_gross_value=gross_val_exit,
                            exit_fees=total_exit_fees, exit_reason=exit_reason,
                            holding_sessions_count=pos.holding_sessions, gross_pnl=gross_pnl,
                            net_pnl=net_pnl, net_return_pct=net_return, realized_r_multiple=realized_r,
                        )
                    )
                    closed_this_day.append(inst_id)

            for inst_id in closed_this_day:
                del active_positions[inst_id]

            # -----------------------------------------------------------------
            # STEP 3: Mark to Market at Close & Equity Snapshot
            # -----------------------------------------------------------------
            eod_positions_val = Decimal("0.00")
            for inst_id, pos in active_positions.items():
                b = price_lookup.get(inst_id, {}).get(curr_date)
                cp = b.close if b else pos.last_known_close
                eod_positions_val += cp * Decimal(pos.quantity)

            eod_equity = cash + eod_positions_val
            if eod_equity > true_peak_equity:
                true_peak_equity = eod_equity

            # True peak-to-trough drawdown (Task 3 / D3)
            dd_pct = (
                ((true_peak_equity - eod_equity) / true_peak_equity * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if true_peak_equity > Decimal("0")
                else Decimal("0.00")
            )

            equity_curve.append(
                EquitySnapshot(
                    trade_date=curr_date,
                    cash=cash.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    portfolio_value=eod_positions_val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    total_equity=eod_equity.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    drawdown_pct=dd_pct,
                    open_positions_count=len(active_positions),
                )
            )

            # If last session, skip screening for day t+1
            if is_final_session:
                break

            # -----------------------------------------------------------------
            # STEP 4: Strategy Evaluation at Day t Close for Day t+1
            # -----------------------------------------------------------------
            # Market regime check on day t close (fail-safe: False if benchmark EMA missing - D17)
            is_bullish = False
            if self.config.gate_enabled and not ignore_regime:
                b_rec = bench_by_date.get(curr_date)
                b_ema = bench_ema_by_date.get(curr_date)
                if b_rec and b_ema is not None:
                    is_bullish = (b_rec.close > b_ema)
                else:
                    is_bullish = False
            else:
                is_bullish = True

            if not is_bullish and not ignore_regime:
                regime_blocked_days += 1
                continue

            mkt_ctx = MarketContext(
                as_of_date=curr_date,
                benchmark_symbol="NIFTYBEES",
                benchmark_close=bench_by_date[curr_date].close if curr_date in bench_by_date else None,
                is_market_regime_bullish=is_bullish,
            )

            # Point-in-time universe filter for curr_date (Task 1 / D1)
            eligible_universe = universe_by_date.get(curr_date) if universe_by_date is not None else None

            day_candidates: List[Tuple[StrategyCandidate, Decimal]] = []
            
            # Determine candidate evaluation set
            candidate_inst_ids = sorted_inst_recs.keys() if eligible_universe is None else (eligible_universe & sorted_inst_recs.keys())

            for inst_id in candidate_inst_ids:
                recs = sorted_inst_recs[inst_id]
                idx_map = inst_date_to_idx[inst_id]
                if curr_date not in idx_map:
                    continue
                end_idx = idx_map[curr_date]
                if end_idx < self.config.min_history_sessions - 1:
                    continue

                # Trailing history slice up to curr_date
                history_slice = recs[:end_idx + 1]
                sym = (symbols_by_instrument or {}).get(inst_id, getattr(history_slice[-1], "symbol", inst_id))

                # Compute trailing 20-session ADTV up to day t close (Task 10 / D10)
                trailing_bars = history_slice[-20:]
                valid_tvs = [b.traded_value for b in trailing_bars if b.traded_value is not None]
                trailing_adtv = sum(valid_tvs) / Decimal(len(valid_tvs)) if valid_tvs else Decimal("0.00")

                feats = feature_engine.extract_features(
                    instrument_id=inst_id,
                    symbol=sym,
                    as_of_date=curr_date,
                    records=history_slice,
                )
                cand = strategy.evaluate_candidate(feats, mkt_ctx)
                if cand.signal_state == SignalState.BUY and cand.is_valid:
                    cand.adtv = trailing_adtv
                    day_candidates.append((cand, trailing_adtv))
                    total_signals_generated += 1

            # Deterministic Ranking (Task 4 / D7)
            if r_seed is not None:
                # Random tie-break ablation mode
                rng_rank = np.random.default_rng(r_seed + d_idx)
                rng_rank.shuffle(day_candidates)
            else:
                # Primary: Trailing ADTV descending; Secondary: RSI closeness to 50 ascending
                day_candidates.sort(
                    key=lambda item: (
                        item[1],  # Trailing ADTV
                        -abs((item[0].rsi_14 or Decimal("50.00")) - Decimal("50.00")),
                    ),
                    reverse=True,
                )

            delay_days = 1 if delay_entry_by_one_day else 0
            for cand, adtv in day_candidates:
                pending_queue.append((delay_days, cand, adtv))

        # Assert no positions remain open at end of run (Task 10 / D10)
        assert len(active_positions) == 0, f"Engine invariant violated: {len(active_positions)} positions remained open after end of simulation liquidation"

        fill_rate = (
            (total_signals_filled / total_signals_generated * 100.0)
            if total_signals_generated > 0
            else 0.0
        )

        metrics = calculate_comprehensive_metrics(
            trades=completed_trades,
            equity_curve=equity_curve,
            initial_capital=self.config.initial_capital,
        )

        return {
            "metrics": metrics,
            "strategy_id": strategy.strategy_id,
            "strategy_version": strategy.strategy_version,
            "trades": completed_trades,
            "equity_curve": equity_curve,
            "total_signals_generated": total_signals_generated,
            "total_signals_filled": total_signals_filled,
            "fill_rate_pct": round(fill_rate, 2),
            "killswitch_triggers": killswitch_triggers,
            "killswitch_triggered_days": killswitch_triggered_days,
            "regime_blocked_days": regime_blocked_days,
            "start_date": sorted_dates[0],
            "end_date": sorted_dates[-1],
        }

    # Alias for run_simulation
    run = run_simulation
