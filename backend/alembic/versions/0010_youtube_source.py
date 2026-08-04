"""allow jobs.source_path to be null and add jobs.source_url -- a YouTube
import (routes/youtube.py) creates its job before downloading, so the
worker (pipeline.py's _download_if_needed) can do that slow, proportional-
to-video-length download instead of the API request blocking on it.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("jobs", "source_path", nullable=True)
    op.add_column("jobs", sa.Column("source_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "source_url")
    op.alter_column("jobs", "source_path", nullable=False)
