"""point in time liquidity universe schema

Revision ID: 0010_point_in_time_universe
Revises: 0009_allow_nullable_traded_value
Create Date: 2026-10-31

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0010_point_in_time_universe"
down_revision: Union[str, None] = "0009_allow_nullable_traded_value"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "universe_snapshots",
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("config_version", sa.String(length=32), nullable=False, server_default="1.0"),
        sa.Column("config_identifier", sa.String(length=128), nullable=False),
        sa.Column("lookback_sessions", sa.Integer(), nullable=False),
        sa.Column("lookback_start_date", sa.Date(), nullable=False),
        sa.Column("lookback_end_date", sa.Date(), nullable=False),
        sa.Column("min_adtv", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("min_trading_completeness", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("min_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("permitted_series", sa.String(length=64), nullable=False),
        sa.Column("adjustment_version", sa.String(length=32), nullable=False, server_default="v1.4"),
        sa.Column("total_instruments_evaluated", sa.Integer(), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("excluded_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id"),
        sa.UniqueConstraint("as_of_date", "config_identifier", "adjustment_version", name="uq_universe_snapshot_date_config_ver"),
    )
    op.create_index("ix_universe_snapshots_as_of_date", "universe_snapshots", ["as_of_date"])
    op.create_index("ix_universe_snapshots_config_id", "universe_snapshots", ["config_identifier"])
    op.create_index("ix_universe_snapshot_date_ver", "universe_snapshots", ["as_of_date", "adjustment_version"])

    op.create_table(
        "universe_members",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("isin", sa.String(length=16), nullable=False),
        sa.Column("series", sa.String(length=16), nullable=False),
        sa.Column("observed_sessions_count", sa.Integer(), nullable=False),
        sa.Column("missing_sessions_count", sa.Integer(), nullable=False),
        sa.Column("trading_completeness", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("total_turnover", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("average_daily_turnover", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("median_daily_turnover", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("null_turnover_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("zero_turnover_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("positive_turnover_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latest_raw_close", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("is_eligible", sa.Boolean(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("exclusion_reason", sa.String(length=64), nullable=True),
        sa.Column("exclusion_detail", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.instrument_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["universe_snapshots.snapshot_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "instrument_id", name="uq_universe_member_snapshot_inst"),
    )
    op.create_index("ix_universe_members_snapshot_id", "universe_members", ["snapshot_id"])
    op.create_index("ix_universe_members_instrument_id", "universe_members", ["instrument_id"])
    op.create_index("ix_universe_members_symbol", "universe_members", ["symbol"])
    op.create_index("ix_universe_members_isin", "universe_members", ["isin"])
    op.create_index("ix_universe_members_is_eligible", "universe_members", ["is_eligible"])
    op.create_index("ix_universe_member_snapshot_eligible", "universe_members", ["snapshot_id", "is_eligible"])
    op.create_index("ix_universe_member_snapshot_rank", "universe_members", ["snapshot_id", "rank"])


def downgrade() -> None:
    op.drop_table("universe_members")
    op.drop_table("universe_snapshots")
