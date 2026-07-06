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


def decode_session_token(token: str) -> str:
    """Returns the user id encoded in the token. Raises jwt.PyJWTError
    (ExpiredSignatureError, InvalidTokenError, ...) on any invalid/expired
    token -- callers should catch jwt.PyJWTError, not specific subclasses."""
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
    return payload["sub"]
