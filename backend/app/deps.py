import jwt
from fastapi import Header, HTTPException

from . import tokens, users


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    """Session-JWT auth only for now -- API-key auth (for programmatic
    /api/convert_to_doc callers) is added alongside this in the API-key
    management milestone, as a second branch checked via X-API-Key."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing credentials")

    token = authorization.removeprefix("Bearer ")
    try:
        user_id = tokens.decode_session_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")

    user = users.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
