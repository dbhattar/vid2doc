"""add jobs.share_token -- opt-in public read-only sharing of a completed
job's rendered documents via an unguessable link (routes/share.py).

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("share_token", sa.String(), nullable=True))
    op.create_index("ix_jobs_share_token", "jobs", ["share_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_jobs_share_token", table_name="jobs")
    op.drop_column("jobs", "share_token")
