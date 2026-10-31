"""add provenance fields to corporate_actions table

Revision ID: 0005_corporate_action_provenance
Revises: 0004_corporate_actions
Create Date: 2026-10-31

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005_corporate_action_provenance"
down_revision: Union[str, None] = "0004_corporate_actions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("corporate_actions", sa.Column("issuing_organisation", sa.String(length=64), server_default="NSE", nullable=False))
    op.add_column("corporate_actions", sa.Column("source_type", sa.String(length=64), server_default="EXCHANGE_CIRCULAR", nullable=False))
    op.add_column("corporate_actions", sa.Column("publication_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("corporate_actions", "publication_date")
    op.drop_column("corporate_actions", "source_type")
    op.drop_column("corporate_actions", "issuing_organisation")
