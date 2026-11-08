"""Public (unauthenticated) unsubscribe endpoint for announcement emails -- the
token in the link is the credential. See app/announcements.py."""

import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import tokens, users

router = APIRouter()


class UnsubscribeRequest(BaseModel):
    token: str


@router.post("/api/announcements/unsubscribe")
def unsubscribe(body: UnsubscribeRequest) -> dict:
    """POST, not GET, so mail-scanner link prefetching can't unsubscribe
    people -- the frontend's /unsubscribe page calls this on a button click.
    Takes either kind of link: the one in announcement emails (switches off
    announcements) or the one in topic-alert emails (switches off topic
    alerts) -- each token's purpose decides which."""
    invalid = HTTPException(status_code=400, detail="This unsubscribe link is invalid.")
    try:
        user_id = tokens.decode_unsubscribe_token(body.token)
        kind, done = "announcements", users.set_announcements_opt_out(user_id, True)
    except jwt.PyJWTError:
        try:
            user_id = tokens.decode_topic_unsubscribe_token(body.token)
        except jwt.PyJWTError:
            raise invalid
        kind, done = "topic_alerts", users.update_preferences(user_id, notify_topic_alerts=False) is not None
    if not done:
        raise invalid
    return {"unsubscribed": True, "kind": kind}
