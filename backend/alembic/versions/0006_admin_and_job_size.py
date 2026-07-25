"""add users.is_admin and jobs.source_size_bytes -- admin dashboard.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-25

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("jobs", sa.Column("source_size_bytes", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "source_size_bytes")
    op.drop_column("users", "is_admin")
