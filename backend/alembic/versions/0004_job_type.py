"""add jobs.job_type ("video" | "audio") -- distinguishes the existing
video-to-document pipeline from the new audio-only verbatim transcript
pipeline (POST /api/transcribe_audio). Existing rows all predate the audio
feature, so they default to "video".

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("job_type", sa.String(), nullable=False, server_default="video"))


def downgrade() -> None:
    op.drop_column("jobs", "job_type")
