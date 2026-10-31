"""initial schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-10-31 06:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. instruments
    op.create_table(
        "instruments",
        sa.Column("instrument_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column("listing_date", sa.Date(), nullable=True),
        sa.Column("delisting_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("instrument_id"),
    )

    # 2. instrument_symbol_history
    op.create_table(
        "instrument_symbol_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False, server_default="NSE"),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("isin", sa.String(length=16), nullable=False),
        sa.Column("series", sa.String(length=16), nullable=False, server_default="EQ"),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="NSE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.instrument_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_instrument_symbol_history_symbol", "instrument_symbol_history", ["symbol"])
    op.create_index("ix_instrument_symbol_history_isin", "instrument_symbol_history", ["isin"])
    op.create_index("ix_sym_hist_lookup", "instrument_symbol_history", ["exchange", "symbol", "series"])
    op.create_index("ix_isin_hist_lookup", "instrument_symbol_history", ["exchange", "isin"])

    # 3. trading_calendar
    op.create_table(
        "trading_calendar",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("is_trading_day", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("holiday_name", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("trade_date"),
    )

    # 4. ingestion_runs
    op.create_table(
        "ingestion_runs",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validation_issues", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_ingestion_runs_trade_date", "ingestion_runs", ["trade_date"])

    # 5. daily_prices_raw
    op.create_table(
        "daily_prices_raw",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("high", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("low", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("close", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("last", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("prev_close", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("traded_value", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("trades_count", sa.Integer(), nullable=True),
        sa.Column("series", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="NSE_CM_UDIFF"),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.instrument_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ingestion_run_id"], ["ingestion_runs.run_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instrument_id", "trade_date", name="uq_daily_price_instrument_date"),
    )
    op.create_index("ix_daily_prices_raw_trade_date", "daily_prices_raw", ["trade_date"])
    op.create_index("ix_daily_prices_raw_instrument_id", "daily_prices_raw", ["instrument_id"])
    op.create_index("ix_daily_prices_date_series", "daily_prices_raw", ["trade_date", "series"])


def downgrade() -> None:
    op.drop_table("daily_prices_raw")
    op.drop_table("ingestion_runs")
    op.drop_table("trading_calendar")
    op.drop_table("instrument_symbol_history")
    op.drop_table("instruments")
