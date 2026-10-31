"""create daily_price_quarantine table

Revision ID: 0003_daily_price_quarantine
Revises: 0002_daily_prices_unique_series
Create Date: 2026-10-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_daily_price_quarantine"
down_revision: Union[str, None] = "0002_daily_prices_unique_series"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_price_quarantine",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=True),
        sa.Column("series", sa.String(length=16), nullable=True),
        sa.Column("isin", sa.String(length=12), nullable=True),
        sa.Column("instrument_id", sa.String(length=36), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("validation_rule", sa.String(length=64), nullable=False),
        sa.Column("validation_message", sa.String(length=512), nullable=False),
        sa.Column("source_file", sa.String(length=128), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.run_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_daily_price_quarantine_trade_date",
        "daily_price_quarantine",
        ["trade_date"],
        unique=False,
    )
    op.create_index(
        "ix_daily_price_quarantine_symbol",
        "daily_price_quarantine",
        ["symbol"],
        unique=False,
    )
    op.create_index(
        "ix_daily_price_quarantine_isin",
        "daily_price_quarantine",
        ["isin"],
        unique=False,
    )
    op.create_index(
        "ix_daily_price_quarantine_instrument_id",
        "daily_price_quarantine",
        ["instrument_id"],
        unique=False,
    )
    op.create_index(
        "ix_daily_price_quarantine_ingestion_run_id",
        "daily_price_quarantine",
        ["ingestion_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_quarantine_date_symbol",
        "daily_price_quarantine",
        ["trade_date", "symbol"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_quarantine_date_symbol", table_name="daily_price_quarantine")
    op.drop_index("ix_daily_price_quarantine_ingestion_run_id", table_name="daily_price_quarantine")
    op.drop_index("ix_daily_price_quarantine_instrument_id", table_name="daily_price_quarantine")
    op.drop_index("ix_daily_price_quarantine_isin", table_name="daily_price_quarantine")
    op.drop_index("ix_daily_price_quarantine_symbol", table_name="daily_price_quarantine")
    op.drop_index("ix_daily_price_quarantine_trade_date", table_name="daily_price_quarantine")
    op.drop_table("daily_price_quarantine")
