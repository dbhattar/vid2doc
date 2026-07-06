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


class InsufficientBalanceError(Exception):
    def __init__(self, required_cents: int, balance_cents: int):
        self.required_cents = required_cents
        self.balance_cents = balance_cents
        super().__init__(f"Insufficient balance: need {required_cents}c, have {balance_cents}c")


def cost_for_duration_cents(duration_seconds: float) -> int:
    """Rounds up to the next cent -- never rounds in the platform's favor."""
    return math.ceil(duration_seconds / SECONDS_PER_CENT)


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


def charge_for_job(user_id: str, job_id: str, duration_seconds: float) -> int:
    """Deducts the cost of converting a video from the user's wallet, inside
    a transaction that locks the user's own row as the per-user
    serialization point -- two concurrent uploads from the same user
    serialize on this lock, so neither can read a stale balance and
    double-spend it. Raises InsufficientBalanceError (charging nothing) if
    the balance is too low. Returns the amount charged, in cents. Called
    before the job row exists (see models.py's note on related_job_id)."""
    cost_cents = cost_for_duration_cents(duration_seconds)
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
    if user.get("stripe_customer_id"):
        return user["stripe_customer_id"]
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
