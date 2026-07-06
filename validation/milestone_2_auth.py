"""Verifies Milestone 2: Google OAuth login + unified auth dependency.

Exercises the real POST /api/auth/google -> JWT -> GET /api/auth/me flow,
login idempotency, real video upload ownership scoping between two distinct
users, and 401 rejection paths. Run from the repo root:

    python validation/milestone_2_auth.py
"""

from common import SAMPLE_VIDEO, auth_header, client, grant_wallet_credit, login_as, reset_test_user

reset_test_user("alice@example.com")
reset_test_user("bob@example.com")

alice = login_as("google-sub-alice", "alice@example.com", "Alice")
alice_token = alice["access_token"]
grant_wallet_credit("alice@example.com")  # pay-as-you-go: uploads charge the wallet
print("Alice login OK:", alice["user"]["email"], alice["user"]["id"])

bob = login_as("google-sub-bob", "bob@example.com", "Bob")
bob_token = bob["access_token"]
print("Bob login OK:", bob["user"]["email"], bob["user"]["id"])

# re-login as alice should resolve to the SAME user id, not create a duplicate
again = login_as("google-sub-alice", "alice@example.com", "Alice")
assert again["user"]["id"] == alice["user"]["id"], "re-login created a duplicate user!"
print("Re-login idempotency OK")

# /api/auth/me
r = client.get("/api/auth/me", headers=auth_header(alice_token))
assert r.status_code == 200 and r.json()["email"] == "alice@example.com", r.text
print("GET /api/auth/me OK")

# no credentials -> 401
r = client.get("/api/auth/me")
assert r.status_code == 401, r.text
print("No-credentials 401 OK")

# bad token -> 401
r = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
assert r.status_code == 401, r.text
print("Bad-token 401 OK")

# Alice uploads a real video through the real endpoint
with open(SAMPLE_VIDEO, "rb") as f:
    r = client.post(
        "/api/convert_to_doc",
        headers=auth_header(alice_token),
        files={"video": ("apchem.mp4", f, "video/mp4")},
    )
assert r.status_code == 202, r.text
job_id = r.json()["job_id"]
print("Alice's upload OK, job_id =", job_id)

# Alice can see her own job
r = client.get(f"/api/get_status?job_id={job_id}", headers=auth_header(alice_token))
assert r.status_code == 200, r.text
print("Alice sees her own job OK:", r.json())

# Bob CANNOT see Alice's job (ownership scoping)
r = client.get(f"/api/get_status?job_id={job_id}", headers=auth_header(bob_token))
assert r.status_code == 404, r.text
print("Bob correctly gets 404 on Alice's job OK")

# no upload without credentials
with open(SAMPLE_VIDEO, "rb") as f:
    r = client.post("/api/convert_to_doc", files={"video": ("apchem.mp4", f, "video/mp4")})
assert r.status_code == 401, r.text
print("Unauthenticated upload correctly rejected with 401 OK")

print("\nALL MILESTONE 2 CHECKS PASSED")
