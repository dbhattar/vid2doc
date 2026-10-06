"""add jobs.public_* columns -- opt-in "make this job public for a partial
refund" feature (see app/public_jobs.py, routes/public_jobs.py). Only
job_type == "video" jobs are eligible; NULL public_status means never opted
in. Once "approved" it's permanent (no revoke path), so there's no
"unpublished"/"revoked" state. Unlike jobs.share_token (owner-revocable,
tied to on-disk storage that dies at 7-day retention), the approved archive
lives in external storage (S3) forever -- see public_archive_prefix.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("public_status", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("public_consented_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("public_refund_cents", sa.BigInteger(), nullable=True))
    op.add_column("jobs", sa.Column("public_archive_prefix", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("public_archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("public_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("public_reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column("jobs", sa.Column("public_rejection_reason", sa.Text(), nullable=True))
    # Speeds up the admin moderation queue's "WHERE public_status = 'pending'"
    # and the public showcase's "WHERE public_status = 'approved'".
    op.create_index("ix_jobs_public_status", "jobs", ["public_status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_public_status", table_name="jobs")
    op.drop_column("jobs", "public_rejection_reason")
    op.drop_column("jobs", "public_reviewed_by")
    op.drop_column("jobs", "public_reviewed_at")
    op.drop_column("jobs", "public_archived_at")
    op.drop_column("jobs", "public_archive_prefix")
    op.drop_column("jobs", "public_refund_cents")
    op.drop_column("jobs", "public_consented_at")
    op.drop_column("jobs", "public_status")
