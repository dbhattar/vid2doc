"""public agency meetings: sources, meetings, topics, subscriptions, alerts.

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UUID = postgresql.UUID(as_uuid=True)


def _id() -> sa.Column:
    return sa.Column("id", _UUID, primary_key=True)


def _created() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now())


def upgrade() -> None:
    op.add_column("users", sa.Column("notify_topic_alerts", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        "meeting_sources",
        _id(),
        sa.Column("agency_name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("adapter", sa.String(), nullable=False),
        sa.Column("feed_url", sa.String(), nullable=False),
        sa.Column("title_filter", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        _created(),
    )
    op.create_index("ix_meeting_sources_slug", "meeting_sources", ["slug"], unique=True)

    op.create_table(
        "agency_meetings",
        _id(),
        sa.Column("source_id", _UUID, sa.ForeignKey("meeting_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("meeting_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("transcript", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created(),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("source_id", "external_id"),
    )
    op.create_index("ix_agency_meetings_source_id", "agency_meetings", ["source_id"])
    op.create_index("ix_agency_meetings_meeting_date", "agency_meetings", ["meeting_date"])
    op.create_index("ix_agency_meetings_job_id", "agency_meetings", ["job_id"])
    op.create_index("ix_agency_meetings_status", "agency_meetings", ["status"])

    op.create_table(
        "topics",
        _id(),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _created(),
    )
    op.create_index("ix_topics_slug", "topics", ["slug"], unique=True)

    op.create_table(
        "topic_suggestions",
        _id(),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("mentions", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("example_meeting_id", _UUID, sa.ForeignKey("agency_meetings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        _created(),
    )
    op.create_index("ix_topic_suggestions_status", "topic_suggestions", ["status"])

    op.create_table(
        "agency_meeting_topics",
        _id(),
        sa.Column("meeting_id", _UUID, sa.ForeignKey("agency_meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", _UUID, sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("start_ts", sa.Float(), nullable=True),
        sa.Column("end_ts", sa.Float(), nullable=True),
        sa.UniqueConstraint("meeting_id", "topic_id"),
    )
    op.create_index("ix_agency_meeting_topics_meeting_id", "agency_meeting_topics", ["meeting_id"])
    op.create_index("ix_agency_meeting_topics_topic_id", "agency_meeting_topics", ["topic_id"])

    op.create_table(
        "topic_subscriptions",
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("topic_id", _UUID, sa.ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True),
        _created(),
    )
    op.create_index("ix_topic_subscriptions_topic_id", "topic_subscriptions", ["topic_id"])

    op.create_table(
        "topic_notifications",
        _id(),
        sa.Column("meeting_id", _UUID, sa.ForeignKey("agency_meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        _created(),
        sa.UniqueConstraint("meeting_id", "user_id"),
    )
    op.create_index("ix_topic_notifications_meeting_id", "topic_notifications", ["meeting_id"])
    op.create_index("ix_topic_notifications_status", "topic_notifications", ["status"])


def downgrade() -> None:
    op.drop_table("topic_notifications")
    op.drop_table("topic_subscriptions")
    op.drop_table("agency_meeting_topics")
    op.drop_table("topic_suggestions")
    op.drop_table("topics")
    op.drop_table("agency_meetings")
    op.drop_table("meeting_sources")
    op.drop_column("users", "notify_topic_alerts")
