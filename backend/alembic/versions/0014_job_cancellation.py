"""add jobs.cancel_requested -- lets a user cancel a queued/processing/
awaiting-review job (routes/jobs.py's new cancel endpoint). A processing
job can't be killed instantly (the single worker has no way to interrupt a
blocking ffmpeg/LLM call already in flight), so this is checked
cooperatively at each pipeline stage boundary instead -- see
pipeline.py's _check_not_cancelled. "cancelled" itself is just a new value
for the existing unconstrained jobs.status column, no schema change needed
for that part.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    op.drop_column("jobs", "cancel_requested")
