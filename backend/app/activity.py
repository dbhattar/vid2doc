"""Synthesizes a "what did each user do" activity feed from existing tables
-- there's no dedicated event/audit log, so this merges Job, WalletLedgerEntry,
and Feedback rows (the only three tables that record user-initiated actions
with a timestamp) into one chronological feed. Powers the admin dashboard's
global activity feed and per-user drill-down page (see routes/admin.py)."""

import uuid

from .db import get_session
from .models import Feedback, Job, User, WalletLedgerEntry


def _job_event(job: Job, user: User) -> dict:
    return {
        "id": f"job:{job.id}",
        "type": "job",
        "user_id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "created_at": job.created_at,
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "title": job.title,
    }


def _wallet_event(entry: WalletLedgerEntry, user: User) -> dict:
    return {
        "id": f"wallet:{entry.id}",
        "type": "wallet",
        "user_id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "created_at": entry.created_at,
        "entry_type": entry.entry_type,
        "amount_cents": entry.amount_cents,
    }


def _feedback_event(fb: Feedback, user: User) -> dict:
    return {
        "id": f"feedback:{fb.id}",
        "type": "feedback",
        "user_id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "created_at": fb.created_at,
        "message": fb.message,
    }


def _merge_sorted(*event_lists: list[dict]) -> list[dict]:
    events = [e for lst in event_lists for e in lst]
    events.sort(key=lambda e: e["created_at"], reverse=True)
    return events


def list_recent_activity(limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    """Newest-first activity across every user. Fetches the top `offset +
    limit` rows from each of the three source tables, merges, then slices --
    an event outside a source's own top-K can't be in the global top-K
    either (K rows from that same source alone would already outrank it),
    so this is exact, not approximate. Inner-joined to User, which also
    drops the legacy null-user_id jobs and anonymous marketing feedback --
    neither is a user's activity."""
    session = get_session()
    try:
        fetch_n = offset + limit
        job_rows = (
            session.query(Job, User)
            .join(User, Job.user_id == User.id)
            .order_by(Job.created_at.desc())
            .limit(fetch_n)
            .all()
        )
        wallet_rows = (
            session.query(WalletLedgerEntry, User)
            .join(User, WalletLedgerEntry.user_id == User.id)
            .order_by(WalletLedgerEntry.created_at.desc())
            .limit(fetch_n)
            .all()
        )
        feedback_rows = (
            session.query(Feedback, User)
            .join(User, Feedback.user_id == User.id)
            .order_by(Feedback.created_at.desc())
            .limit(fetch_n)
            .all()
        )
        events = _merge_sorted(
            [_job_event(j, u) for j, u in job_rows],
            [_wallet_event(w, u) for w, u in wallet_rows],
            [_feedback_event(f, u) for f, u in feedback_rows],
        )
        total = (
            session.query(Job).filter(Job.user_id.isnot(None)).count()
            + session.query(WalletLedgerEntry).count()
            + session.query(Feedback).filter(Feedback.user_id.isnot(None)).count()
        )
        return events[offset : offset + limit], total
    finally:
        session.close()


def list_activity_for_user(user_id: str | uuid.UUID, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
    """Same merge as list_recent_activity, scoped to one user -- no join
    needed since the caller already has the user's identity."""
    session = get_session()
    try:
        user = session.get(User, user_id)
        if not user:
            return [], 0
        fetch_n = offset + limit
        job_rows = (
            session.query(Job)
            .filter_by(user_id=user_id)
            .order_by(Job.created_at.desc())
            .limit(fetch_n)
            .all()
        )
        wallet_rows = (
            session.query(WalletLedgerEntry)
            .filter_by(user_id=user_id)
            .order_by(WalletLedgerEntry.created_at.desc())
            .limit(fetch_n)
            .all()
        )
        feedback_rows = (
            session.query(Feedback)
            .filter_by(user_id=user_id)
            .order_by(Feedback.created_at.desc())
            .limit(fetch_n)
            .all()
        )
        events = _merge_sorted(
            [_job_event(j, user) for j in job_rows],
            [_wallet_event(w, user) for w in wallet_rows],
            [_feedback_event(f, user) for f in feedback_rows],
        )
        total = (
            session.query(Job).filter_by(user_id=user_id).count()
            + session.query(WalletLedgerEntry).filter_by(user_id=user_id).count()
            + session.query(Feedback).filter_by(user_id=user_id).count()
        )
        return events[offset : offset + limit], total
    finally:
        session.close()
