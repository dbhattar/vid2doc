"""Cloudflare Turnstile verification for the marketing site's anonymous
feedback widget (routes/feedback.py) -- the primary defense against
scripted/bot submissions to an endpoint that has no auth and no billing
gate to throttle it otherwise.
"""

import requests

from .config import settings

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_turnstile_token(token: str, remote_ip: str) -> bool:
    """Fails closed: a misconfigured secret, a network error, or an
    unexpected response all mean "not verified" rather than silently letting
    the upload through unprotected."""
    if not settings.TURNSTILE_SECRET_KEY or not token:
        return False
    try:
        response = requests.post(
            VERIFY_URL,
            data={"secret": settings.TURNSTILE_SECRET_KEY, "response": token, "remoteip": remote_ip},
            timeout=5,
        )
        return bool(response.json().get("success"))
    except (requests.RequestException, ValueError):
        return False
