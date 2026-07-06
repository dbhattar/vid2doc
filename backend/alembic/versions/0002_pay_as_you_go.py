"""pivot from subscription plans to pure pay-as-you-go wallet billing:
drop subscriptions entirely, rename jobs.billed_overage_cents ->
jobs.billed_cents (billing is no longer "overage on top of a plan", it's
the whole charge), and drop the FK on wallet_ledger.related_job_id since a
usage charge is now recorded before its job row exists.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("wallet_ledger_related_job_id_fkey", "wallet_ledger", type_="foreignkey")
    op.alter_column("jobs", "billed_overage_cents", new_column_name="billed_cents")
    op.drop_table("subscriptions")


def downgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("plan", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_subscriptions_stripe_subscription_id", "subscriptions", ["stripe_subscription_id"])
    op.alter_column("jobs", "billed_cents", new_column_name="billed_overage_cents")
    op.create_foreign_key("wallet_ledger_related_job_id_fkey", "wallet_ledger", "jobs", ["related_job_id"], ["id"])
