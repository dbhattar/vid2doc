"""Encrypts/decrypts stored OAuth refresh tokens (Google Drive connections --
see app/routes/drive.py). Nothing here is usable without ENCRYPTION_KEY.
Distinct from app/api_keys.py's SHA256 hashing: that's one-way by design
(only proof-of-possession is ever needed), but Drive uploads need the
actual refresh token back, so this has to be reversible."""

from cryptography.fernet import Fernet, InvalidToken  # noqa: F401 -- re-exported for callers to catch

from .config import settings


def _fernet() -> Fernet:
    if not settings.ENCRYPTION_KEY:
        raise RuntimeError("ENCRYPTION_KEY is not set -- Drive integration is not configured")
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Raises cryptography.fernet.InvalidToken if ENCRYPTION_KEY was rotated
    or the value is corrupt -- callers should treat that the same as a
    revoked connection (surface as 'reconnect Drive')."""
    return _fernet().decrypt(ciphertext.encode()).decode()
