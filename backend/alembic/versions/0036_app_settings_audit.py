"""app_settings: who last changed a setting, and when (admin Settings page).

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "app_settings",
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "updated_by")
    op.drop_column("app_settings", "updated_at")
