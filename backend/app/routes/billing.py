from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import billing, users
from ..config import settings
from ..deps import get_current_session_user, get_current_user
from ..stripe_client import stripe

router = APIRouter()


class TopUpRequest(BaseModel):
    amount_cents: int = Field(ge=500, le=100_000)  # $5 - $1000 per top-up


@router.post("/api/billing/checkout/topup")
def create_topup_checkout(body: TopUpRequest, current_user: dict = Depends(get_current_session_user)):
    customer_id = billing.get_or_create_stripe_customer(current_user)
    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": body.amount_cents,
                    "product_data": {"name": "Framewrite wallet top-up"},
                },
                "quantity": 1,
            }
        ],
        success_url=f"{settings.FRONTEND_URL}/settings/billing?status=success",
        cancel_url=f"{settings.FRONTEND_URL}/settings/billing?status=cancelled",
    )
    return {"url": session.url}


@router.get("/api/billing/wallet")
def get_wallet(current_user: dict = Depends(get_current_user)):
    return {"balance_cents": billing.get_wallet_balance_cents(current_user["id"])}


@router.post("/api/billing/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid webhook payload or signature")

    if not billing.claim_webhook_event(event["id"]):
        return {"status": "already processed"}

    if event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        if obj.get("mode") == "payment":
            user = users.get_user_by_stripe_customer_id(obj["customer"])
            if user:
                billing.credit_topup(user["id"], obj["amount_total"], obj.get("payment_intent"))

    return {"status": "ok"}
