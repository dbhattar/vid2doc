"""Users asking for access to the gated Meetings preview. Admins resolve the
requests from routes/admin.py."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import emails, feature_flags, feature_requests
from ..deps import get_current_user

router = APIRouter()

FEATURE = "meetings"


class RequestAccessBody(BaseModel):
    message: str | None = Field(default=None, max_length=1000)


def _state(current_user: dict) -> dict:
    has_access = feature_flags.meetings_available_for(current_user)
    latest = feature_requests.get_latest_for_user(str(current_user["id"]), FEATURE)
    return {"has_access": has_access, "request_status": latest["status"] if latest else None}


@router.get("/api/features/meetings/request")
def get_meetings_request_state(current_user: dict = Depends(get_current_user)):
    return _state(current_user)


@router.post("/api/features/meetings/request", status_code=201)
def request_meetings_access(
    body: RequestAccessBody, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)
):
    if feature_flags.meetings_available_for(current_user):
        raise HTTPException(status_code=400, detail="You already have access to Meetings.")
    message = (body.message or "").strip() or None
    request, created = feature_requests.create_request(str(current_user["id"]), FEATURE, message)
    if created:
        background_tasks.add_task(emails.notify_feature_request, request["id"])
    return _state(current_user) | {"request_status": request["status"]}
