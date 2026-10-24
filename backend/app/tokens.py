from datetime import datetime, timedelta, timezone

import jwt

from .config import settings

ALGORITHM = "HS256"


def create_session_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRES_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def create_unsubscribe_token(user_id: str) -> str:
    """Never expires -- an unsubscribe link in an old email must keep working.
    The "purpose" claim keeps it from ever being accepted as a session token
    (decode_session_token would happily accept any token signed with the same
    secret that has a "sub"), and vice versa."""
    return jwt.encode({"sub": user_id, "purpose": "unsubscribe"}, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_unsubscribe_token(token: str) -> str:
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
    if payload.get("purpose") != "unsubscribe":
        raise jwt.InvalidTokenError("Not an unsubscribe token")
    return payload["sub"]


def decode_session_token(token: str) -> str:
    """Returns the user id encoded in the token. Raises jwt.PyJWTError
    (ExpiredSignatureError, InvalidTokenError, ...) on any invalid/expired
    token -- callers should catch jwt.PyJWTError, not specific subclasses."""
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
    if "purpose" in payload:
        raise jwt.InvalidTokenError("Not a session token")
    return payload["sub"]
