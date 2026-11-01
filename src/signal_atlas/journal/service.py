"""
service.py - Trade Journal & Paper Trading Application Service Layer.

Provides deterministic persistence, lifecycle management, and financial accounting
for manual and paper-trading decisions adhering to Architecture Sections 12 and 14.2:
- Strict segregation: Journal writes must never place orders, change broker holdings,
  or mutate historical market data / backtest parameters.
- Comprehensive cost modeling: Employs TransactionCostModel for all-inclusive
  statutory Indian charges (STT, stamp duty, exchange turnover fee, SEBI, GST).
- Execution auditability: Compares planned geometry vs actual fills to track slippage,
  realized R-multiples, and behavioral errors.
"""

import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
import uuid
from sqlalchemy import select, and_, desc
from sqlalchemy.orm import Session

from signal_atlas.backtest.costs import TransactionCostModel
from signal_atlas.db.models.journal import JournalEntryRecord
from signal_atlas.db.session import get_db
from signal_atlas.journal.models import (
    ExitReason,
    JournalDecision,
    JournalEntry,
    JournalStatus,
    JournalSummary,
)


class JournalService:
    """
    Pure application service managing trade journal records and paper-trading performance.
    """

    def __init__(self, cost_model: Optional[TransactionCostModel] = None):
        self.cost_model = cost_model or TransactionCostModel()

    def record_decision(
        self,
        symbol: str,
        signal_date: datetime.date,
        decision: JournalDecision | str,
        planned_entry_price: Decimal,
        planned_stop_loss: Decimal,
        planned_target_price: Decimal,
        planned_quantity: int,
        planned_risk_amount: Optional[Decimal] = None,
        planned_reward_to_risk: Optional[Decimal] = None,
        decision_reason: Optional[str] = None,
        actual_entry_date: Optional[datetime.date] = None,
        actual_entry_price: Optional[Decimal] = None,
        actual_quantity: Optional[int] = None,
        strategy_id: str = "trend_pullback",
        strategy_version: str = "v1.0",
        notes: Optional[str] = None,
        tags: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> JournalEntry:
        """
        Records a taken or skipped trade decision for a signal.
        """
        symbol_clean = symbol.strip().upper()
        if not symbol_clean:
            raise ValueError("Symbol is required")

        if isinstance(decision, str):
            try:
                dec = JournalDecision(decision.upper())
            except ValueError:
                raise ValueError(f"Invalid decision '{decision}'. Must be TAKEN or SKIPPED.")
        else:
            dec = decision

        # Validate planned geometry
        if planned_entry_price <= Decimal("0"):
            raise ValueError(f"Planned entry price must be positive, got {planned_entry_price}")
        if planned_stop_loss <= Decimal("0") or planned_stop_loss >= planned_entry_price:
            raise ValueError(f"Planned stop loss ({planned_stop_loss}) must be positive and below entry ({planned_entry_price})")
        if planned_quantity <= 0:
            raise ValueError(f"Planned quantity must be positive, got {planned_quantity}")

        # Compute derived planned risk and R:R if not provided
        if planned_risk_amount is None:
            risk_per_share = planned_entry_price - planned_stop_loss
            planned_risk_amount = (risk_per_share * Decimal(planned_quantity)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        if planned_reward_to_risk is None:
            risk_per_share = planned_entry_price - planned_stop_loss
            reward_per_share = planned_target_price - planned_entry_price
            if risk_per_share > Decimal("0"):
                planned_reward_to_risk = (reward_per_share / risk_per_share).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            else:
                planned_reward_to_risk = Decimal("0.00")

        # Determine lifecycle and actual execution attributes
        if dec == JournalDecision.TAKEN:
            status = JournalStatus.OPEN
            act_entry_price = actual_entry_price if actual_entry_price is not None else planned_entry_price
            act_entry_date = actual_entry_date if actual_entry_date is not None else (signal_date + datetime.timedelta(days=1))
            act_qty = actual_quantity if actual_quantity is not None else planned_quantity

            if act_entry_price <= Decimal("0"):
                raise ValueError(f"Actual entry price must be positive, got {act_entry_price}")
            if act_qty <= 0:
                raise ValueError(f"Actual quantity must be positive, got {act_qty}")

            slippage = (act_entry_price - planned_entry_price).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            status = JournalStatus.SKIPPED
            act_entry_price = None
            act_entry_date = None
            act_qty = None
            slippage = None

        # Generate unique entry_id
        short_id = uuid.uuid4().hex[:8]
        entry_id = f"JRN-{signal_date.strftime('%Y%m%d')}-{symbol_clean}-{short_id}"

        now = datetime.datetime.now(datetime.timezone.utc)
        record = JournalEntryRecord(
            entry_id=entry_id,
            symbol=symbol_clean,
            signal_date=signal_date,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            decision=dec.value,
            decision_reason=decision_reason,
            status=status.value,
            planned_entry_price=planned_entry_price,
            planned_stop_loss=planned_stop_loss,
            planned_target_price=planned_target_price,
            planned_quantity=planned_quantity,
            planned_risk_amount=planned_risk_amount,
            planned_reward_to_risk=planned_reward_to_risk,
            actual_entry_date=act_entry_date,
            actual_entry_price=act_entry_price,
            actual_quantity=act_qty,
            entry_slippage=slippage,
            notes=notes,
            tags=tags,
            created_at=now,
            updated_at=now,
        )

        def _persist(s: Session) -> JournalEntry:
            s.add(record)
            s.commit()
            s.refresh(record)
            return JournalEntry.model_validate(record)

        if db is not None:
            return _persist(db)
        with get_db() as session:
            return _persist(session)

    def close_entry(
        self,
        entry_id: str,
        exit_date: datetime.date,
        exit_price: Decimal,
        exit_reason: ExitReason | str = ExitReason.MANUAL,
        notes: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> JournalEntry:
        """
        Closes an active OPEN journal trade with exit details and calculates all financial metrics.
        """
        if exit_price <= Decimal("0"):
            raise ValueError(f"Exit price must be positive, got {exit_price}")

        reason_str = exit_reason.value if isinstance(exit_reason, ExitReason) else str(exit_reason)

        def _do_close(s: Session) -> JournalEntry:
            record = s.get(JournalEntryRecord, entry_id)
            if not record:
                raise ValueError(f"Journal entry '{entry_id}' not found")

            if record.status != JournalStatus.OPEN.value:
                raise ValueError(
                    f"Cannot close journal entry '{entry_id}' in '{record.status}' status; "
                    f"only OPEN entries can be closed."
                )

            if record.actual_entry_date and exit_date < record.actual_entry_date:
                raise ValueError(
                    f"Exit date {exit_date} cannot precede actual entry date {record.actual_entry_date}"
                )

            qty = record.actual_quantity or record.planned_quantity
            entry_p = record.actual_entry_price or record.planned_entry_price

            # Calculate gross P&L
            gross_pnl = ((exit_price - entry_p) * Decimal(qty)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Calculate exact regulatory and execution transaction costs
            buy_costs = self.cost_model.calculate_buy_costs(price=entry_p, quantity=qty)
            sell_costs = self.cost_model.calculate_sell_costs(price=exit_price, quantity=qty)
            total_costs = (buy_costs.total_charges + sell_costs.total_charges).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            net_pnl = (gross_pnl - total_costs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            capital_outlay = entry_p * Decimal(qty)
            pnl_pct = (net_pnl / capital_outlay).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

            # R-Multiple calculation: Net P&L / Initial Planned Risk
            planned_risk = record.planned_risk_amount
            if planned_risk and planned_risk > Decimal("0"):
                r_multiple = (net_pnl / planned_risk).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                r_multiple = Decimal("0.00")

            now = datetime.datetime.now(datetime.timezone.utc)
            record.status = JournalStatus.CLOSED.value
            record.actual_exit_date = exit_date
            record.actual_exit_price = exit_price
            record.exit_reason = reason_str
            record.realized_gross_pnl = gross_pnl
            record.realized_costs = total_costs
            record.realized_net_pnl = net_pnl
            record.realized_pnl_pct = pnl_pct
            record.realized_r_multiple = r_multiple
            record.closed_at = now
            record.updated_at = now

            if notes:
                existing_notes = record.notes or ""
                record.notes = f"{existing_notes}\n[Exit Note {exit_date}]: {notes}".strip()

            s.commit()
            s.refresh(record)
            return JournalEntry.model_validate(record)

        if db is not None:
            return _do_close(db)
        with get_db() as session:
            return _do_close(session)

    def cancel_entry(
        self,
        entry_id: str,
        reason: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> JournalEntry:
        """
        Cancels an open journal entry (e.g., unfilled order, rule invalidation prior to fill).
        """
        def _do_cancel(s: Session) -> JournalEntry:
            record = s.get(JournalEntryRecord, entry_id)
            if not record:
                raise ValueError(f"Journal entry '{entry_id}' not found")

            if record.status != JournalStatus.OPEN.value:
                raise ValueError(f"Cannot cancel entry '{entry_id}' in '{record.status}' status")

            now = datetime.datetime.now(datetime.timezone.utc)
            record.status = JournalStatus.CANCELLED.value
            record.updated_at = now
            if reason:
                existing_notes = record.notes or ""
                record.notes = f"{existing_notes}\n[Cancellation]: {reason}".strip()

            s.commit()
            s.refresh(record)
            return JournalEntry.model_validate(record)

        if db is not None:
            return _do_cancel(db)
        with get_db() as session:
            return _do_cancel(session)

    def get_entry(self, entry_id: str, db: Optional[Session] = None) -> Optional[JournalEntry]:
        """
        Retrieves a single journal entry by ID.
        """
        def _get(s: Session) -> Optional[JournalEntry]:
            record = s.get(JournalEntryRecord, entry_id)
            return JournalEntry.model_validate(record) if record else None

        if db is not None:
            return _get(db)
        with get_db() as session:
            return _get(session)

    def list_entries(
        self,
        status: Optional[JournalStatus | str] = None,
        symbol: Optional[str] = None,
        start_date: Optional[datetime.date] = None,
        end_date: Optional[datetime.date] = None,
        db: Optional[Session] = None,
    ) -> List[JournalEntry]:
        """
        Lists journal entries ordered by signal date descending.
        """
        def _list(s: Session) -> List[JournalEntry]:
            stmt = select(JournalEntryRecord)
            filters = []

            if status is not None:
                stat_val = status.value if isinstance(status, JournalStatus) else str(status).upper()
                filters.append(JournalEntryRecord.status == stat_val)

            if symbol:
                filters.append(JournalEntryRecord.symbol == symbol.strip().upper())

            if start_date:
                filters.append(JournalEntryRecord.signal_date >= start_date)

            if end_date:
                filters.append(JournalEntryRecord.signal_date <= end_date)

            if filters:
                stmt = stmt.where(and_(*filters))

            stmt = stmt.order_by(desc(JournalEntryRecord.signal_date), desc(JournalEntryRecord.created_at))
            records = s.execute(stmt).scalars().all()
            return [JournalEntry.model_validate(r) for r in records]

        if db is not None:
            return _list(db)
        with get_db() as session:
            return _list(session)

    def get_performance_summary(
        self,
        start_date: Optional[datetime.date] = None,
        end_date: Optional[datetime.date] = None,
        db: Optional[Session] = None,
    ) -> JournalSummary:
        """
        Computes aggregate paper-trading performance analytics across logged signals and closed positions.
        """
        entries = self.list_entries(start_date=start_date, end_date=end_date, db=db)

        total_signals = len(entries)
        taken_count = sum(1 for e in entries if e.decision == JournalDecision.TAKEN)
        skipped_count = sum(1 for e in entries if e.decision == JournalDecision.SKIPPED)
        open_count = sum(1 for e in entries if e.status == JournalStatus.OPEN)
        closed_count = sum(1 for e in entries if e.status == JournalStatus.CLOSED)
        cancelled_count = sum(1 for e in entries if e.status == JournalStatus.CANCELLED)

        closed_entries = [e for e in entries if e.status == JournalStatus.CLOSED]

        win_count = 0
        loss_count = 0
        breakeven_count = 0

        total_gross = Decimal("0.00")
        total_costs = Decimal("0.00")
        total_net = Decimal("0.00")
        gross_wins = Decimal("0.00")
        gross_losses = Decimal("0.00")

        total_holding_days = 0
        holding_count = 0

        r_multiples: List[Decimal] = []
        slippages: List[Decimal] = []
        wins: List[Decimal] = []
        losses: List[Decimal] = []

        for e in entries:
            if e.entry_slippage is not None:
                slippages.append(e.entry_slippage)

        for e in closed_entries:
            net = e.realized_net_pnl or Decimal("0.00")
            gross = e.realized_gross_pnl or Decimal("0.00")
            costs = e.realized_costs or Decimal("0.00")

            total_gross += gross
            total_costs += costs
            total_net += net

            if net > Decimal("0.00"):
                win_count += 1
                gross_wins += net
                wins.append(net)
            elif net < Decimal("0.00"):
                loss_count += 1
                gross_losses += abs(net)
                losses.append(net)
            else:
                breakeven_count += 1

            if e.realized_r_multiple is not None:
                r_multiples.append(e.realized_r_multiple)

            if e.actual_entry_date and e.actual_exit_date:
                days = (e.actual_exit_date - e.actual_entry_date).days
                total_holding_days += max(0, days)
                holding_count += 1

        win_rate = (
            (Decimal(win_count) / Decimal(closed_count) * Decimal("100.00")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if closed_count > 0
            else Decimal("0.00")
        )

        profit_factor = (
            (gross_wins / gross_losses).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if gross_losses > Decimal("0.00")
            else (Decimal("999.00") if gross_wins > Decimal("0.00") else None)
        )

        avg_trade_pnl = (
            (total_net / Decimal(closed_count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if closed_count > 0
            else Decimal("0.00")
        )

        avg_win = (
            (gross_wins / Decimal(win_count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if win_count > 0
            else Decimal("0.00")
        )

        avg_loss = (
            (gross_losses / Decimal(loss_count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if loss_count > 0
            else Decimal("0.00")
        )

        avg_r = (
            (sum(r_multiples) / Decimal(len(r_multiples))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if r_multiples
            else None
        )

        max_win = max(wins) if wins else Decimal("0.00")
        max_loss = min(losses) if losses else Decimal("0.00")

        avg_holding = (
            (Decimal(total_holding_days) / Decimal(holding_count)).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
            if holding_count > 0
            else Decimal("0.0")
        )

        avg_slippage = (
            (sum(slippages) / Decimal(len(slippages))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if slippages
            else Decimal("0.00")
        )

        return JournalSummary(
            total_signals_logged=total_signals,
            taken_count=taken_count,
            skipped_count=skipped_count,
            open_count=open_count,
            closed_count=closed_count,
            cancelled_count=cancelled_count,
            win_count=win_count,
            loss_count=loss_count,
            breakeven_count=breakeven_count,
            win_rate_pct=win_rate,
            total_gross_pnl=total_gross,
            total_realized_costs=total_costs,
            total_net_pnl=total_net,
            profit_factor=profit_factor,
            avg_trade_pnl=avg_trade_pnl,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_r_multiple=avg_r,
            max_win=max_win,
            max_loss=max_loss,
            avg_holding_days=avg_holding,
            avg_entry_slippage=avg_slippage,
        )
