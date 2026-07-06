import uuid

from .db import get_session
from .models import User


def _user_to_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "google_sub": user.google_sub,
        "email": user.email,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "stripe_customer_id": user.stripe_customer_id,
        "created_at": user.created_at,
    }


def get_or_create_user_by_google(
    google_sub: str, email: str, display_name: str | None, avatar_url: str | None
) -> dict:
    """Looks up a user by their stable Google subject id, creating one on
    first login. Also refreshes email/display_name/avatar_url on every login
    since Google is the source of truth for that profile data."""
    session = get_session()
    try:
        user = session.query(User).filter_by(google_sub=google_sub).one_or_none()
        if user is None:
            user = User(google_sub=google_sub, email=email, display_name=display_name, avatar_url=avatar_url)
            session.add(user)
        else:
            user.email = email
            user.display_name = display_name
            user.avatar_url = avatar_url
        session.commit()
        return _user_to_dict(user)
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
