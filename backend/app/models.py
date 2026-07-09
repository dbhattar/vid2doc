"""SQLAlchemy models for the multi-tenant schema (Postgres-only, see app/db.py).

`jobs` is the one pre-existing table (previously raw sqlite3, see git history of
app/db.py) -- its columns here are a superset of the original: user_id,
duration_seconds, billed_cents, and deleted_at are new. user_id is
nullable because Milestone 1 (this file) intentionally lands before auth does;
it becomes application-required starting with the auth milestone.

Pricing is pure pay-as-you-go ($1.00/video-hour, charged up front per job,
wallet-funded) -- there are no subscription plans/tiers.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    google_sub: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String, nullable=False)
    key_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="api_keys")


class WalletLedgerEntry(Base):
    """Append-only. Balance for a user is always SUM(amount_cents) WHERE user_id=X,
    never a stored/mutable counter -- see plan doc for the concurrency reasoning.
    related_job_id is intentionally NOT a DB-level foreign key: a usage charge
    is recorded before the job row exists (the charge decides whether the
    upload is even accepted), so enforcing the FK would get the ordering
    backwards. It's still always a real job id in practice."""

    __tablename__ = "wallet_ledger"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    entry_type: Mapped[str] = mapped_column(String, nullable=False)  # topup|usage_charge|usage_refund
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)  # signed: credit +, debit -
    related_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # str(uuid.uuid4()), generated in routes/convert.py
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")  # queued|processing|done|failed
    progress_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    # Set from the uploaded filename at submission time, then overwritten with
    # an LLM-generated title once compose_document runs (see pipeline.py) --
    # whichever is freshest is what list/detail views show.
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    source_path: Mapped[str] = mapped_column(String, nullable=False)
    document_path: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    billed_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProcessedWebhookEvent(Base):
    """Dedup guard for Stripe webhook retries -- insert the event id before
    processing; a duplicate insert (unique violation) means skip it."""

    __tablename__ = "processed_webhook_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Stripe event id, e.g. "evt_..."
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
