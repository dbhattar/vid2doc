from . import crypto
from .db import get_session
from .models import GoogleDriveConnection


def _connection_to_dict(conn: GoogleDriveConnection) -> dict:
    return {
        "id": str(conn.id),
        "user_id": str(conn.user_id),
        "google_email": conn.google_email,
        "refresh_token_encrypted": conn.refresh_token_encrypted,
        "scope": conn.scope,
        "created_at": conn.created_at,
    }


def get_connection_for_user(user_id: str) -> dict | None:
    session = get_session()
    try:
        conn = session.query(GoogleDriveConnection).filter_by(user_id=user_id).one_or_none()
        return _connection_to_dict(conn) if conn else None
    finally:
        session.close()


def save_connection(user_id: str, google_email: str, refresh_token: str, scope: str) -> dict:
    """Upsert -- a user reconnecting replaces the row rather than erroring,
    since a stale/revoked refresh token is exactly why they'd reconnect."""
    refresh_token_encrypted = crypto.encrypt(refresh_token)
    session = get_session()
    try:
        conn = session.query(GoogleDriveConnection).filter_by(user_id=user_id).one_or_none()
        if conn is None:
            conn = GoogleDriveConnection(user_id=user_id, google_email=google_email, scope=scope)
            session.add(conn)
        else:
            conn.google_email = google_email
            conn.scope = scope
        conn.refresh_token_encrypted = refresh_token_encrypted
        session.commit()
        return _connection_to_dict(conn)
    finally:
        session.close()


def delete_connection(user_id: str) -> bool:
    session = get_session()
    try:
        conn = session.query(GoogleDriveConnection).filter_by(user_id=user_id).one_or_none()
        if not conn:
            return False
        session.delete(conn)
        session.commit()
        return True
    finally:
        session.close()
