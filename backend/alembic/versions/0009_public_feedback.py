"""allow anonymous feedback -- marketing site feedback widget has no login,
so feedback.user_id must be nullable; adds email (optional contact-back for
anonymous submitters) and source (distinguishes "app" vs "marketing" in the
admin feedback list).

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("feedback", "user_id", nullable=True)
    op.add_column("feedback", sa.Column("email", sa.String(), nullable=True))
    op.add_column(
        "feedback", sa.Column("source", sa.String(), nullable=False, server_default="app")
    )


def downgrade() -> None:
    op.drop_column("feedback", "source")
    op.drop_column("feedback", "email")
    op.alter_column("feedback", "user_id", nullable=False)
