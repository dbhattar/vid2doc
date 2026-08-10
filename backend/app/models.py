"""SQLAlchemy models for the multi-tenant schema (Postgres-only, see app/db.py).

`jobs` is the one pre-existing table (previously raw sqlite3, see git history of
app/db.py) -- its columns here are a superset of the original: user_id,
duration_seconds, billed_cents, and deleted_at are new. user_id started out
nullable only because Milestone 1 (this file) intentionally landed before auth
did; every authenticated route now always sets it. That nullability is reused
deliberately as the signal for an anonymous trial job (see routes/trial.py) --
`user_id IS NULL` means "trial", never charged, never paused for review, swept
by retention.py on a much shorter clock than real users' jobs.

Pricing is pure pay-as-you-go ($1.00/video-hour, charged up front per job,
wallet-funded) -- there are no subscription plans/tiers.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, String, Text, func
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
    # Auto-granted on login to any email in ADMIN_EMAILS (see users.py), or
    # toggled directly by an existing admin via the admin dashboard --
    # ADMIN_EMAILS only ever grants, never revokes, so removing an email
    # from that list doesn't silently demote someone still using the app.
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    # video: frame capture + composed document (routes/convert.py). audio:
    # verbatim speaker-tagged transcript only, no frames/composition
    # (routes/audio.py) -- see pipeline.py's is_audio_job branch.
    job_type: Mapped[str] = mapped_column(String, nullable=False, default="video")
    # Set from the uploaded filename at submission time, then overwritten with
    # an LLM-generated title once compose_document runs (see pipeline.py) --
    # whichever is freshest is what list/detail views show.
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    # Nullable: a job imported from YouTube (routes/youtube.py) is created
    # with source_path=None and source_url set -- the worker downloads it
    # (pipeline.py's _download_if_needed) and fills in source_path once that
    # completes, same as every other job type has it set from the start.
    source_path: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    document_path: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Uploaded file size in bytes, captured at upload time (media.py's
    # save_upload already streams and counts this) -- nullable since jobs
    # created before this column existed never recorded it.
    source_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    billed_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Only ever set for anonymous trial jobs (user_id IS NULL) -- the basis
    # for routes/trial.py's per-IP daily cap. Never set for real users.
    client_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    # Set when the owner turns on public sharing for this job (see
    # routes/share.py) -- NULL means not shared, same nullable-as-signal
    # convention as user_id for trial jobs (see this class's docstring).
    # Stored in plaintext (unlike api_keys.key_hash): the raw value itself is
    # what a share link must reproduce, and the only party who ever sees it
    # back is the owner, through their own authenticated job responses.
    share_token: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GoogleDriveConnection(Base):
    """One row per user -- the OAuth refresh token that lets us mint short-
    lived Drive access tokens on demand for 'Save to Drive' uploads. The
    refresh token is stored encrypted (see app/crypto.py); nothing here is
    usable without ENCRYPTION_KEY."""

    __tablename__ = "google_drive_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False, index=True
    )
    google_email: Mapped[str] = mapped_column(String, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False)  # granted scope string, for future auditing
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Feedback(Base):
    """Freeform feedback/feature requests -- from the app's feedback button
    (source="app", user_id set) or the marketing site's public widget
    (source="marketing", user_id NULL since those visitors aren't logged in,
    email optional if they chose to leave one). Just persisted for later
    review via the admin dashboard."""

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="app")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Testimonial(Base):
    """Curated quotes shown on the marketing homepage (see
    routes/testimonials.py's public list endpoint) -- there's no admin UI
    for these yet, so rows are added directly (see that route module's
    docstring for a one-off insert snippet). Every row is shown; there's no
    draft/published flag since nothing writes one unpublished."""

    __tablename__ = "testimonials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    author_name: Mapped[str] = mapped_column(String, nullable=False)
    author_role: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessedWebhookEvent(Base):
    """Dedup guard for Stripe webhook retries -- insert the event id before
    processing; a duplicate insert (unique violation) means skip it."""

    __tablename__ = "processed_webhook_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Stripe event id, e.g. "evt_..."
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
