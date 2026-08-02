"""add jobs.client_ip -- basis for the anonymous trial's per-IP daily cap.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("client_ip", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "client_ip")
