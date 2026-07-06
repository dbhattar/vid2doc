import jwt
from fastapi import Header, HTTPException

from . import api_keys, tokens, users


def _user_from_session_jwt(authorization: str | None) -> dict:
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


def _user_from_api_key(raw_key: str) -> dict:
    user = api_keys.get_user_by_api_key(raw_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    return user


def get_current_user(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> dict:
    """Accepts either a per-user API key (X-API-Key, for programmatic
    callers) or a browser session token (Authorization: Bearer, from
    /api/auth/google) -- both resolve to the same user dict."""
    if x_api_key:
        return _user_from_api_key(x_api_key)
    return _user_from_session_jwt(authorization)


def get_current_session_user(authorization: str | None = Header(default=None)) -> dict:
    """Session-token only -- for endpoints that must not be reachable with an
    API key, e.g. minting new API keys (no self-propagating keys)."""
    return _user_from_session_jwt(authorization)
