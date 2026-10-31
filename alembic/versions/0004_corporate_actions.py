"""create corporate_actions table

Revision ID: 0004_corporate_actions
Revises: 0003_daily_price_quarantine
Create Date: 2026-10-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_corporate_actions"
down_revision: Union[str, None] = "0003_daily_price_quarantine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "corporate_actions",
        sa.Column("action_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("instrument_id", sa.String(length=36), sa.ForeignKey("instruments.instrument_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("series", sa.String(length=16), server_default="EQ", nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column("old_isin", sa.String(length=16), nullable=True),
        sa.Column("new_isin", sa.String(length=16), nullable=True),
        sa.Column("old_face_value", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("new_face_value", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("old_share_qty", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("new_share_qty", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("share_multiplier", sa.Numeric(precision=12, scale=6), server_default="1.0", nullable=False),
        sa.Column("cash_entitlement", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("purpose", sa.String(length=512), nullable=False),
        sa.Column("source_circular", sa.String(length=128), nullable=True),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("identity_decision", sa.String(length=32), server_default="UNIFIED_IDENTITY", nullable=False),
        sa.Column("verification_status", sa.String(length=32), server_default="VERIFIED", nullable=False),
        sa.Column("parser_version", sa.String(length=32), server_default="v1.0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index("ix_corporate_actions_instrument_id", "corporate_actions", ["instrument_id"])
    op.create_index("ix_corporate_actions_symbol", "corporate_actions", ["symbol"])
    op.create_index("ix_corporate_actions_ex_date", "corporate_actions", ["ex_date"])
    op.create_index("ix_corporate_actions_old_isin", "corporate_actions", ["old_isin"])
    op.create_index("ix_corporate_actions_new_isin", "corporate_actions", ["new_isin"])
    op.create_index("ix_corporate_actions_date_symbol", "corporate_actions", ["ex_date", "symbol"])
    op.create_index("ix_corporate_actions_type_status", "corporate_actions", ["action_type", "verification_status"])


def downgrade() -> None:
    op.drop_index("ix_corporate_actions_type_status", table_name="corporate_actions")
    op.drop_index("ix_corporate_actions_date_symbol", table_name="corporate_actions")
    op.drop_index("ix_corporate_actions_new_isin", table_name="corporate_actions")
    op.drop_index("ix_corporate_actions_old_isin", table_name="corporate_actions")
    op.drop_index("ix_corporate_actions_ex_date", table_name="corporate_actions")
    op.drop_index("ix_corporate_actions_symbol", table_name="corporate_actions")
    op.drop_index("ix_corporate_actions_instrument_id", table_name="corporate_actions")
    op.drop_table("corporate_actions")
