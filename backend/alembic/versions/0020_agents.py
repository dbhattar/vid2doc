"""AI agents (proof of concept): agents, agent_documents (snapshotted
knowledge base), agent_conversations, agent_messages. Tools and skills live
in code (app/agent_catalog.py), stored on the agent as id lists.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_ids", sa.JSON(), nullable=False),
        sa.Column("skill_ids", sa.JSON(), nullable=False),
        sa.Column("memory", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agents_user_id", "agents", ["user_id"])

    op.create_table(
        "agent_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "job_id", name="uq_agent_documents_agent_job"),
    )
    op.create_index("ix_agent_documents_agent_id", "agent_documents", ["agent_id"])

    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("summarized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_conversations_agent_id", "agent_conversations", ["agent_id"])

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), sa.ForeignKey("agent_conversations.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tools_used", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_messages_conversation_id", "agent_messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_messages_conversation_id", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index("ix_agent_conversations_agent_id", table_name="agent_conversations")
    op.drop_table("agent_conversations")
    op.drop_index("ix_agent_documents_agent_id", table_name="agent_documents")
    op.drop_table("agent_documents")
    op.drop_index("ix_agents_user_id", table_name="agents")
    op.drop_table("agents")
