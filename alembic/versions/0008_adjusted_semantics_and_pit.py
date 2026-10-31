"""add traded-value semantics, raw prev close, vwap, and point-in-time vintage to daily_prices_adjusted

Revision ID: 0008_adjusted_semantics_and_pit
Revises: 0007_adjusted_prices
Create Date: 2026-10-31

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0008_adjusted_semantics_and_pit"
down_revision: Union[str, None] = "0007_adjusted_prices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add semantic columns to daily_prices_adjusted
    op.add_column("daily_prices_adjusted", sa.Column("raw_prev_close", sa.Numeric(precision=16, scale=6), server_default="0.0", nullable=False))
    op.add_column("daily_prices_adjusted", sa.Column("raw_traded_value", sa.Numeric(precision=18, scale=2), server_default="0.0", nullable=False))
    op.add_column("daily_prices_adjusted", sa.Column("raw_vwap", sa.Numeric(precision=16, scale=6), nullable=True))
    op.add_column("daily_prices_adjusted", sa.Column("adjusted_vwap", sa.Numeric(precision=16, scale=6), nullable=True))
    op.add_column("daily_prices_adjusted", sa.Column("adjustment_as_of_date", sa.Date(), server_default="2024-12-31", nullable=False))
    op.add_column("daily_prices_adjusted", sa.Column("adjustment_vintage", sa.String(length=32), server_default="LATEST_VINTAGE", nullable=False))

    # 2. Update unique constraint to incorporate adjustment_as_of_date
    op.drop_constraint("uq_adj_price_inst_date_series_ver", "daily_prices_adjusted", type_="unique")
    op.create_unique_constraint(
        "uq_adj_price_inst_date_series_ver_asof",
        "daily_prices_adjusted",
        ["instrument_id", "trade_date", "series", "adjustment_version", "adjustment_as_of_date"],
    )

    # 3. Add index on PIT queries
    op.create_index("ix_adj_prices_pit", "daily_prices_adjusted", ["instrument_id", "adjustment_as_of_date", "trade_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_adj_prices_pit", table_name="daily_prices_adjusted")
    op.drop_constraint("uq_adj_price_inst_date_series_ver_asof", "daily_prices_adjusted", type_="unique")
    op.create_unique_constraint(
        "uq_adj_price_inst_date_series_ver",
        "daily_prices_adjusted",
        ["instrument_id", "trade_date", "series", "adjustment_version"],
    )
    op.drop_column("daily_prices_adjusted", "adjustment_vintage")
    op.drop_column("daily_prices_adjusted", "adjustment_as_of_date")
    op.drop_column("daily_prices_adjusted", "adjusted_vwap")
    op.drop_column("daily_prices_adjusted", "raw_vwap")
    op.drop_column("daily_prices_adjusted", "raw_traded_value")
    op.drop_column("daily_prices_adjusted", "raw_prev_close")
