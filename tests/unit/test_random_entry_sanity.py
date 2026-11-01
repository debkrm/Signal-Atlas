"""
test_random_entry_sanity.py - Unit test verifying random-entry baseline sanity (Task B).

Tests that on a zero-drift random walk price series, random entries with 1:2 R:R
(e.g., 1.5 ATR stop, 3.0 ATR target) with statutory transaction costs and slippage
produce an expected R roughly equal to minus the transaction costs in R (-0.10 R to -0.30 R),
demonstrating that the random baseline simulation is mathematically sound.
"""

from decimal import Decimal, ROUND_HALF_UP
import numpy as np
import pytest


def test_random_entry_zero_drift_sanity():
    # 1. Generate zero-drift random walk price series
    rng = np.random.default_rng(1)
    n_days = 5000
    daily_vol = 0.015  # 1.5% daily volatility
    returns = rng.normal(loc=0.0, scale=daily_vol, size=n_days)
    prices = 100.0 * np.exp(np.cumsum(returns))

    # Pre-calculate statutory costs and slippage rates
    stt_rate = Decimal("0.0010")
    exch_rate = Decimal("0.0000345")
    sebi_rate = Decimal("0.000001")
    stamp_rate = Decimal("0.00015")
    gst_rate = Decimal("0.18")
    slip_rate = Decimal("0.0010")
    dp_charge = Decimal("15.93")

    trades_gross_r = []
    trades_net_r = []

    # Simulate 2,000 trades across the random series for low standard error
    trade_indices = rng.integers(14, n_days - 35, size=2000)

    for idx in trade_indices:
        entry_price = Decimal(str(round(float(prices[idx]), 2)))
        # Stop loss at 3% (1.5x of 2% daily ATR), Target at 6% (3.0x of 2% daily ATR = 2.0 R:R)
        risk_per_share = entry_price * Decimal("0.03")
        target_dist = risk_per_share * Decimal("2.0")

        stop_p = entry_price - risk_per_share
        target_p = entry_price + target_dist

        # Track price over next 30 sessions
        exit_p = entry_price
        exit_hit = False

        for h in range(1, 31):
            curr_p = Decimal(str(round(float(prices[idx + h]), 2)))
            bar_high = curr_p * Decimal("1.008")
            bar_low = curr_p * Decimal("0.992")

            if bar_low <= stop_p:
                exit_p = stop_p
                exit_hit = True
                break
            elif bar_high >= target_p:
                exit_p = target_p
                exit_hit = True
                break

        if not exit_hit:
            exit_p = Decimal(str(round(float(prices[idx + 30]), 2)))

        gross_pnl = exit_p - entry_price
        buy_fees = (entry_price * (slip_rate + stt_rate + exch_rate + sebi_rate + stamp_rate + (exch_rate + sebi_rate) * gst_rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        typical_qty = max(1, int(Decimal("100000.00") / entry_price))
        dp_fee_per_share = (dp_charge / Decimal(typical_qty)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        sell_fees = (exit_p * (slip_rate + stt_rate + exch_rate + sebi_rate + (exch_rate + sebi_rate) * gst_rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) + dp_fee_per_share

        net_pnl = gross_pnl - buy_fees - sell_fees

        gross_r = float(gross_pnl / risk_per_share)
        net_r = float(net_pnl / risk_per_share)

        trades_gross_r.append(gross_r)
        trades_net_r.append(net_r)

    mean_gross_r = float(np.mean(trades_gross_r))
    mean_net_r = float(np.mean(trades_net_r))
    mean_cost_r = mean_gross_r - mean_net_r

    print(f"Mean Gross R: {mean_gross_r:+.4f} R")
    print(f"Mean Net R: {mean_net_r:+.4f} R")
    print(f"Mean Cost in R: {mean_cost_r:.4f} R")

    # Gross R on zero-drift random walk should be near zero (+/- 0.10 R)
    assert abs(mean_gross_r) < 0.10, f"Gross R ({mean_gross_r}) deviated too far from zero drift"

    # Cost in R must be roughly 0.10 to 0.20 R (~0.45% round-trip cost on 3% stop)
    assert 0.10 <= mean_cost_r <= 0.20, f"Cost in R ({mean_cost_r}) out of expected [0.10, 0.20] range"

    # Net R must reflect realistic friction: between -0.30 R and -0.05 R
    assert -0.30 <= mean_net_r <= -0.05, f"Net R ({mean_net_r}) out of expected [-0.30, -0.05] range"
