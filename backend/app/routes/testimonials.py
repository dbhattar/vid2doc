from fastapi import APIRouter

from .. import testimonials

router = APIRouter()


@router.get("/api/public/testimonials")
def list_public_testimonials() -> dict:
    """Public, unauthenticated -- feeds the marketing homepage's
    Testimonials section (see marketing/src/components/Testimonials/). An
    empty list is a normal, expected response (no testimonials added yet):
    the marketing site hides the whole section rather than showing it empty."""
    return {"testimonials": testimonials.list_testimonials()}
