"""
test_journal.py - Unit Tests for Signal Atlas Trade Journal & Paper Trading Service.
"""

import datetime
from decimal import Decimal
import pytest

from signal_atlas.journal import (
    ExitReason,
    JournalDecision,
    JournalEntry,
    JournalService,
    JournalStatus,
)


def test_record_taken_trade_defaults_and_geometry(test_db):
    """
    Verifies recording a TAKEN trade properly initializes OPEN status,
    defaults actual entry fill to planned geometry, and calculates planned risk.
    """
    service = JournalService()
    sig_date = datetime.date(2024, 10, 24)

    entry = service.record_decision(
        symbol="RELIANCE",
        signal_date=sig_date,
        decision=JournalDecision.TAKEN,
        planned_entry_price=Decimal("1200.00"),
        planned_stop_loss=Decimal("1140.00"),
        planned_target_price=Decimal("1320.00"),
        planned_quantity=100,
        decision_reason="Strong pullback to EMA 20 with benchmark uptrend",
        notes="Executed at morning open",
        tags="momentum,a-setup",
        db=test_db,
    )

    assert entry.symbol == "RELIANCE"
    assert entry.signal_date == sig_date
    assert entry.decision == JournalDecision.TAKEN
    assert entry.status == JournalStatus.OPEN
    assert entry.planned_entry_price == Decimal("1200.00")
    assert entry.planned_stop_loss == Decimal("1140.00")
    assert entry.planned_target_price == Decimal("1320.00")
    assert entry.planned_quantity == 100

    # Planned risk = (1200 - 1140) * 100 = 6000.00
    assert entry.planned_risk_amount == Decimal("6000.00")
    # Planned R:R = (1320 - 1200) / (1200 - 1140) = 120 / 60 = 2.00
    assert entry.planned_reward_to_risk == Decimal("2.00")

    # Default actual fills
    assert entry.actual_entry_price == Decimal("1200.00")
    assert entry.actual_quantity == 100
    assert entry.actual_entry_date == datetime.date(2024, 10, 25)
    assert entry.entry_slippage == Decimal("0.00")
    assert entry.closed_at is None


def test_record_taken_trade_with_custom_fill_and_slippage(test_db):
    """
    Verifies tracking of entry execution slippage when actual fill differs from planned open.
    """
    service = JournalService()
    sig_date = datetime.date(2024, 10, 24)

    entry = service.record_decision(
        symbol="TCS",
        signal_date=sig_date,
        decision=JournalDecision.TAKEN,
        planned_entry_price=Decimal("3500.00"),
        planned_stop_loss=Decimal("3400.00"),
        planned_target_price=Decimal("3700.00"),
        planned_quantity=50,
        actual_entry_date=datetime.date(2024, 10, 25),
        actual_entry_price=Decimal("3512.50"),  # Gapped up 12.50
        actual_quantity=48,
        decision_reason="Took setup despite slight gap",
        db=test_db,
    )

    assert entry.actual_entry_price == Decimal("3512.50")
    assert entry.actual_quantity == 48
    # Slippage = 3512.50 - 3500.00 = +12.50
    assert entry.entry_slippage == Decimal("12.50")


def test_record_skipped_trade_lifecycle(test_db):
    """
    Verifies that skipped trade setups are persisted with SKIPPED status and leave fills empty.
    """
    service = JournalService()
    sig_date = datetime.date(2024, 10, 24)

    entry = service.record_decision(
        symbol="HDFCBANK",
        signal_date=sig_date,
        decision=JournalDecision.SKIPPED,
        planned_entry_price=Decimal("1500.00"),
        planned_stop_loss=Decimal("1450.00"),
        planned_target_price=Decimal("1600.00"),
        planned_quantity=100,
        decision_reason="Approaching quarterly earnings announcement in 3 days",
        db=test_db,
    )

    assert entry.symbol == "HDFCBANK"
    assert entry.decision == JournalDecision.SKIPPED
    assert entry.status == JournalStatus.SKIPPED
    assert entry.actual_entry_price is None
    assert entry.actual_entry_date is None
    assert entry.actual_quantity is None
    assert entry.entry_slippage is None


def test_close_trade_profit_target_financial_accounting(test_db):
    """
    Verifies closing an OPEN trade at profit target computes gross P&L,
    regulatory transaction charges, net P&L, and realized R-multiple.
    """
    service = JournalService()
    sig_date = datetime.date(2024, 10, 24)

    entry = service.record_decision(
        symbol="INFY",
        signal_date=sig_date,
        decision=JournalDecision.TAKEN,
        planned_entry_price=Decimal("1800.00"),
        planned_stop_loss=Decimal("1720.00"),  # Risk = 80/share
        planned_target_price=Decimal("1960.00"),  # Reward = 160/share (2.0R)
        planned_quantity=100,
        db=test_db,
    )

    closed = service.close_entry(
        entry_id=entry.entry_id,
        exit_date=datetime.date(2024, 11, 5),
        exit_price=Decimal("1960.00"),
        exit_reason=ExitReason.PROFIT_TARGET,
        notes="Hit target cleanly on intraday expansion bar",
        db=test_db,
    )

    assert closed.status == JournalStatus.CLOSED
    assert closed.actual_exit_date == datetime.date(2024, 11, 5)
    assert closed.actual_exit_price == Decimal("1960.00")
    assert closed.exit_reason == "PROFIT_TARGET"

    # Gross P&L = (1960 - 1800) * 100 = 16,000.00
    assert closed.realized_gross_pnl == Decimal("16000.00")

    # Transaction costs must be non-zero and realistic for ~1.8L - 1.96L turnover
    assert closed.realized_costs > Decimal("500.00")
    assert closed.realized_net_pnl == closed.realized_gross_pnl - closed.realized_costs
    assert closed.realized_net_pnl > Decimal("15000.00")

    # Planned risk was 80 * 100 = 8000.00
    # R-multiple = Net P&L / 8000.00 ~= 1.9R after friction
    assert closed.realized_r_multiple > Decimal("1.80")
    assert closed.realized_r_multiple <= Decimal("2.00")
    assert "Hit target cleanly" in closed.notes


def test_close_trade_stop_loss_financial_accounting(test_db):
    """
    Verifies closing an OPEN trade at stop loss calculates negative P&L and negative R-multiple.
    """
    service = JournalService()
    sig_date = datetime.date(2024, 10, 24)

    entry = service.record_decision(
        symbol="SBIN",
        signal_date=sig_date,
        decision=JournalDecision.TAKEN,
        planned_entry_price=Decimal("800.00"),
        planned_stop_loss=Decimal("760.00"),  # 40 risk
        planned_target_price=Decimal("880.00"),
        planned_quantity=100,
        db=test_db,
    )

    closed = service.close_entry(
        entry_id=entry.entry_id,
        exit_date=datetime.date(2024, 10, 30),
        exit_price=Decimal("758.00"),  # Slight slippage past stop
        exit_reason=ExitReason.STOP_LOSS,
        notes="Exited on break of swing low",
        db=test_db,
    )

    assert closed.status == JournalStatus.CLOSED
    # Gross P&L = (758 - 800) * 100 = -4200.00
    assert closed.realized_gross_pnl == Decimal("-4200.00")
    # Net P&L is worse than gross due to costs
    assert closed.realized_net_pnl < closed.realized_gross_pnl
    # R-multiple is negative (~ -1.05R to -1.15R)
    assert closed.realized_r_multiple < Decimal("-1.00")


def test_invalid_lifecycle_transitions(test_db):
    """
    Ensures state machine guards prevent illegal operations.
    """
    service = JournalService()
    sig_date = datetime.date(2024, 10, 24)

    # 1. Reject invalid stop loss (stop >= entry)
    with pytest.raises(ValueError, match="Planned stop loss .* must be positive and below entry"):
        service.record_decision(
            symbol="TEST",
            signal_date=sig_date,
            decision=JournalDecision.TAKEN,
            planned_entry_price=Decimal("100.00"),
            planned_stop_loss=Decimal("105.00"),
            planned_target_price=Decimal("120.00"),
            planned_quantity=10,
            db=test_db,
        )

    # 2. Cannot close a SKIPPED entry
    skipped = service.record_decision(
        symbol="TEST2",
        signal_date=sig_date,
        decision=JournalDecision.SKIPPED,
        planned_entry_price=Decimal("100.00"),
        planned_stop_loss=Decimal("90.00"),
        planned_target_price=Decimal("120.00"),
        planned_quantity=10,
        db=test_db,
    )
    with pytest.raises(ValueError, match="Cannot close journal entry .* in 'SKIPPED' status"):
        service.close_entry(
            entry_id=skipped.entry_id,
            exit_date=datetime.date(2024, 10, 26),
            exit_price=Decimal("110.00"),
            db=test_db,
        )

    # 3. Cannot exit prior to actual entry date
    taken = service.record_decision(
        symbol="TEST3",
        signal_date=sig_date,
        decision=JournalDecision.TAKEN,
        planned_entry_price=Decimal("100.00"),
        planned_stop_loss=Decimal("90.00"),
        planned_target_price=Decimal("120.00"),
        planned_quantity=10,
        actual_entry_date=datetime.date(2024, 10, 25),
        db=test_db,
    )
    with pytest.raises(ValueError, match="Exit date .* cannot precede actual entry date"):
        service.close_entry(
            entry_id=taken.entry_id,
            exit_date=datetime.date(2024, 10, 24),
            exit_price=Decimal("110.00"),
            db=test_db,
        )


def test_performance_summary_aggregation(test_db):
    """
    Verifies calculation of overall paper-trading metrics across multiple entries.
    """
    service = JournalService()
    sig_date = datetime.date(2024, 10, 24)

    # Trade 1: Winner (+16k gross)
    t1 = service.record_decision(
        symbol="STOCK1",
        signal_date=sig_date,
        decision=JournalDecision.TAKEN,
        planned_entry_price=Decimal("100.00"),
        planned_stop_loss=Decimal("90.00"),
        planned_target_price=Decimal("120.00"),
        planned_quantity=100,
        db=test_db,
    )
    service.close_entry(
        entry_id=t1.entry_id,
        exit_date=datetime.date(2024, 10, 28),
        exit_price=Decimal("120.00"),
        exit_reason=ExitReason.PROFIT_TARGET,
        db=test_db,
    )

    # Trade 2: Loser (-1k gross)
    t2 = service.record_decision(
        symbol="STOCK2",
        signal_date=sig_date,
        decision=JournalDecision.TAKEN,
        planned_entry_price=Decimal("200.00"),
        planned_stop_loss=Decimal("190.00"),
        planned_target_price=Decimal("220.00"),
        planned_quantity=100,
        db=test_db,
    )
    service.close_entry(
        entry_id=t2.entry_id,
        exit_date=datetime.date(2024, 10, 29),
        exit_price=Decimal("190.00"),
        exit_reason=ExitReason.STOP_LOSS,
        db=test_db,
    )

    # Trade 3: Skipped
    service.record_decision(
        symbol="STOCK3",
        signal_date=sig_date,
        decision=JournalDecision.SKIPPED,
        planned_entry_price=Decimal("300.00"),
        planned_stop_loss=Decimal("280.00"),
        planned_target_price=Decimal("340.00"),
        planned_quantity=50,
        decision_reason="Liquidity too low",
        db=test_db,
    )

    summary = service.get_performance_summary(db=test_db)

    assert summary.total_signals_logged == 3
    assert summary.taken_count == 2
    assert summary.skipped_count == 1
    assert summary.closed_count == 2
    assert summary.win_count == 1
    assert summary.loss_count == 1
    assert summary.win_rate_pct == Decimal("50.00")
    assert summary.total_net_pnl > Decimal("0.00")
    assert summary.profit_factor is not None and summary.profit_factor > Decimal("1.00")
    assert summary.avg_holding_days > Decimal("0.0")
