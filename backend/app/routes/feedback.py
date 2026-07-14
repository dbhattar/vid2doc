from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import get_session
from ..deps import get_current_user
from ..models import Feedback

router = APIRouter()


class FeedbackRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@router.post("/api/feedback", status_code=202)
def submit_feedback(body: FeedbackRequest, current_user: dict = Depends(get_current_user)):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Feedback message is empty")

    session = get_session()
    try:
        session.add(Feedback(user_id=current_user["id"], message=message))
        session.commit()
    finally:
        session.close()
    return {"ok": True}
