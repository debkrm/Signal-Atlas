"""allow nullable traded_value and raw_traded_value in daily_prices_adjusted

Revision ID: 0009_allow_nullable_traded_value
Revises: 0008_adjusted_semantics_and_pit
Create Date: 2026-10-31

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0009_allow_nullable_traded_value"
down_revision: Union[str, None] = "0008_adjusted_semantics_and_pit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make traded_value and raw_traded_value nullable in daily_prices_adjusted
    op.alter_column(
        "daily_prices_adjusted",
        "traded_value",
        existing_type=sa.Numeric(precision=18, scale=2),
        nullable=True,
    )
    op.alter_column(
        "daily_prices_adjusted",
        "raw_traded_value",
        existing_type=sa.Numeric(precision=18, scale=2),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "daily_prices_adjusted",
        "raw_traded_value",
        existing_type=sa.Numeric(precision=18, scale=2),
        nullable=False,
    )
    op.alter_column(
        "daily_prices_adjusted",
        "traded_value",
        existing_type=sa.Numeric(precision=18, scale=2),
        nullable=False,
    )
