import math

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from . import users
from .db import get_session
from .models import ProcessedWebhookEvent, User, WalletLedgerEntry
from .stripe_client import stripe

# $1.00/video-hour, charged proportionally to the exact video length --
# 36 seconds of video costs exactly 1 cent. No plans/tiers.
SECONDS_PER_CENT = 36
# $0.40/hour for audio-only transcript jobs (job_type == "audio") -- these
# skip the frame capture, vision-classification, and full document
# composition that make up most of a video job's cost (one summary LLM
# call still happens, see pipeline.py/compose.generate_summary), so they're
# priced lower to match.
SECONDS_PER_CENT_AUDIO = 90
# $3.00/video-hour for generated video (job_type == "video_gen") -- higher
# than the plain video rate because ffmpeg rendering is real CPU-seconds on
# the shared worker (not just 3rd-party API cost like the other two rates),
# plus the extra LLM calls for scene segmentation and headline generation.
# PLACEHOLDER: needs real measurement from a beta/pilot pass before launch,
# not just this proportional-to-duration guess.
SECONDS_PER_CENT_VIDEO_GEN = 12


class InsufficientBalanceError(Exception):
    def __init__(self, required_cents: int, balance_cents: int):
        self.required_cents = required_cents
        self.balance_cents = balance_cents
        super().__init__(f"Insufficient balance: need {required_cents}c, have {balance_cents}c")


def cost_for_duration_cents(duration_seconds: float, job_type: str = "video") -> int:
    """Rounds up to the next cent -- never rounds in the platform's favor."""
    if job_type == "audio":
        rate = SECONDS_PER_CENT_AUDIO
    elif job_type == "video_gen":
        rate = SECONDS_PER_CENT_VIDEO_GEN
    else:
        rate = SECONDS_PER_CENT
    return math.ceil(duration_seconds / rate)


def get_wallet_balance_cents(user_id: str) -> int:
    session = get_session()
    try:
        total = session.execute(
            select(func.coalesce(func.sum(WalletLedgerEntry.amount_cents), 0)).where(
                WalletLedgerEntry.user_id == user_id
            )
        ).scalar()
        return int(total or 0)
    finally:
        session.close()


def net_spent_cents(user_id: str) -> int:
    """Net amount actually spent on processing (usage charges minus any
    refunds), for the unified dashboard's usage overview -- deliberately
    excludes topups, which are money added, not spent."""
    session = get_session()
    try:
        total = session.execute(
            select(func.coalesce(func.sum(WalletLedgerEntry.amount_cents), 0)).where(
                WalletLedgerEntry.user_id == user_id,
                WalletLedgerEntry.entry_type.in_(["usage_charge", "usage_refund"]),
            )
        ).scalar()
        return -int(total or 0)
    finally:
        session.close()


def total_revenue_cents() -> int:
    """Real money collected platform-wide -- sum of topup entries only, not
    net wallet balance (which would undercount revenue by however much
    users still have unspent sitting in their wallets)."""
    session = get_session()
    try:
        total = session.execute(
            select(func.coalesce(func.sum(WalletLedgerEntry.amount_cents), 0)).where(
                WalletLedgerEntry.entry_type == "topup"
            )
        ).scalar()
        return int(total or 0)
    finally:
        session.close()


def charge_for_job(user_id: str, job_id: str, duration_seconds: float, job_type: str = "video") -> int:
    """Deducts the cost of converting a video (or transcribing audio) from the
    user's wallet, inside a transaction that locks the user's own row as the
    per-user serialization point -- two concurrent uploads from the same
    user serialize on this lock, so neither can read a stale balance and
    double-spend it. Raises InsufficientBalanceError (charging nothing) if
    the balance is too low. Returns the amount charged, in cents. Called
    before the job row exists (see models.py's note on related_job_id)."""
    cost_cents = cost_for_duration_cents(duration_seconds, job_type)
    session = get_session()
    try:
        session.execute(select(User.id).where(User.id == user_id).with_for_update())
        balance = session.execute(
            select(func.coalesce(func.sum(WalletLedgerEntry.amount_cents), 0)).where(
                WalletLedgerEntry.user_id == user_id
            )
        ).scalar()
        balance = int(balance or 0)
        if balance < cost_cents:
            session.rollback()
            raise InsufficientBalanceError(cost_cents, balance)
        session.add(
            WalletLedgerEntry(
                user_id=user_id, entry_type="usage_charge", amount_cents=-cost_cents, related_job_id=job_id
            )
        )
        session.commit()
        return cost_cents
    finally:
        session.close()


def refund_job_charge(user_id: str, job_id: str, amount_cents: int) -> None:
    """A video that failed mid-pipeline didn't produce anything usable --
    refund what it was charged. A no-op if it wasn't charged anything."""
    if amount_cents <= 0:
        return
    session = get_session()
    try:
        session.add(
            WalletLedgerEntry(
                user_id=user_id, entry_type="usage_refund", amount_cents=amount_cents, related_job_id=job_id
            )
        )
        session.commit()
    finally:
        session.close()


def credit_topup(user_id: str, amount_cents: int, stripe_payment_intent_id: str | None) -> None:
    session = get_session()
    try:
        session.add(
            WalletLedgerEntry(
                user_id=user_id,
                entry_type="topup",
                amount_cents=amount_cents,
                stripe_payment_intent_id=stripe_payment_intent_id,
            )
        )
        session.commit()
    finally:
        session.close()


def get_or_create_stripe_customer(user: dict) -> str:
    """Stripe test mode and live mode are entirely separate data stores --
    a customer id created under one doesn't exist under the other. Switching
    STRIPE_SECRET_KEY from test to live (or vice versa) instantly strands
    every previously-cached stripe_customer_id, so verify it still resolves
    before trusting it rather than failing checkout for every existing user."""
    if user.get("stripe_customer_id"):
        try:
            stripe.Customer.retrieve(user["stripe_customer_id"])
            return user["stripe_customer_id"]
        except stripe.InvalidRequestError:
            pass
    customer = stripe.Customer.create(email=user["email"])
    users.set_stripe_customer_id(user["id"], customer.id)
    return customer.id


def claim_webhook_event(event_id: str) -> bool:
    """Returns True the first time this event id is seen (and records it),
    False if already processed (Stripe retries webhook delivery) -- callers
    should skip processing entirely on False."""
    session = get_session()
    try:
        session.add(ProcessedWebhookEvent(id=event_id))
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False
    finally:
        session.close()
