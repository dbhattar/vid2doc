"""jobs: private S3 storage (prefix + stored file list).

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("storage_prefix", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("storage_files", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "storage_files")
    op.drop_column("jobs", "storage_prefix")
