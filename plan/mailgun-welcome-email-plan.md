# Mailgun welcome email on first login

## Context

There is currently zero outbound email in this codebase (confirmed via a full grep for mailgun/smtp/sendgrid/ses/email-sending code). The first step toward a Mailgun-based transactional email system is: send a welcome email the moment a user's account is created via Google Sign-In (i.e. their very first login, not every subsequent one).

The natural hook is `get_or_create_user_by_google` (`backend/app/users.py:23-46`), called from the single login route `POST /api/auth/google` (`backend/app/routes/auth.py:19-35`). It already branches internally on "does a `User` row exist for this `google_sub`" — it just doesn't surface that fact to its caller today.

## Design decisions

- **Email is best-effort, never blocking or failing login.** Mailgun is called via FastAPI's built-in `BackgroundTasks` (no new dependency — nothing in this codebase uses Celery/RQ for lightweight work; the existing `worker.py` polling loop is for heavy video-pipeline jobs only and would be overkill here) so the HTTP response to the frontend returns immediately, and a Mailgun outage/latency never affects sign-in.
- **No-op when unconfigured.** If `MAILGUN_API_KEY`/`MAILGUN_DOMAIN` aren't set, the send function logs and returns `False` instead of raising — mirrors how `STRIPE_SECRET_KEY`/`ASSEMBLYAI_API_KEY`-style optional integrations already behave in this codebase (config.py), so local dev/CI never needs real Mailgun credentials.
- **Plain `requests` call, no Mailgun SDK.** `requests==2.32.3` is already a dependency; Mailgun's API is a single `POST .../messages` call with HTTP basic auth, so a small wrapper is simpler than adding a new SDK dependency for one call site.
- **Plain-text email for this first pass** (no HTML template) — matches "as a start" scope; an HTML version can follow once the plain-text path is proven.

## Backend changes

**`backend/app/config.py`** — add a new settings block, following the existing `os.environ.get(...)` pattern used for `STRIPE_SECRET_KEY` etc.:
```python
# Mailgun: transactional email (e.g. the first-login welcome email, see
# app/mailgun_client.py). No-op if MAILGUN_API_KEY/MAILGUN_DOMAIN are unset,
# so local dev/CI never need real credentials.
MAILGUN_API_KEY = os.environ.get("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.environ.get("MAILGUN_DOMAIN", "")
MAILGUN_FROM_EMAIL = os.environ.get("MAILGUN_FROM_EMAIL", "Framewrite <noreply@framewrite.cc>")
# EU-region Mailgun accounts use https://api.eu.mailgun.net/v3 instead.
MAILGUN_BASE_URL = os.environ.get("MAILGUN_BASE_URL", "https://api.mailgun.net/v3")
# Mailgun's own test mode (o:testmode=yes): validates the API key/domain and
# request shape, logs the call in the Mailgun dashboard, but never actually
# delivers the email. Lets you verify the whole integration against a real
# Mailgun account locally without risking a real send. Leave false in prod.
MAILGUN_TEST_MODE = os.environ.get("MAILGUN_TEST_MODE", "false").strip().lower() == "true"
```

**`backend/.env.example`** — add a matching documented block (same style as the Stripe section) near the other integration keys, including `MAILGUN_TEST_MODE=false` with a comment pointing out it can be set to `true` locally to exercise the real API without delivering anything.

**New file `backend/app/mailgun_client.py`** — thin, provider-specific wrapper:
```python
import logging

import requests

from .config import settings

logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, text: str, html: str | None = None) -> bool:
    """Sends via Mailgun's REST API. No-op (returns False) if Mailgun isn't
    configured -- callers should treat email as best-effort, never something
    a request should fail over."""
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.info("Mailgun not configured, skipping email to %s", to_email)
        return False

    data = {"from": settings.MAILGUN_FROM_EMAIL, "to": [to_email], "subject": subject, "text": text}
    if html:
        data["html"] = html
    if settings.MAILGUN_TEST_MODE:
        data["o:testmode"] = "yes"

    try:
        response = requests.post(
            f"{settings.MAILGUN_BASE_URL}/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=data,
            timeout=10,
        )
        response.raise_for_status()
        return True
    except requests.RequestException:
        logger.exception("Failed to send email to %s via Mailgun", to_email)
        return False
```

**New file `backend/app/emails.py`** — composes specific transactional emails (keeps copy/templates separate from the transport, so later emails just add functions here):
```python
from .mailgun_client import send_email


def send_welcome_email(user: dict) -> None:
    name = user.get("display_name") or user["email"].split("@")[0]
    subject = "Welcome to Framewrite"
    text = (
        f"Hi {name},\n\n"
        "Welcome to Framewrite! Upload a video or audio file and we'll turn it into "
        "a clean, searchable document -- full transcript, speaker labels, and the "
        "right images in the right places.\n\n"
        "Pay-as-you-go, no subscription: $1/hour of video, $0.40/hour of audio.\n\n"
        "-- The Framewrite team"
    )
    send_email(user["email"], subject, text)
```

**`backend/app/users.py`** — change `get_or_create_user_by_google` to return `(user, is_new)` instead of just `user`, so the route can detect first login. Confirmed via grep this function has exactly one caller (`routes/auth.py`), so this is a safe signature change:
```python
def get_or_create_user_by_google(
    google_sub: str, email: str, display_name: str | None, avatar_url: str | None
) -> tuple[dict, bool]:
    """Returns (user, is_new) -- is_new is True only the first time this
    google_sub logs in, so callers can trigger first-login-only side effects
    (e.g. the welcome email in routes/auth.py)."""
    session = get_session()
    try:
        user = session.query(User).filter_by(google_sub=google_sub).one_or_none()
        is_new = user is None
        if is_new:
            user = User(google_sub=google_sub, email=email, display_name=display_name, avatar_url=avatar_url)
            session.add(user)
        else:
            user.email = email
            user.display_name = display_name
            user.avatar_url = avatar_url
        if email.lower() in settings.ADMIN_EMAILS:
            user.is_admin = True
        session.commit()
        return _user_to_dict(user), is_new
    finally:
        session.close()
```

**`backend/app/routes/auth.py`** — accept `BackgroundTasks`, unpack the new tuple, and schedule the welcome email only when `is_new`:
```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
...
from .. import emails, tokens, users
...
@router.post("/api/auth/google")
def login_with_google(body: GoogleLoginRequest, background_tasks: BackgroundTasks):
    try:
        payload = google_id_token.verify_oauth2_token(
            body.id_token, _google_request, settings.GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google ID token")

    user, is_new = users.get_or_create_user_by_google(
        google_sub=payload["sub"],
        email=payload["email"],
        display_name=payload.get("name"),
        avatar_url=payload.get("picture"),
    )
    if is_new:
        background_tasks.add_task(emails.send_welcome_email, user)
    access_token = tokens.create_session_token(user["id"])
    return {"access_token": access_token, "user": user}
```

No changes needed to `requirements.txt` (`requests` already present), `docker-compose.yml` (both `api`/`worker` already load `env_file: .env`, so new keys reach the container automatically), or the database (no schema change).

## Files touched

- `backend/app/config.py` — new Mailgun settings block.
- `backend/.env.example` — documented Mailgun env vars.
- `backend/app/mailgun_client.py` (new) — `send_email`.
- `backend/app/emails.py` (new) — `send_welcome_email`.
- `backend/app/users.py` — `get_or_create_user_by_google` now returns `(user, is_new)`.
- `backend/app/routes/auth.py` — schedule the welcome email as a background task on first login.

## Verification

1. `python3 -m py_compile` the changed/new backend files to catch syntax errors.
2. **No credentials at all** (default local `.env`): log in with a fresh Google account — confirm login still succeeds normally and the log shows "Mailgun not configured, skipping email" rather than any error. Confirms the trigger logic without touching Mailgun at all.
3. **Real credentials + `MAILGUN_TEST_MODE=true`**: set real `MAILGUN_API_KEY`/`MAILGUN_DOMAIN`/`MAILGUN_FROM_EMAIL` plus `MAILGUN_TEST_MODE=true`, log in with a brand-new Google account, and confirm the request succeeds (HTTP 200 from Mailgun, no exception logged) — check the Mailgun dashboard's log to see the test-mode send recorded, then confirm no actual email arrives anywhere. Validates the whole integration (auth, payload, domain) with zero delivery risk.
4. **Real send (optional, sandbox domain)**: set `MAILGUN_TEST_MODE=false` with a Mailgun sandbox domain and your own email added as an authorized recipient, log in with a new account using that email, and confirm a real welcome email arrives addressed correctly.
5. Log in again with the same account used in step 3 or 4 (now existing) and confirm no second welcome email is sent/logged.
6. Temporarily point `MAILGUN_DOMAIN` at an invalid domain to force a Mailgun error, log in with a new account, and confirm login still succeeds (background task swallows the error) and the log shows the exception from `mailgun_client.send_email`.
