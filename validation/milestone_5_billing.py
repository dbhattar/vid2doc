"""Verifies pay-as-you-go wallet billing ($1.00/video-hour, no plans/tiers).

Mocks only the actual Stripe network calls (stripe.Customer.create,
stripe.checkout.Session.create) -- everything else is real: our own wallet
ledger math, webhook signature verification (via Stripe's own public HMAC
scheme, see common.sign_stripe_webhook_payload), idempotency, and the
balance check in /api/convert_to_doc. Run from the repo root:

    python validation/milestone_5_billing.py
"""

import json
import math
import subprocess
import uuid
from unittest.mock import MagicMock, patch

from common import SAMPLE_VIDEO, auth_header, client, login_as, reset_test_user, sign_stripe_webhook_payload

from app import billing
from app.routes import billing as billing_route

reset_test_user("alice-m5@example.com")
alice = login_as("google-sub-alice-m5", "alice-m5@example.com", "Alice")
alice_token = alice["access_token"]
alice_id = alice["user"]["id"]

# Exact duration of the sample video, computed the same way the backend
# does, so the expected charge isn't a hardcoded number tied to one file.
sample_duration = float(
    subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(SAMPLE_VIDEO)],
        capture_output=True,
        text=True,
    ).stdout.strip()
)
expected_cost_cents = math.ceil(sample_duration / billing.SECONDS_PER_CENT)


def post_webhook(event_type: str, obj: dict, event_id: str | None = None):
    body = json.dumps({"id": event_id or f"evt_{uuid.uuid4()}", "type": event_type, "data": {"object": obj}}).encode()
    sig = sign_stripe_webhook_payload(body)
    return client.post(
        "/api/billing/webhook", content=body, headers={"stripe-signature": sig, "Content-Type": "application/json"}
    )


def upload():
    with open(SAMPLE_VIDEO, "rb") as f:
        return client.post(
            "/api/convert_to_doc", headers=auth_header(alice_token), files={"video": ("apchem.mp4", f, "video/mp4")}
        )


def wallet_balance():
    return client.get("/api/billing/wallet", headers=auth_header(alice_token)).json()["balance_cents"]


# 1. No wallet credit at all -> upload hard-blocked with 402
assert wallet_balance() == 0
r = upload()
assert r.status_code == 402, r.text
print("Upload blocked with $0 balance (402) OK")

# 2. Top-up checkout session creation (mocking only the Stripe network call)
fake_customer = MagicMock(id="cus_test_alice")
fake_checkout_session = MagicMock(url="https://checkout.stripe.com/test-session")
with patch.object(billing_route.stripe.Customer, "create", return_value=fake_customer) as mock_create_customer:
    with patch.object(billing_route.stripe.checkout.Session, "create", return_value=fake_checkout_session) as mock_checkout:
        r = client.post(
            "/api/billing/checkout/topup", headers=auth_header(alice_token), json={"amount_cents": 2000}
        )
assert r.status_code == 200 and r.json()["url"] == "https://checkout.stripe.com/test-session", r.text
mock_create_customer.assert_called_once_with(email="alice-m5@example.com")
assert mock_checkout.call_args.kwargs["mode"] == "payment"
assert mock_checkout.call_args.kwargs["line_items"][0]["price_data"]["unit_amount"] == 2000
assert mock_checkout.call_args.kwargs["customer"] == "cus_test_alice"
print("Top-up checkout session creation OK (correct amount + customer)")

# 3. Rejects amounts outside the allowed $5-$1000 range
r = client.post("/api/billing/checkout/topup", headers=auth_header(alice_token), json={"amount_cents": 100})
assert r.status_code == 422, r.text
print("Top-up amount below minimum correctly rejected (422) OK")

# 4. stripe_customer_id was persisted -- a second call must NOT create another Stripe customer
with patch.object(billing_route.stripe.Customer, "create") as mock_create_customer_again:
    with patch.object(billing_route.stripe.checkout.Session, "create", return_value=fake_checkout_session):
        client.post("/api/billing/checkout/topup", headers=auth_header(alice_token), json={"amount_cents": 2000})
mock_create_customer_again.assert_not_called()
print("Stripe customer id reused (not recreated) on second checkout OK")

# 5. checkout.session.completed (mode=payment) webhook credits the wallet
r = post_webhook("checkout.session.completed", {"mode": "payment", "customer": "cus_test_alice", "amount_total": 2000, "payment_intent": "pi_test_1"})
assert r.status_code == 200, r.text
assert wallet_balance() == 2000, wallet_balance()
print("checkout.session.completed credited the wallet by the correct amount OK")

# 6. Webhook idempotency: replaying the same event id doesn't double-credit
event_id = f"evt_{uuid.uuid4()}"
r1 = post_webhook("checkout.session.completed", {"mode": "payment", "customer": "cus_test_alice", "amount_total": 500, "payment_intent": "pi_test_2"}, event_id=event_id)
r2 = post_webhook("checkout.session.completed", {"mode": "payment", "customer": "cus_test_alice", "amount_total": 500, "payment_intent": "pi_test_2"}, event_id=event_id)
assert r1.status_code == 200 and r2.status_code == 200
assert r2.json()["status"] == "already processed", r2.json()
assert wallet_balance() == 2500, wallet_balance()  # +500 exactly once, not twice
print("Webhook replay with the same event id credits exactly once OK")

# 7. Upload now succeeds and charges exactly $1/hour proportionally
balance_before = wallet_balance()
r = upload()
assert r.status_code == 202, r.text
job_id = r.json()["job_id"]
assert wallet_balance() == balance_before - expected_cost_cents, (wallet_balance(), balance_before, expected_cost_cents)
print(f"Upload succeeded and charged exactly {expected_cost_cents}c (${expected_cost_cents / 100:.2f}) OK")

# 8. Job failure refunds the exact amount charged (simulated directly --
# these validation scripts don't run the full real pipeline, see milestone_4_document_bundle.py for the same pattern)
balance_before_refund = wallet_balance()
billing.refund_job_charge(alice_id, job_id, expected_cost_cents)
assert wallet_balance() == balance_before_refund + expected_cost_cents
print("refund_job_charge restores the exact charged amount OK")

# 9. Insufficient balance: drain to just under one more video's cost
r = client.get("/api/billing/wallet", headers=auth_header(alice_token))
remaining = r.json()["balance_cents"]
billing.charge_for_job(alice_id, f"validation-drain-{uuid.uuid4()}", (remaining - 1) * billing.SECONDS_PER_CENT)
assert wallet_balance() <= 1
r = upload()
assert r.status_code == 402, r.text
assert "Insufficient balance" in r.json()["detail"], r.json()
print("Upload blocked once balance can't cover the video's cost (402) OK")

# 10. Bad webhook signature -> 400
r = client.post(
    "/api/billing/webhook",
    content=b'{"id": "evt_bad", "type": "checkout.session.completed", "data": {"object": {}}}',
    headers={"stripe-signature": "t=0,v1=deadbeef", "Content-Type": "application/json"},
)
assert r.status_code == 400, r.text
print("Invalid webhook signature correctly rejected (400) OK")

# 11. No credentials -> 401
r = client.get("/api/billing/wallet")
assert r.status_code == 401, r.text
print("No-credentials 401 on GET /api/billing/wallet OK")

print("\nALL MILESTONE 5 (pay-as-you-go wallet) CHECKS PASSED")
