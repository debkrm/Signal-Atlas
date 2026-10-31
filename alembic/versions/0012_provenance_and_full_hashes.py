"""expand snapshot_id and add raw_data_manifest_hash

Revision ID: 0012_provenance_and_full_hashes
Revises: 0011_universe_data_closure
Create Date: 2026-10-31 20:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0012_provenance_and_full_hashes"
down_revision: Union[str, None] = "0011_universe_data_closure"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Expand snapshot_id on universe_snapshots and universe_members
    # Note: On PostgreSQL, altering type of referenced PK requires dropping or altering FK
    op.alter_column(
        "universe_members",
        "snapshot_id",
        existing_type=sa.String(length=64),
        type_=sa.String(length=128),
        existing_nullable=False,
    )
    op.alter_column(
        "universe_snapshots",
        "snapshot_id",
        existing_type=sa.String(length=64),
        type_=sa.String(length=128),
        existing_nullable=False,
    )

    # 2. Expand code_revision and raw_data_version to 128 characters
    op.alter_column(
        "universe_snapshots",
        "code_revision",
        existing_type=sa.String(length=64),
        type_=sa.String(length=128),
        existing_nullable=False,
    )
    op.alter_column(
        "universe_snapshots",
        "raw_data_version",
        existing_type=sa.String(length=64),
        type_=sa.String(length=128),
        existing_nullable=False,
    )

    # 3. Add raw_data_manifest_hash column
    op.add_column(
        "universe_snapshots",
        sa.Column("raw_data_manifest_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("universe_snapshots", "raw_data_manifest_hash")

    op.alter_column(
        "universe_snapshots",
        "raw_data_version",
        existing_type=sa.String(length=128),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "universe_snapshots",
        "code_revision",
        existing_type=sa.String(length=128),
        type_=sa.String(length=64),
        existing_nullable=False,
    )

    op.alter_column(
        "universe_snapshots",
        "snapshot_id",
        existing_type=sa.String(length=128),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "universe_members",
        "snapshot_id",
        existing_type=sa.String(length=128),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
