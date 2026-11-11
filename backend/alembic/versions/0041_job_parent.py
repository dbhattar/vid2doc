"""jobs: parent_job_id for documents derived from a finished video job.

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("parent_job_id", sa.String(), nullable=True))
    op.create_foreign_key("fk_jobs_parent_job_id", "jobs", "jobs", ["parent_job_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_jobs_parent_job_id", "jobs", ["parent_job_id"])
    op.create_index(
        "uq_jobs_live_derivative",
        "jobs",
        ["parent_job_id", "transformation"],
        unique=True,
        postgresql_where=sa.text("parent_job_id IS NOT NULL AND status NOT IN ('failed', 'cancelled')"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_live_derivative", table_name="jobs")
    op.drop_index("ix_jobs_parent_job_id", table_name="jobs")
    op.drop_constraint("fk_jobs_parent_job_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "parent_job_id")
