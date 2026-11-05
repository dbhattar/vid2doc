"""The signed-in user's own preferences -- the Settings page's Notifications
and Meetings sections. Profile data (name, email, avatar) comes from Google and
is read-only, so it isn't editable here."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import users
from ..deps import get_current_user
from .meetings import _clean_bot_name

router = APIRouter()


class PreferencesPatch(BaseModel):
    notify_job_done: bool | None = None
    notify_review_reminder: bool | None = None
    notify_meeting_notes: bool | None = None
    # Product announcements; the inverse of users.announcements_opt_out.
    product_announcements: bool | None = None
    default_bot_name: str | None = Field(default=None, max_length=50)


def _public(user: dict) -> dict:
    return {
        "notify_job_done": user["notify_job_done"],
        "notify_review_reminder": user["notify_review_reminder"],
        "notify_meeting_notes": user["notify_meeting_notes"],
        "product_announcements": not user["announcements_opt_out"],
        "default_bot_name": user["default_bot_name"] or "",
    }


@router.get("/api/me/preferences")
def get_preferences(current_user: dict = Depends(get_current_user)):
    return _public(current_user)


@router.patch("/api/me/preferences")
def update_preferences(body: PreferencesPatch, current_user: dict = Depends(get_current_user)):
    fields = body.model_dump(exclude_unset=True, exclude_none=True)
    if body.default_bot_name is not None:
        fields["default_bot_name"] = _clean_bot_name(body.default_bot_name)  # blank clears it
    if "product_announcements" in fields:
        fields["announcements_opt_out"] = not fields.pop("product_announcements")
    updated = users.update_preferences(current_user["id"], **fields) if fields else current_user
    return _public(updated)
