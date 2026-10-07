"""chat-with-document: jobs.chat_enabled_at/chat_archive_prefix/chat_video_key
(owner opt-in, permanent/irreversible, mirrors the public-showcase archive
columns but private -- see app/chat_jobs.py) plus a new chat_messages table
for persisted per-job conversation history.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("chat_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("chat_archive_prefix", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("chat_video_key", sa.String(), nullable=True))

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citation_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_chat_messages_job_id", "chat_messages", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_job_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_column("jobs", "chat_video_key")
    op.drop_column("jobs", "chat_archive_prefix")
    op.drop_column("jobs", "chat_enabled_at")
