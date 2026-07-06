import hashlib
import secrets
from datetime import datetime, timezone

from . import users
from .db import get_session
from .models import ApiKey


def _generate_raw_key() -> str:
    return f"vd2_{secrets.token_urlsafe(32)}"


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _key_to_dict(key: ApiKey) -> dict:
    return {
        "id": str(key.id),
        "name": key.name,
        "key_prefix": key.key_prefix,
        "created_at": key.created_at,
        "last_used_at": key.last_used_at,
        "revoked_at": key.revoked_at,
    }


def create_api_key(user_id: str, name: str) -> tuple[dict, str]:
    """Returns (masked key dict, raw key). The raw key is only ever available
    here, at creation time -- it is hashed before storage and never
    retrievable again, by design."""
    raw_key = _generate_raw_key()
    session = get_session()
    try:
        key = ApiKey(user_id=user_id, name=name, key_prefix=raw_key[:12], key_hash=_hash_key(raw_key))
        session.add(key)
        session.commit()
        return _key_to_dict(key), raw_key
    finally:
        session.close()


def list_api_keys_for_user(user_id: str) -> list[dict]:
    session = get_session()
    try:
        keys = session.query(ApiKey).filter_by(user_id=user_id).order_by(ApiKey.created_at.desc()).all()
        return [_key_to_dict(k) for k in keys]
    finally:
        session.close()


def revoke_api_key(user_id: str, key_id: str) -> bool:
    """Soft-revoke (keeps the row for audit history). Returns False if the
    key doesn't exist, belongs to someone else, or is already revoked --
    callers should treat all three as a plain 404, never leaking which."""
    session = get_session()
    try:
        key = session.query(ApiKey).filter_by(id=key_id, user_id=user_id).one_or_none()
        if not key or key.revoked_at is not None:
            return False
        key.revoked_at = datetime.now(timezone.utc)
        session.commit()
        return True
    finally:
        session.close()


def get_user_by_api_key(raw_key: str) -> dict | None:
    key_hash = _hash_key(raw_key)
    session = get_session()
    try:
        key = session.query(ApiKey).filter_by(key_hash=key_hash, revoked_at=None).one_or_none()
        if not key:
            return None
        key.last_used_at = datetime.now(timezone.utc)
        user_id = key.user_id
        session.commit()
    finally:
        session.close()
    return users.get_user_by_id(user_id)
