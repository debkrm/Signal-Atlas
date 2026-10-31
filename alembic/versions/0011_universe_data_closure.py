"""universe data integrity closure

Revision ID: 0011_universe_data_closure
Revises: 0010_point_in_time_universe
Create Date: 2026-10-31

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0011_universe_data_closure"
down_revision: Union[str, None] = "0010_point_in_time_universe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add first_observed_trade_date to instruments
    op.add_column("instruments", sa.Column("first_observed_trade_date", sa.Date(), nullable=True))
    op.create_index("ix_instruments_first_observed_date", "instruments", ["first_observed_trade_date"])

    # 2. Populate first_observed_trade_date from MIN(daily_prices_raw.trade_date)
    op.execute("""
        UPDATE instruments i
        SET first_observed_trade_date = sub.min_td
        FROM (
            SELECT instrument_id, min(trade_date) as min_td
            FROM daily_prices_raw
            GROUP BY instrument_id
        ) sub
        WHERE i.instrument_id = sub.instrument_id;
    """)

    # 3. Reset unverified listing_date in instruments to NULL
    op.execute("""
        UPDATE instruments
        SET listing_date = NULL;
    """)

    # 4. Add provenance & reproducibility columns to universe_snapshots
    op.add_column("universe_snapshots", sa.Column("raw_data_version", sa.String(length=64), server_default="RAW_NSE_2022_2024_V1", nullable=False))
    op.add_column("universe_snapshots", sa.Column("data_coverage_start", sa.Date(), server_default="2022-01-03", nullable=False))
    op.add_column("universe_snapshots", sa.Column("data_coverage_end", sa.Date(), server_default="2024-12-31", nullable=False))
    op.add_column("universe_snapshots", sa.Column("code_revision", sa.String(length=64), server_default="phase-1b-iii.1", nullable=False))

    # 5. Add turnover completeness columns to universe_members
    op.add_column("universe_members", sa.Column("expected_lookback_sessions", sa.Integer(), server_default="126", nullable=False))
    op.add_column("universe_members", sa.Column("valid_turnover_sessions_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("universe_members", sa.Column("turnover_data_completeness", sa.Numeric(precision=6, scale=4), server_default="0.0000", nullable=False))


def downgrade() -> None:
    op.drop_column("universe_members", "turnover_data_completeness")
    op.drop_column("universe_members", "valid_turnover_sessions_count")
    op.drop_column("universe_members", "expected_lookback_sessions")

    op.drop_column("universe_snapshots", "code_revision")
    op.drop_column("universe_snapshots", "data_coverage_end")
    op.drop_column("universe_snapshots", "data_coverage_start")
    op.drop_column("universe_snapshots", "raw_data_version")

    op.drop_index("ix_instruments_first_observed_date", table_name="instruments")
    op.drop_column("instruments", "first_observed_trade_date")
