"""meetings: back to the vendor (Recall.ai) bot -- undoes 0030's own-bot columns.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("meetings", "audio_path")
    op.drop_column("meetings", "stop_requested")
    op.drop_column("meetings", "claimed_at")
    op.add_column("meetings", sa.Column("vendor_bot_id", sa.String(), nullable=True))
    op.create_index("ix_meetings_vendor_bot_id", "meetings", ["vendor_bot_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_meetings_vendor_bot_id", table_name="meetings")
    op.drop_column("meetings", "vendor_bot_id")
    op.add_column("meetings", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("meetings", sa.Column("stop_requested", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("meetings", sa.Column("audio_path", sa.String(), nullable=True))
