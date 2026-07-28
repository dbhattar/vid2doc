from .db import get_session
from .models import Feedback, User


def create_feedback(user_id: str, message: str) -> None:
    session = get_session()
    try:
        session.add(Feedback(user_id=user_id, message=message))
        session.commit()
    finally:
        session.close()


def list_feedback_with_users(limit: int = 500) -> list[dict]:
    """Newest first, joined with the submitting user's identity -- read-only,
    no reviewed/status field yet (see models.Feedback)."""
    session = get_session()
    try:
        rows = (
            session.query(Feedback, User)
            .join(User, Feedback.user_id == User.id)
            .order_by(Feedback.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": str(f.id),
                "user_id": str(f.user_id),
                "email": u.email,
                "display_name": u.display_name,
                "message": f.message,
                "created_at": f.created_at,
            }
            for f, u in rows
        ]
    finally:
        session.close()
