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
    people -- the frontend's /unsubscribe page calls this on a button click."""
    try:
        user_id = tokens.decode_unsubscribe_token(body.token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="This unsubscribe link is invalid.")
    if not users.set_announcements_opt_out(user_id, True):
        raise HTTPException(status_code=400, detail="This unsubscribe link is invalid.")
    return {"unsubscribed": True}
