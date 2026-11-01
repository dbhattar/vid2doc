"""meetings.bot_name -- the name the user chose for the notetaker bot.

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("bot_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "bot_name")
