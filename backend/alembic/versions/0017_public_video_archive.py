"""add jobs.public_video_key -- public-showcase archives now include the
original source video (job.source_path) alongside the generated document,
not just the document (see app/public_jobs.py). Stores the archived video's
S3 key (filename preserves the source's original extension, since uploads
aren't always .mp4) rather than assuming one.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("public_video_key", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "public_video_key")
