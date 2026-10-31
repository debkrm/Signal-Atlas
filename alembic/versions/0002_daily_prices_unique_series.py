"""allow multi series daily prices per instrument date

Revision ID: 0002_daily_prices_unique_series
Revises: 0001_initial_schema
Create Date: 2026-10-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_daily_prices_unique_series"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Replace (instrument_id, trade_date) constraint with (instrument_id, trade_date, series)
    # to support multiple trading series (e.g. EQ and BL block deals) for the same instrument on the same date.
    op.drop_constraint("uq_daily_price_instrument_date", "daily_prices_raw", type_="unique")
    op.create_unique_constraint(
        "uq_daily_price_inst_date_series",
        "daily_prices_raw",
        ["instrument_id", "trade_date", "series"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_daily_price_inst_date_series", "daily_prices_raw", type_="unique")
    op.create_unique_constraint(
        "uq_daily_price_instrument_date",
        "daily_prices_raw",
        ["instrument_id", "trade_date"],
    )
