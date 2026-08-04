from .db import get_session
from .models import Feedback, User


def create_feedback(
    user_id: str | None, message: str, email: str | None = None, source: str = "app"
) -> None:
    session = get_session()
    try:
        session.add(Feedback(user_id=user_id, message=message, email=email, source=source))
        session.commit()
    finally:
        session.close()


def list_feedback_with_users(limit: int = 500) -> list[dict]:
    """Newest first, left-joined with the submitting user's identity --
    marketing-site submissions have no user (see models.Feedback), so this
    can't be an inner join. Read-only, no reviewed/status field yet."""
    session = get_session()
    try:
        rows = (
            session.query(Feedback, User)
            .outerjoin(User, Feedback.user_id == User.id)
            .order_by(Feedback.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": str(f.id),
                "user_id": str(f.user_id) if f.user_id else None,
                "email": u.email if u else f.email,
                "display_name": u.display_name if u else None,
                "source": f.source,
                "message": f.message,
                "created_at": f.created_at,
            }
            for f, u in rows
        ]
    finally:
        session.close()
