"""Shared setup for the milestone verification scripts in this directory.

These are not pytest tests -- they're linear, readable scripts that exercise
real HTTP flows (via FastAPI's TestClient, in-process, no server to start)
against a real Postgres database, run manually. See README.md.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
# local_test/*.mp4 is gitignored (not checked in) -- point this at any small
# local video file if you don't have this exact one.
SAMPLE_VIDEO = Path(os.environ.get("VALIDATION_SAMPLE_VIDEO", REPO_ROOT / "local_test" / "apchem.mp4"))
if not SAMPLE_VIDEO.is_file():
    raise FileNotFoundError(
        f"No sample video at {SAMPLE_VIDEO} (local_test/*.mp4 isn't checked into git). "
        "Set VALIDATION_SAMPLE_VIDEO to point at any small local .mp4 file."
    )

# Only takes effect if not already set in the environment -- lets you point
# at a different DB/config without editing this file.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://vid2doc:dev-postgres-password@localhost:55432/vid2doc")
os.environ.setdefault("DATA_DIR", "/tmp/vid2doc_validation_data")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("JWT_SECRET", "test-secret")

sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.routes import auth as auth_route  # noqa: E402

client = TestClient(app)


def reset_test_user(email: str) -> None:
    """Deletes a user by email (and their jobs/keys/ledger/subscription rows,
    since none of those FKs cascade at the schema level -- deliberately, so
    production code never accidentally loses a billing audit trail), if
    present. Lets a script be re-run repeatedly from a deterministic starting
    state instead of accumulating rows across runs. Test-only: real app code
    never hard-deletes a user like this."""
    session = get_session()
    try:
        for table in ("wallet_ledger", "api_keys", "jobs", "subscriptions"):
            session.execute(
                text(f"DELETE FROM {table} WHERE user_id = (SELECT id FROM users WHERE email = :email)"),
                {"email": email},
            )
        session.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
        session.commit()
    finally:
        session.close()


def login_as(google_sub: str, email: str, name: str = "") -> dict:
    """Logs in a fake Google user -- mocks only the network call to Google's
    verification endpoint, not any of our own code -- and returns the
    /api/auth/google response body ({"access_token", "user"}). Does NOT reset
    first (callers that want a clean slate call reset_test_user explicitly
    before their first login -- some scripts deliberately log in as the same
    identity twice in a row to test re-login idempotency, which a reset here
    would silently defeat)."""
    payload = {"sub": google_sub, "email": email, "name": name}
    with patch.object(auth_route.google_id_token, "verify_oauth2_token", return_value=payload):
        r = client.post("/api/auth/google", json={"id_token": f"fake-token-for-{google_sub}"})
    assert r.status_code == 200, r.text
    return r.json()


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
