"""add jobs.public_hidden -- lets admin exclude an already-"approved" public
showcase item from the homepage carousel (GET /api/public/showcase) without
touching public_status, the refund, or the S3 archive (see
app/public_jobs.py's state machine, which stays closed/permanent once
approved). Default false so every existing approved row stays visible the
moment this ships. See routes/admin.py's new /hide and /unhide endpoints.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("public_hidden", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    op.drop_column("jobs", "public_hidden")
