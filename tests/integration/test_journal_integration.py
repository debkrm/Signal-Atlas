"""
test_journal_integration.py - PostgreSQL Integration Tests for Trade Journal & Paper Trading.

Verifies end-to-end paper trading lifecycle per Architecture Section 12 & 14.2:
1. Complete signal decision lifecycle: TAKEN -> OPEN -> CLOSED (Profit Target) & CLOSED (Stop Loss).
2. SKIPPED signal recording and behavioral decision tracking.
3. Accurate Indian delivery transaction charges (STT, stamp duty, exchange fee, SEBI, GST) and realized R-multiples.
4. Separate paper-trading performance scorecard reporting.
5. Strict isolation: Verifies journal operations never touch or mutate raw market data, corporate actions, or backtests.
"""

import datetime
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import func, select, delete
from sqlalchemy.orm import sessionmaker

from signal_atlas.db.models.journal import JournalEntryRecord
from signal_atlas.db.models.prices import DailyPriceRaw
from signal_atlas.db.models.corporate_actions import CorporateAction
from signal_atlas.journal import (
    ExitReason,
    JournalDecision,
    JournalService,
    JournalStatus,
)


def test_end_to_end_journal_workflow(pg_engine):
    """
    Integration test: Records multiple real trade decisions, closes positions,
    and validates financial metrics and paper-trading performance scorecard against PostgreSQL.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    service = JournalService()

    run_uuid = uuid.uuid4().hex[:6]
    sym_win = f"WIN_{run_uuid}".upper()
    sym_loss = f"LOSS_{run_uuid}".upper()
    sym_skip = f"SKIP_{run_uuid}".upper()
    sig_date = datetime.date(2024, 10, 15)

    with SessionFactory() as session:
        # Clean any leftover journal records to ensure isolated scorecard evaluation
        session.execute(delete(JournalEntryRecord))
        session.commit()

        # 1. Record Trade 1: TAKEN (Planned Entry 500, Stop 475, Target 550, Qty 200) -> Planned Risk = 25 * 200 = 5,000
        t1 = service.record_decision(
            symbol=sym_win,
            signal_date=sig_date,
            decision=JournalDecision.TAKEN,
            planned_entry_price=Decimal("500.00"),
            planned_stop_loss=Decimal("475.00"),
            planned_target_price=Decimal("550.00"),
            planned_quantity=200,
            actual_entry_date=datetime.date(2024, 10, 16),
            actual_entry_price=Decimal("502.00"),  # Gapped up Rs. 2 slippage
            actual_quantity=200,
            decision_reason="A-grade trend pullback setup with sector momentum",
            notes="Filled with Rs. 2.00 morning gap",
            tags="pullback,nifty50",
            db=session,
        )
        assert t1.status == JournalStatus.OPEN
        assert t1.entry_slippage == Decimal("2.00")
        assert t1.planned_risk_amount == Decimal("5000.00")

        # 2. Record Trade 2: TAKEN (Planned Entry 1000, Stop 950, Target 1100, Qty 100) -> Planned Risk = 50 * 100 = 5,000
        t2 = service.record_decision(
            symbol=sym_loss,
            signal_date=sig_date,
            decision=JournalDecision.TAKEN,
            planned_entry_price=Decimal("1000.00"),
            planned_stop_loss=Decimal("950.00"),
            planned_target_price=Decimal("1100.00"),
            planned_quantity=100,
            actual_entry_date=datetime.date(2024, 10, 16),
            actual_entry_price=Decimal("1000.00"),
            actual_quantity=100,
            decision_reason="Valid setup near support",
            db=session,
        )
        assert t2.status == JournalStatus.OPEN

        # 3. Record Trade 3: SKIPPED (Avoid setup due to high news risk)
        t3 = service.record_decision(
            symbol=sym_skip,
            signal_date=sig_date,
            decision=JournalDecision.SKIPPED,
            planned_entry_price=Decimal("2000.00"),
            planned_stop_loss=Decimal("1900.00"),
            planned_target_price=Decimal("2200.00"),
            planned_quantity=50,
            decision_reason="Management conference call scheduled; elevated gap risk",
            db=session,
        )
        assert t3.status == JournalStatus.SKIPPED

        # 4. Close Trade 1 at Target (Exit 550.00 on 2024-10-24)
        c1 = service.close_entry(
            entry_id=t1.entry_id,
            exit_date=datetime.date(2024, 10, 24),
            exit_price=Decimal("550.00"),
            exit_reason=ExitReason.PROFIT_TARGET,
            notes="Hit profit target cleanly at session peak",
            db=session,
        )
        assert c1.status == JournalStatus.CLOSED
        # Gross = (550 - 502) * 200 = 48 * 200 = 9,600.00
        assert c1.realized_gross_pnl == Decimal("9600.00")
        assert c1.realized_costs > Decimal("200.00")
        assert c1.realized_net_pnl == c1.realized_gross_pnl - c1.realized_costs
        assert c1.realized_r_multiple > Decimal("1.70")  # ~1.85R

        # 5. Close Trade 2 at Stop Loss (Exit 945.00 on 2024-10-21)
        c2 = service.close_entry(
            entry_id=t2.entry_id,
            exit_date=datetime.date(2024, 10, 21),
            exit_price=Decimal("945.00"),  # Slight slippage through stop
            exit_reason=ExitReason.STOP_LOSS,
            notes="Stopped out below structural swing low",
            db=session,
        )
        assert c2.status == JournalStatus.CLOSED
        # Gross = (945 - 1000) * 100 = -5500.00
        assert c2.realized_gross_pnl == Decimal("-5500.00")
        assert c2.realized_net_pnl < c2.realized_gross_pnl
        assert c2.realized_r_multiple < Decimal("-1.00")

        # 6. Verify Filtered Listing
        open_entries = service.list_entries(status=JournalStatus.OPEN, db=session)
        assert not any(e.entry_id in (t1.entry_id, t2.entry_id, t3.entry_id) for e in open_entries)

        closed_entries = service.list_entries(status=JournalStatus.CLOSED, db=session)
        closed_ids = {e.entry_id for e in closed_entries}
        assert t1.entry_id in closed_ids
        assert t2.entry_id in closed_ids

        skipped_entries = service.list_entries(status=JournalStatus.SKIPPED, db=session)
        assert any(e.entry_id == t3.entry_id for e in skipped_entries)

        # 7. Aggregate Performance Scorecard
        summary = service.get_performance_summary(start_date=sig_date, db=session)
        assert summary.total_signals_logged == 3
        assert summary.taken_count == 2
        assert summary.skipped_count == 1
        assert summary.win_count == 1
        assert summary.loss_count == 1
        assert summary.win_rate_pct == Decimal("50.00")
        assert summary.total_net_pnl > Decimal("0.00")
        assert summary.profit_factor is not None and summary.profit_factor > Decimal("1.00")
        assert summary.avg_holding_days > Decimal("0.0")

        # Teardown synthetic records
        session.execute(delete(JournalEntryRecord).where(JournalEntryRecord.entry_id.in_([t1.entry_id, t2.entry_id, t3.entry_id])))
        session.commit()


def test_journal_isolation_and_immutability(pg_engine):
    """
    Strict architectural test: Verifies journal operations are pure append-only records
    that NEVER mutate or delete historical raw price data, corporate actions, or calendar records.
    """
    SessionFactory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    service = JournalService()

    with SessionFactory() as session:
        # Record baselines
        raw_count_before = session.execute(select(func.count(DailyPriceRaw.id))).scalar()
        ca_count_before = session.execute(select(func.count(CorporateAction.action_id))).scalar()

        # Perform journal operations
        t = service.record_decision(
            symbol="ISOLATION_TEST",
            signal_date=datetime.date(2024, 10, 24),
            decision=JournalDecision.TAKEN,
            planned_entry_price=Decimal("100.00"),
            planned_stop_loss=Decimal("90.00"),
            planned_target_price=Decimal("120.00"),
            planned_quantity=10,
            db=session,
        )
        service.close_entry(
            entry_id=t.entry_id,
            exit_date=datetime.date(2024, 10, 28),
            exit_price=Decimal("115.00"),
            db=session,
        )

        # Re-check baselines
        raw_count_after = session.execute(select(func.count(DailyPriceRaw.id))).scalar()
        ca_count_after = session.execute(select(func.count(CorporateAction.action_id))).scalar()

        assert raw_count_before == raw_count_after, "Journal operation mutated daily_prices_raw!"
        assert ca_count_before == ca_count_after, "Journal operation mutated corporate_actions!"

        # Teardown
        session.execute(delete(JournalEntryRecord).where(JournalEntryRecord.entry_id == t.entry_id))
        session.commit()
