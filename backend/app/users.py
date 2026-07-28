import uuid

from sqlalchemy import func

from .config import settings
from .db import get_session
from .models import Job, User, WalletLedgerEntry


def _user_to_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "google_sub": user.google_sub,
        "email": user.email,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "stripe_customer_id": user.stripe_customer_id,
        "is_admin": user.is_admin,
        "created_at": user.created_at,
    }


def get_or_create_user_by_google(
    google_sub: str, email: str, display_name: str | None, avatar_url: str | None
) -> tuple[dict, bool]:
    """Looks up a user by their stable Google subject id, creating one on
    first login. Also refreshes email/display_name/avatar_url on every login
    since Google is the source of truth for that profile data. Auto-grants
    admin if the email is in ADMIN_EMAILS -- only ever grants, never revokes,
    so it's safe to run on every login without risk of demoting someone.
    Returns (user, is_new) -- is_new is True only the first time this
    google_sub logs in, so callers can trigger first-login-only side effects
    (e.g. the welcome email in routes/auth.py)."""
    session = get_session()
    try:
        user = session.query(User).filter_by(google_sub=google_sub).one_or_none()
        is_new = user is None
        if is_new:
            user = User(google_sub=google_sub, email=email, display_name=display_name, avatar_url=avatar_url)
            session.add(user)
        else:
            user.email = email
            user.display_name = display_name
            user.avatar_url = avatar_url
        if email.lower() in settings.ADMIN_EMAILS:
            user.is_admin = True
        session.commit()
        return _user_to_dict(user), is_new
    finally:
        session.close()


def set_admin_status(user_id: str | uuid.UUID, is_admin: bool) -> dict | None:
    if isinstance(user_id, str):
        try:
            user_id = uuid.UUID(user_id)
        except ValueError:
            return None
    session = get_session()
    try:
        user = session.get(User, user_id)
        if not user:
            return None
        user.is_admin = is_admin
        session.commit()
        return _user_to_dict(user)
    finally:
        session.close()


def count_users() -> int:
    session = get_session()
    try:
        return session.query(User).count()
    finally:
        session.close()


def list_users_with_stats(limit: int = 200, offset: int = 0) -> list[dict]:
    """All users plus two per-user aggregates -- net amount actually spent
    (usage_charge + usage_refund summed and negated, so a refunded/failed
    job's charge nets back to zero rather than counting as spend) and total
    job count. Three plain queries merged in Python rather than one SQL join,
    since the expected user count here is small and this stays easy to read."""
    session = get_session()
    try:
        user_rows = session.query(User).order_by(User.created_at.desc()).limit(limit).offset(offset).all()
        # Negating in SQL (-func.sum(...)) produces an unlabeled
        # UnaryExpression the ORM row-processor can't map back to a result
        # column (NoSuchColumnError) -- sum in SQL, negate in Python instead.
        net_by_user = dict(
            session.query(WalletLedgerEntry.user_id, func.sum(WalletLedgerEntry.amount_cents))
            .filter(WalletLedgerEntry.entry_type.in_(["usage_charge", "usage_refund"]))
            .group_by(WalletLedgerEntry.user_id)
            .all()
        )
        job_counts_by_user = dict(
            session.query(Job.user_id, func.count(Job.id)).group_by(Job.user_id).all()
        )
        return [
            {
                **_user_to_dict(u),
                "spent_cents": -int(net_by_user.get(u.id, 0) or 0),
                "job_count": int(job_counts_by_user.get(u.id, 0) or 0),
            }
            for u in user_rows
        ]
    finally:
        session.close()


def get_user_by_id(user_id: str | uuid.UUID) -> dict | None:
    if isinstance(user_id, str):
        try:
            user_id = uuid.UUID(user_id)
        except ValueError:
            return None
    session = get_session()
    try:
        user = session.get(User, user_id)
        return _user_to_dict(user) if user else None
    finally:
        session.close()


def get_user_by_stripe_customer_id(stripe_customer_id: str) -> dict | None:
    session = get_session()
    try:
        user = session.query(User).filter_by(stripe_customer_id=stripe_customer_id).one_or_none()
        return _user_to_dict(user) if user else None
    finally:
        session.close()


def set_stripe_customer_id(user_id: str | uuid.UUID, stripe_customer_id: str) -> None:
    session = get_session()
    try:
        user = session.get(User, user_id)
        if user:
            user.stripe_customer_id = stripe_customer_id
            session.commit()
    finally:
        session.close()
