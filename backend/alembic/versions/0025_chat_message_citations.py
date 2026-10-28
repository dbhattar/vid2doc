"""chat_messages.citations -- playable start/end clip ranges an answer cites.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("citations", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "citations")
