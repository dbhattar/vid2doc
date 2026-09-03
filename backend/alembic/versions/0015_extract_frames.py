"""add jobs.extract_frames -- lets a user skip frame capture/classification/
review for a video job and get a transcript-only composed document instead
(see pipeline.py's run_job). Only meaningful for job_type == "video".
server_default=true backfills every pre-existing row to the current
always-extract behavior, so nothing changes for jobs created before this
column existed.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("extract_frames", sa.Boolean(), nullable=False, server_default=sa.true())
    )


def downgrade() -> None:
    op.drop_column("jobs", "extract_frames")
