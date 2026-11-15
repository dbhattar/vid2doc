"""jobs: private S3 storage (prefix + stored file list).

Idempotent: this feature's columns were first added by an earlier version of
this migration numbered 0037 (before the agency-meetings migrations took
0037-0041), so a database that ran that one already has them while still
recorded at 0041. Each step is skipped if its column is already there.

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _job_columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("jobs")}


def upgrade() -> None:
    existing = _job_columns()
    if "storage_prefix" not in existing:
        op.add_column("jobs", sa.Column("storage_prefix", sa.String(), nullable=True))
    if "storage_files" not in existing:
        op.add_column("jobs", sa.Column("storage_files", sa.JSON(), nullable=True))


def downgrade() -> None:
    existing = _job_columns()
    if "storage_files" in existing:
        op.drop_column("jobs", "storage_files")
    if "storage_prefix" in existing:
        op.drop_column("jobs", "storage_prefix")
