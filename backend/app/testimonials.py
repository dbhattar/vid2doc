from .db import get_session
from .models import Testimonial


def create_testimonial(quote: str, author_name: str, author_role: str | None = None) -> None:
    """No route calls this yet -- there's no admin UI for testimonials, so
    for now a row is added directly, e.g. via a one-off script:

        from app.testimonials import create_testimonial
        create_testimonial("Quote here.", "Jane Doe", "Product Manager, Acme")

    Kept here (rather than only inline SQL) so that one-off insert goes
    through the same model/validation path everything else does."""
    session = get_session()
    try:
        session.add(Testimonial(quote=quote, author_name=author_name, author_role=author_role))
        session.commit()
    finally:
        session.close()


def list_testimonials(limit: int = 20) -> list[dict]:
    """Oldest first -- curated quotes are added in the order they're
    collected, and that's the order they should read on the page."""
    session = get_session()
    try:
        rows = session.query(Testimonial).order_by(Testimonial.created_at.asc()).limit(limit).all()
        return [
            {"quote": t.quote, "name": t.author_name, "role": t.author_role}
            for t in rows
        ]
    finally:
        session.close()
