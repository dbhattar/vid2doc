"""add jobs.aspect_ratio/video_template/stock_media_provider -- support for
the new "video_gen" job_type (audio -> generated video, routes/video_gen.py).
Only "16:9"/"highlight_card"/"pexels" are actually implemented in v1; these
columns exist now so a future aspect ratio or visual style doesn't need a
second migration. Existing rows (job_type != "video_gen") get the same
defaults, which are simply unused for them.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("aspect_ratio", sa.String(), nullable=False, server_default="16:9"))
    op.add_column(
        "jobs", sa.Column("video_template", sa.String(), nullable=True, server_default="highlight_card")
    )
    op.add_column(
        "jobs", sa.Column("stock_media_provider", sa.String(), nullable=True, server_default="pexels")
    )


def downgrade() -> None:
    op.drop_column("jobs", "stock_media_provider")
    op.drop_column("jobs", "video_template")
    op.drop_column("jobs", "aspect_ratio")
