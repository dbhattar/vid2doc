"""add jobs.public_upfront and users.announcements_opt_out

public_upfront marks a job the owner made public at upload time (free, see
routes/convert.py) rather than opting in afterwards for a refund.
announcements_opt_out backs the unsubscribe link in admin announcement emails
(see app/announcements.py).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("public_upfront", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(
        "users", sa.Column("announcements_opt_out", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    op.drop_column("users", "announcements_opt_out")
    op.drop_column("jobs", "public_upfront")
