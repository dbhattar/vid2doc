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
