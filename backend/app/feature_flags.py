"""Admin-controlled feature gating. The meeting notetaker is the first gated
feature: it's visible to a user when they're an admin, have been switched on
individually (User.meetings_enabled), or the admin has made it generally
available (the "meetings_public" app setting). Visibility deliberately doesn't
depend on RECALL_API_KEY, so it can be set up and tried before the key exists;
sending a bot without the key fails with an error (meeting_bots.py)."""

from .db import get_session
from .models import AppSetting

MEETINGS_PUBLIC_KEY = "meetings_public"


def get_flag(key: str) -> bool:
    session = get_session()
    try:
        row = session.get(AppSetting, key)
        return row is not None and row.value == "true"
    finally:
        session.close()


def set_flag(key: str, value: bool) -> None:
    session = get_session()
    try:
        row = session.get(AppSetting, key)
        if row:
            row.value = "true" if value else "false"
        else:
            session.add(AppSetting(key=key, value="true" if value else "false"))
        session.commit()
    finally:
        session.close()


def meetings_available_for(user: dict) -> bool:
    return bool(user.get("is_admin") or user.get("meetings_enabled") or get_flag(MEETINGS_PUBLIC_KEY))
