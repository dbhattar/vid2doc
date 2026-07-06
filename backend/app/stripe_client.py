"""Single place the Stripe SDK gets configured. Other modules should import
`stripe` from here (`from .stripe_client import stripe`), not `import stripe`
directly, so `stripe.api_key` is guaranteed set before use."""

import stripe

from .config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

__all__ = ["stripe"]
