"""meetings.scheduled_for -- when a scheduled meeting's bot is due to join.

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "scheduled_for")
