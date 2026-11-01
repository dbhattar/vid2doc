"""Requests for gated features (feature_flags.py). One open request per
user+feature; an admin resolves it from routes/admin.py."""

from datetime import datetime, timezone

from .db import get_session
from .models import FeatureRequest, User


def _to_dict(r: FeatureRequest, user: User | None = None) -> dict:
    d = {
        "id": str(r.id),
        "user_id": str(r.user_id),
        "feature": r.feature,
        "message": r.message,
        "status": r.status,
        "created_at": r.created_at,
        "resolved_at": r.resolved_at,
    }
    if user is not None:
        d["email"] = user.email
        d["display_name"] = user.display_name
    return d


def create_request(user_id: str, feature: str, message: str | None) -> tuple[dict, bool]:
    """Returns (request, created). If the user already has a pending request
    for this feature it's returned untouched (created=False) so a double click
    or re-submit can't pile up duplicates."""
    session = get_session()
    try:
        existing = (
            session.query(FeatureRequest)
            .filter_by(user_id=user_id, feature=feature, status="pending")
            .first()
        )
        if existing:
            return _to_dict(existing), False
        request = FeatureRequest(user_id=user_id, feature=feature, message=message or None)
        session.add(request)
        session.commit()
        session.refresh(request)
        return _to_dict(request), True
    finally:
        session.close()


def get_latest_for_user(user_id: str, feature: str) -> dict | None:
    session = get_session()
    try:
        row = (
            session.query(FeatureRequest)
            .filter_by(user_id=user_id, feature=feature)
            .order_by(FeatureRequest.created_at.desc())
            .first()
        )
        return _to_dict(row) if row else None
    finally:
        session.close()


def get_request(request_id: str) -> dict | None:
    session = get_session()
    try:
        row = session.get(FeatureRequest, request_id)
        return _to_dict(row) if row else None
    finally:
        session.close()


def list_requests(status: str = "pending", limit: int = 200) -> list[dict]:
    session = get_session()
    try:
        rows = (
            session.query(FeatureRequest, User)
            .join(User, FeatureRequest.user_id == User.id)
            .filter(FeatureRequest.status == status)
            .order_by(FeatureRequest.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_dict(r, u) for r, u in rows]
    finally:
        session.close()


def resolve_request(request_id: str, status: str) -> dict | None:
    """pending -> approved|declined. None if it doesn't exist or was already
    resolved (so two admins can't both act on it)."""
    session = get_session()
    try:
        row = session.get(FeatureRequest, request_id)
        if row is None or row.status != "pending":
            return None
        row.status = status
        row.resolved_at = datetime.now(timezone.utc)
        session.commit()
        return _to_dict(row)
    finally:
        session.close()


def resolve_pending_for_user(user_id: str, feature: str, status: str) -> int:
    """Closes any open request for a user (e.g. an admin enabled the feature
    directly, without going through the request). Returns how many it closed."""
    session = get_session()
    try:
        rows = session.query(FeatureRequest).filter_by(user_id=user_id, feature=feature, status="pending").all()
        for row in rows:
            row.status = status
            row.resolved_at = datetime.now(timezone.utc)
        session.commit()
        return len(rows)
    finally:
        session.close()
