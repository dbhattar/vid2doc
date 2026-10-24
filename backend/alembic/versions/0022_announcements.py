"""announcements + announcement_deliveries -- admin emails are queued as one
delivery row per recipient and sent by the worker with a delay between each
(see app/announcements.py).

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "announcement_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "announcement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("announcements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("announcement_id", "user_id"),
    )
    op.create_index("ix_announcement_deliveries_announcement_id", "announcement_deliveries", ["announcement_id"])
    op.create_index("ix_announcement_deliveries_status", "announcement_deliveries", ["status"])


def downgrade() -> None:
    op.drop_table("announcement_deliveries")
    op.drop_table("announcements")
