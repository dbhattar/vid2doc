import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import mailgun_client

router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NewsletterSignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


@router.post("/api/public/newsletter", status_code=202)
def subscribe_to_newsletter(body: NewsletterSignupRequest):
    """Public, unauthenticated -- adds an address to the Mailgun newsletter
    list. Best-effort like send_email: a well-formed address always gets a
    success response, Mailgun/list failures are only logged server-side, not
    surfaced as an error to the visitor."""
    email = body.email.strip()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    mailgun_client.add_to_mailing_list(email)
    return {"ok": True}
