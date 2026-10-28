"""jobs.transformation -- what a video job turns the video into (document, notes, study_guide, research).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("transformation", sa.String(), nullable=False, server_default="document"))


def downgrade() -> None:
    op.drop_column("jobs", "transformation")
