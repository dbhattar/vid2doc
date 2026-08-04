from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import feedback
from ..deps import get_current_user
from ..turnstile import verify_turnstile_token

router = APIRouter()


class FeedbackRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@router.post("/api/feedback", status_code=202)
def submit_feedback(body: FeedbackRequest, current_user: dict = Depends(get_current_user)):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Feedback message is empty")

    feedback.create_feedback(current_user["id"], message, source="app")
    return {"ok": True}


class PublicFeedbackRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    email: str | None = Field(default=None, max_length=320)
    turnstile_token: str


@router.post("/api/public/feedback", status_code=202)
def submit_public_feedback(body: PublicFeedbackRequest, request: Request):
    """Unauthenticated counterpart to /api/feedback for the marketing site's
    floating feedback widget -- same storage, source="marketing" and no
    user_id since visitors there aren't logged in. Turnstile-gated instead of
    auth-gated, same defense used for the anonymous trial upload
    (routes/trial.py)."""
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Feedback message is empty")

    ip = request.client.host if request.client else "unknown"
    if not verify_turnstile_token(body.turnstile_token, ip):
        raise HTTPException(status_code=403, detail="Verification failed -- please try again.")

    email = body.email.strip() or None if body.email else None
    feedback.create_feedback(None, message, email=email, source="marketing")
    return {"ok": True}
