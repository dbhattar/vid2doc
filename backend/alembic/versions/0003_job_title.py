"""add jobs.title -- filename-derived at upload time, upgraded to an
LLM-generated title once compose_document runs. Nullable so existing rows
just show their created_at timestamp instead (see displayTitle() fallback
in the frontend).

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("title", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "title")
