"""What a user is told about a failed job. `jobs.error_message` holds the raw
error (admins see all of it: the admin jobs page), but some of those are
provider internals -- an AI vendor's "no credits remaining" billing notice, a
rejected API key, a raw SDK error dump -- that mean nothing to a customer, can
look like their wallet is at fault, and shouldn't be shown to them. Those are
replaced with a plain message; everything else (the pipeline's own messages,
written to be shown) passes through.
"""

import re

GENERIC_MESSAGE = (
    "Something went wrong on our side while processing this. "
    "Any charge was refunded -- please try again in a little while."
)

# An SDK error's str() is "Error code: 429 - {...}"; the rest are the vendors'
# billing/auth wording and our own missing-config messages.
_INTERNAL = re.compile(
    r"^\s*Error code: \d{3}"
    r"|insufficient_quota|credit_balance|no credits remaining|exceeded your current quota"
    r"|invalid_api_key|incorrect api key|authentication_error|permission_denied"
    r"|\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_(?:API_KEY|MODEL_URL) is not set"
    r"|No transcription engine configured",
    re.IGNORECASE,
)


def user_facing_error(message: str | None) -> str | None:
    if not message:
        return message
    return GENERIC_MESSAGE if _INTERNAL.search(message) else message
