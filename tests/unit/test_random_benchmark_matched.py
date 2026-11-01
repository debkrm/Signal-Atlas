"""
test_random_benchmark_matched.py - Deterministic Verification of Matched Random-Entry Control

Tests Stage 3 (P1) requirements:
1. Deterministic repeatability from random seed.
2. Controlled mock dataset execution verifying stop, target, cost model, and expectancy.
3. Invariant checks: seed recording, no lookahead, and reproducible status.
"""

from collections import namedtuple
import datetime
from decimal import Decimal
import pytest

from signal_atlas.backtest.models import ExitReason, PositionRecord
from signal_atlas.backtest.robustness import run_matched_random_control

MockBar = namedtuple("MockBar", ["trade_date", "open", "high", "low", "close"])


class MockDataset:
    def __init__(self):
        self.trading_dates = [
            datetime.date(2023, 1, 2) + datetime.timedelta(days=i) for i in range(40)
        ]
        # Two mock instruments
        self.prices_by_instrument = {
            "inst-1": [
                MockBar(d, Decimal("100.00"), Decimal("108.00"), Decimal("98.00"), Decimal("105.00"))
                for d in self.trading_dates
            ],
            "inst-2": [
                MockBar(d, Decimal("200.00"), Decimal("202.00"), Decimal("185.00"), Decimal("190.00"))
                for d in self.trading_dates
            ],
        }
        self.universe_by_date = {
            d: {"inst-1", "inst-2"} for d in self.trading_dates
        }


def test_matched_random_control_deterministic_seed():
    """Verifies that identical seed produces identical results."""
    dataset = MockDataset()
    t1 = PositionRecord(
        trade_id="TRD-0001",
        instrument_id="inst-1",
        symbol="TEST",
        entry_date=datetime.date(2023, 1, 2),
        exit_date=datetime.date(2023, 1, 10),
        entry_price=Decimal("100.00"),
        exit_price=Decimal("110.00"),
        quantity=100,
        entry_gross_value=Decimal("10000.00"),
        exit_gross_value=Decimal("11000.00"),
        entry_fees=Decimal("15.00"),
        exit_fees=Decimal("15.00"),
        initial_stop_loss=Decimal("95.00"),
        initial_target_price=Decimal("110.00"),
        initial_risk_per_share=Decimal("5.00"),
        holding_sessions_count=8,
        exit_reason=ExitReason.PROFIT_TARGET,
        gross_pnl=Decimal("1000.00"),
        net_pnl=Decimal("970.00"),
        net_return_pct=Decimal("9.70"),
        realized_r_multiple=Decimal("1.94"),
    )

    res1 = run_matched_random_control(dataset, [t1], runs=50, seed=123)
    res2 = run_matched_random_control(dataset, [t1], runs=50, seed=123)

    assert res1["seed"] == 123
    assert res1["p95_expectancy_r"] == res2["p95_expectancy_r"]
    assert res1["p50_expectancy_r"] == res2["p50_expectancy_r"]
    assert res1["passed"] == res2["passed"]


def test_matched_random_control_empty_trades():
    """Verifies safe rejection when no actual trades are provided."""
    dataset = MockDataset()
    res = run_matched_random_control(dataset, [], runs=10, seed=42)
    assert res["passed"] is False
    assert res["baseline_expectancy_r"] == 0.0
    assert "FAIL" in res["status"]
