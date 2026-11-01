"""create trade journal entries table

Revision ID: 0013_trade_journal
Revises: 0012_provenance_and_full_hashes
Create Date: 2026-11-01 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0013_trade_journal"
down_revision: Union[str, None] = "0012_provenance_and_full_hashes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "journal_entries",
        sa.Column("entry_id", sa.String(length=64), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False, server_default="trend_pullback"),
        sa.Column("strategy_version", sa.String(length=32), nullable=False, server_default="v1.0"),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("planned_entry_price", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("planned_stop_loss", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("planned_target_price", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("planned_quantity", sa.Integer(), nullable=False),
        sa.Column("planned_risk_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("planned_reward_to_risk", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("actual_entry_date", sa.Date(), nullable=True),
        sa.Column("actual_entry_price", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("actual_quantity", sa.Integer(), nullable=True),
        sa.Column("actual_exit_date", sa.Date(), nullable=True),
        sa.Column("actual_exit_price", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("exit_reason", sa.String(length=32), nullable=True),
        sa.Column("entry_slippage", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("realized_gross_pnl", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("realized_costs", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("realized_net_pnl", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("realized_pnl_pct", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("realized_r_multiple", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tags", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_journal_entries_symbol", "journal_entries", ["symbol"])
    op.create_index("ix_journal_entries_signal_date", "journal_entries", ["signal_date"])
    op.create_index("ix_journal_entries_status", "journal_entries", ["status"])
    op.create_index("ix_journal_entries_actual_exit_date", "journal_entries", ["actual_exit_date"])


def downgrade() -> None:
    op.drop_index("ix_journal_entries_actual_exit_date", table_name="journal_entries")
    op.drop_index("ix_journal_entries_status", table_name="journal_entries")
    op.drop_index("ix_journal_entries_signal_date", table_name="journal_entries")
    op.drop_index("ix_journal_entries_symbol", table_name="journal_entries")
    op.drop_table("journal_entries")
