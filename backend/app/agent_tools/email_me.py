import html

from .. import mailgun_client
from ..config import settings
from ._common import rate_limited

MAX_PER_HOUR = 10
MAX_BODY_CHARS = 10000


def available(user: dict) -> str | None:
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        return "Email isn't configured on this server."
    return None


def run(ctx: dict, args: dict) -> str:
    user = ctx["user"]
    reason = available(user)
    if reason:
        return reason
    subject = str(args.get("subject", "")).strip()[:150] or "Message from your agent"
    body = str(args.get("body", "")).strip()[:MAX_BODY_CHARS]
    if not body:
        return "Provide a body."
    if rate_limited("email_me", user["id"], MAX_PER_HOUR):
        return f"Email limit reached ({MAX_PER_HOUR} per hour) -- try again later."
    html_body = "<div style=\"font-family:sans-serif;white-space:pre-wrap\">" + html.escape(body) + "</div>"
    # Recipient is always the logged-in user -- never model-chosen.
    sent = mailgun_client.send_email(user["email"], f"[Framewrite agent] {subject}", body, html_body)
    return "Email sent to the user." if sent else "Couldn't send the email right now."


TOOL = {
    "order": 50,
    "name": "Email me a result",
    "description": "Email the agent's output to your own address.",
    "available": available,
    "functions": [
        {
            "type": "function",
            "name": "email_me",
            "description": "Send an email to the user themself (it cannot email anyone else) with a subject and plain-text body, e.g. a summary or a quiz they asked for.",
            "parameters": {
                "type": "object",
                "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
                "required": ["subject", "body"],
                "additionalProperties": False,
            },
            "strict": True,
            "run": run,
        },
    ],
}
