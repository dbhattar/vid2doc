"""users: notification and meeting preferences (Settings page).

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FLAGS = ("notify_job_done", "notify_review_reminder", "notify_meeting_notes")


def upgrade() -> None:
    for name in _FLAGS:
        op.add_column("users", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("users", sa.Column("default_bot_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "default_bot_name")
    for name in reversed(_FLAGS):
        op.drop_column("users", name)
