"""add retrieved_at to corporate_actions and create daily_prices_adjusted table

Revision ID: 0007_adjusted_prices_and_provenance
Revises: 0006_expand_ca_status_length
Create Date: 2026-10-31

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007_adjusted_prices"
down_revision: Union[str, None] = "0006_expand_ca_status_length"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add retrieved_at to corporate_actions
    op.add_column("corporate_actions", sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True))

    # 2. Create daily_prices_adjusted table
    op.create_table(
        "daily_prices_adjusted",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("series", sa.String(length=16), nullable=False),
        sa.Column("open", sa.Numeric(precision=16, scale=6), nullable=False),
        sa.Column("high", sa.Numeric(precision=16, scale=6), nullable=False),
        sa.Column("low", sa.Numeric(precision=16, scale=6), nullable=False),
        sa.Column("close", sa.Numeric(precision=16, scale=6), nullable=False),
        sa.Column("last", sa.Numeric(precision=16, scale=6), nullable=True),
        sa.Column("prev_close", sa.Numeric(precision=16, scale=6), nullable=False),
        sa.Column("volume", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("raw_volume", sa.BigInteger(), nullable=False),
        sa.Column("traded_value", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cumulative_multiplier", sa.Numeric(precision=12, scale=6), server_default="1.0", nullable=False),
        sa.Column("applied_action_ids", sa.String(length=512), nullable=True),
        sa.Column("adjustment_version", sa.String(length=32), server_default="v1.0", nullable=False),
        sa.Column("adjustment_run_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.instrument_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id", "trade_date", "series", "adjustment_version", name="uq_adj_price_inst_date_series_ver"),
    )
    op.create_index("ix_adj_prices_inst_date", "daily_prices_adjusted", ["instrument_id", "trade_date"], unique=False)
    op.create_index("ix_adj_prices_date_series", "daily_prices_adjusted", ["trade_date", "series"], unique=False)
    op.create_index("ix_adj_prices_run_id", "daily_prices_adjusted", ["adjustment_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_adj_prices_run_id", table_name="daily_prices_adjusted")
    op.drop_index("ix_adj_prices_date_series", table_name="daily_prices_adjusted")
    op.drop_index("ix_adj_prices_inst_date", table_name="daily_prices_adjusted")
    op.drop_table("daily_prices_adjusted")
    op.drop_column("corporate_actions", "retrieved_at")
