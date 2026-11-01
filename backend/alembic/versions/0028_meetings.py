"""meetings -- Zoom/Meet/Teams meetings a notetaker bot was sent to.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("meeting_url", sa.String(), nullable=False),
        sa.Column("vendor_bot_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_meetings_user_id", "meetings", ["user_id"])
    op.create_index("ix_meetings_vendor_bot_id", "meetings", ["vendor_bot_id"], unique=True)
    op.create_index("ix_meetings_job_id", "meetings", ["job_id"])


def downgrade() -> None:
    op.drop_table("meetings")
