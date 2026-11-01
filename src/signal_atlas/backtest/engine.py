"""
engine.py - Production Backtesting Event Loop for Signal Atlas.

Strictly follows backtest_and_tuning_plan.md and Section 2.2 / 8.3 of Architecture:
- Next-session (t+1) opening fills with entry variants (A: Open+Slippage with R:R recheck, B: Limit order, C: Pessimistic limit).
- Conservative dual-touch ambiguity resolution: if daily bar touches both stop and target, stop loss is assumed hit first.
- Gap-through-stop at open: if bar opens at or below stop, fills at open (tracking gap losses in R).
- Time stop: configurable holding sessions.
- Full Indian delivery cost model: STT, stamp duty, exchange fee, SEBI fee, DP charges (₹15.93 on sell), GST, and slippage.
- Portfolio risk limits: 1% equity risk per trade, max 10 positions, max 6% open risk cap, 10% drawdown killswitch.
- Market regime gate: NIFTYBEES > EMA50 evaluated at day t close (zero lookahead).
"""

import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple
import uuid

from signal_atlas.backtest.costs import ExecutionCostBreakdown, TransactionCostModel
from signal_atlas.backtest.models import (
    BacktestConfig,
    EquitySnapshot,
    ExitReason,
    PositionRecord,
)
from signal_atlas.features.engine import TechnicalFeatureEngine
from signal_atlas.features.indicators import compute_ema
from signal_atlas.quality.adjustment import AdjustedPriceRecord
from signal_atlas.strategy.base import Strategy
from signal_atlas.strategy.models import MarketContext, SignalState, StrategyCandidate


class EntryVariant(str, Enum):
    A = "A"  # Primary: t+1 open + slippage, skip if R:R < min or open > entry_zone_high
    B = "B"  # Limit order: fill at open if open <= entry, else entry if low <= entry
    C = "C"  # Pessimistic limit: require low < entry by at least 1 tick (0.05)


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


class BacktestEngineConfig(BacktestConfig):
    entry_variant: EntryVariant = EntryVariant.A
    max_total_open_risk_pct: Decimal = Decimal("0.06")  # 6% open risk cap
    drawdown_killswitch_pct: Decimal = Decimal("0.10")   # 10% drawdown halt
    killswitch_cooldown_sessions: Optional[int] = 20    # Re-enable after 20 sessions cooldown
    dp_charge_per_scrip: Decimal = Decimal("15.93")     # ₹13.50 + 18% GST on delivery sell
    gate_enabled: bool = True
    benchmark_ema_period: int = 50
    tick_size: Decimal = Decimal("0.05")


class BacktestEngine:
    """
    Event-driven simulation engine strictly executing live risk policies.
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
        ignore_regime: bool = False,
        entry_variant: Optional[EntryVariant] = None,
        stress_costs: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes backtest over chronological trading_dates.
        """
        if not trading_dates:
            raise ValueError("trading_dates cannot be empty")

        sorted_dates = sorted(trading_dates)
        variant = entry_variant or self.config.entry_variant

        cost_model = TransactionCostModel(
            brokerage_per_order=Decimal("0.00"),
            brokerage_pct=Decimal("0.0003"),
            stt_rate=Decimal("0.0010"),
            exchange_rate=Decimal("0.0000297"),
            sebi_rate=Decimal("0.000001"),
            stamp_duty_buy_rate=Decimal("0.00015"),
            gst_rate=Decimal("0.18"),
            slippage_bps=Decimal("0.0025") if stress_costs else Decimal("0.0010"),
        )
        dp_charge = self.config.dp_charge_per_scrip

        feature_engine = TechnicalFeatureEngine(min_required_sessions=self.config.min_history_sessions)

        # 1. Index instrument prices by (inst_id, date)
        price_lookup: Dict[str, Dict[datetime.date, AdjustedPriceRecord]] = {}
        history_up_to: Dict[str, List[AdjustedPriceRecord]] = {inst_id: [] for inst_id in prices_by_instrument}
        for inst_id, recs in prices_by_instrument.items():
            price_lookup[inst_id] = {r.trade_date: r for r in recs}

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
        peak_equity: Decimal = cash
        active_positions: Dict[str, ActiveTrade] = {}
        completed_trades: List[PositionRecord] = []
        equity_curve: List[EquitySnapshot] = []

        total_signals_generated = 0
        total_signals_filled = 0
        killswitch_triggered_days = 0
        regime_blocked_days = 0

        pending_candidates: List[StrategyCandidate] = []

        # Sort all instrument records chronologically
        sorted_inst_recs: Dict[str, List[AdjustedPriceRecord]] = {
            inst_id: sorted(recs, key=lambda r: r.trade_date)
            for inst_id, recs in prices_by_instrument.items()
        }

        # Pointer per instrument for fast O(1) history slice
        inst_indices: Dict[str, int] = {inst_id: 0 for inst_id in prices_by_instrument}

        for d_idx, curr_date in enumerate(sorted_dates):
            # Advance instrument histories up to curr_date
            for inst_id, recs in sorted_inst_recs.items():
                idx = inst_indices[inst_id]
                while idx < len(recs) and recs[idx].trade_date <= curr_date:
                    history_up_to[inst_id].append(recs[idx])
                    idx += 1
                inst_indices[inst_id] = idx

            # -----------------------------------------------------------------
            # STEP 1: Morning Open Bell Fills (Gap Exits & New Entries)
            # -----------------------------------------------------------------
            closed_this_day: List[str] = []

            # 1a. Gap-down exits at Open (open <= stop_loss)
            for inst_id, pos in list(active_positions.items()):
                bar = price_lookup.get(inst_id, {}).get(curr_date)
                if not bar:
                    continue
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
                            trade_id=pos.trade_id,
                            instrument_id=pos.instrument_id,
                            symbol=pos.symbol,
                            entry_date=pos.entry_date,
                            entry_price=pos.entry_price,
                            quantity=pos.quantity,
                            entry_gross_value=gross_val_entry,
                            entry_fees=pos.entry_fees,
                            initial_stop_loss=pos.stop_loss,
                            initial_target_price=pos.target_price,
                            initial_risk_per_share=pos.risk_per_share,
                            exit_date=curr_date,
                            exit_price=bar.open,
                            exit_gross_value=gross_val_exit,
                            exit_fees=total_exit_fees,
                            exit_reason=ExitReason.STOP_LOSS,
                            holding_sessions_count=pos.holding_sessions,
                            gross_pnl=gross_pnl,
                            net_pnl=net_pnl,
                            net_return_pct=net_return,
                            realized_r_multiple=realized_r,
                        )
                    )
                    closed_this_day.append(inst_id)

            for inst_id in closed_this_day:
                del active_positions[inst_id]
            closed_this_day = []

            # 1b. Mark-to-open equity to check killswitch & position sizing
            open_positions_val = Decimal("0.00")
            current_open_risk = Decimal("0.00")
            for inst_id, pos in active_positions.items():
                b = price_lookup.get(inst_id, {}).get(curr_date)
                ref_p = b.open if b else pos.entry_price
                open_positions_val += ref_p * Decimal(pos.quantity)
                current_open_risk += pos.risk_per_share * Decimal(pos.quantity)

            current_equity = cash + open_positions_val
            drawdown = (
                (peak_equity - current_equity) / peak_equity
                if peak_equity > Decimal("0")
                else Decimal("0")
            )

            is_killswitch_active = drawdown >= self.config.drawdown_killswitch_pct
            if is_killswitch_active:
                killswitch_triggered_days += 1

            # 1c. Process New Entries (if killswitch is not active)
            if not is_killswitch_active and pending_candidates:
                max_open_risk_allowed = current_equity * self.config.max_total_open_risk_pct

                for cand in pending_candidates:
                    if len(active_positions) >= self.config.max_concurrent_positions:
                        break
                    if cand.instrument_id in active_positions:
                        continue

                    bar = price_lookup.get(cand.instrument_id, {}).get(curr_date)
                    if not bar:
                        continue

                    # Evaluate Entry Variant
                    fill_p: Optional[Decimal] = None
                    if variant == EntryVariant.A:
                        # Primary: Open + slippage
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
                        # Pessimistic limit: low < entry by at least 1 tick
                        if bar.open < cand.entry_reference:
                            fill_p = bar.open
                        elif bar.low <= (cand.entry_reference - self.config.tick_size):
                            fill_p = cand.entry_reference

                    if fill_p is None:
                        continue

                    # Check risk per share at fill
                    risk_per_sh = fill_p - cand.stop_loss
                    if risk_per_sh <= Decimal("0"):
                        continue

                    # Recalculate R:R for variant B & C if needed
                    reward_per_sh = cand.target_price - fill_p
                    effective_rr = (reward_per_sh / risk_per_sh).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if effective_rr < Decimal("1.50"):
                        continue

                    # Sizing: q_risk
                    risk_budget = current_equity * self.config.risk_per_trade_pct
                    q_risk = int((risk_budget / risk_per_sh).quantize(Decimal("1"), rounding=ROUND_DOWN))

                    # Sizing: q_capital (max 20% equity)
                    cap_budget = min(cash, current_equity * self.config.max_capital_per_position_pct)
                    q_capital = int((cap_budget / fill_p).quantize(Decimal("1"), rounding=ROUND_DOWN))

                    # Sizing: q_adtv (2% ADTV)
                    q_adtv = q_capital
                    if bar.traded_value and bar.traded_value > Decimal("0"):
                        max_vol = int((bar.traded_value * self.config.max_adtv_participation_pct / fill_p).quantize(Decimal("1"), rounding=ROUND_DOWN))
                        q_adtv = max(1, max_vol)

                    qty = min(q_risk, q_capital, q_adtv)
                    if qty <= 0:
                        continue

                    # Portfolio rule: Max 6% total open risk
                    trade_risk = risk_per_sh * Decimal(qty)
                    if (current_open_risk + trade_risk) > max_open_risk_allowed:
                        remaining_risk_budget = max_open_risk_allowed - current_open_risk
                        if remaining_risk_budget <= Decimal("0"):
                            continue
                        qty = int((remaining_risk_budget / risk_per_sh).quantize(Decimal("1"), rounding=ROUND_DOWN))
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
                        trade_id=f"TRD-{uuid.uuid4().hex[:8]}",
                        instrument_id=cand.instrument_id,
                        symbol=cand.symbol,
                        entry_date=curr_date,
                        entry_price=fill_p,
                        quantity=qty,
                        entry_fees=buy_breakdown.total_charges,
                        stop_loss=cand.stop_loss,
                        target_price=cand.target_price,
                        risk_per_share=risk_per_sh,
                    )

            pending_candidates = []

            # -----------------------------------------------------------------
            # STEP 2: Intraday Price Action & Session Exits
            # -----------------------------------------------------------------
            for inst_id, pos in list(active_positions.items()):
                pos.holding_sessions += 1
                bar = price_lookup.get(inst_id, {}).get(curr_date)
                if not bar:
                    continue

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
                # Rule 5: Final session liquidation
                elif d_idx == len(sorted_dates) - 1:
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
                            trade_id=pos.trade_id,
                            instrument_id=pos.instrument_id,
                            symbol=pos.symbol,
                            entry_date=pos.entry_date,
                            entry_price=pos.entry_price,
                            quantity=pos.quantity,
                            entry_gross_value=gross_val_entry,
                            entry_fees=pos.entry_fees,
                            initial_stop_loss=pos.stop_loss,
                            initial_target_price=pos.target_price,
                            initial_risk_per_share=pos.risk_per_share,
                            exit_date=curr_date,
                            exit_price=exit_price,
                            exit_gross_value=gross_val_exit,
                            exit_fees=total_exit_fees,
                            exit_reason=exit_reason,
                            holding_sessions_count=pos.holding_sessions,
                            gross_pnl=gross_pnl,
                            net_pnl=net_pnl,
                            net_return_pct=net_return,
                            realized_r_multiple=realized_r,
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
                cp = b.close if b else pos.entry_price
                eod_positions_val += cp * Decimal(pos.quantity)

            eod_equity = cash + eod_positions_val
            if eod_equity > peak_equity:
                peak_equity = eod_equity

            dd_pct = (
                ((peak_equity - eod_equity) / peak_equity * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if peak_equity > Decimal("0")
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

            # -----------------------------------------------------------------
            # STEP 4: Strategy Evaluation at Day t Close for Day t+1
            # -----------------------------------------------------------------
            # Market regime check on day t close
            is_bullish = True
            if self.config.gate_enabled and not ignore_regime:
                b_rec = bench_by_date.get(curr_date)
                b_ema = bench_ema_by_date.get(curr_date)
                if b_rec and b_ema:
                    is_bullish = b_rec.close > b_ema
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

            day_candidates: List[StrategyCandidate] = []
            for inst_id, history in history_up_to.items():
                if len(history) < self.config.min_history_sessions:
                    continue
                sym = (
                    (symbols_by_instrument or {}).get(inst_id)
                    or getattr(history[-1], "symbol", None)
                    or inst_id
                )
                feats = feature_engine.extract_features(
                    instrument_id=inst_id,
                    symbol=sym,
                    as_of_date=curr_date,
                    records=history,
                )
                cand = strategy.evaluate_candidate(feats, mkt_ctx)
                if cand.signal_state == SignalState.BUY and cand.is_valid:
                    day_candidates.append(cand)
                    total_signals_generated += 1

            # Rank candidates by reward-to-risk descending
            day_candidates.sort(key=lambda c: -c.reward_to_risk)
            pending_candidates = day_candidates

        fill_rate = (
            (total_signals_filled / total_signals_generated * 100.0)
            if total_signals_generated > 0
            else 0.0
        )

        return {
            "strategy_id": strategy.strategy_id,
            "strategy_version": strategy.strategy_version,
            "trades": completed_trades,
            "equity_curve": equity_curve,
            "total_signals_generated": total_signals_generated,
            "total_signals_filled": total_signals_filled,
            "fill_rate_pct": round(fill_rate, 2),
            "killswitch_triggered_days": killswitch_triggered_days,
            "regime_blocked_days": regime_blocked_days,
            "start_date": sorted_dates[0],
            "end_date": sorted_dates[-1],
        }
