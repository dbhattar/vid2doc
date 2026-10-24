"""announcements.tag / cta_label / cta_url -- options for the branded announcement
email template (see app/announcements.py's render_announcement).

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("announcements", sa.Column("tag", sa.String(), nullable=False, server_default="Update"))
    op.add_column("announcements", sa.Column("cta_label", sa.String(), nullable=True))
    op.add_column("announcements", sa.Column("cta_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("announcements", "cta_url")
    op.drop_column("announcements", "cta_label")
    op.drop_column("announcements", "tag")
