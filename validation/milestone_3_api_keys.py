"""Verifies Milestone 3: API key management.

Exercises key creation/masking/listing/revocation, the no-self-propagation
rule (can't mint a key using an API key), and that a real video upload made
with an API key resolves to and is scoped by the correct owning user. Run
from the repo root:

    python validation/milestone_3_api_keys.py
"""

from common import SAMPLE_VIDEO, auth_header, client, grant_wallet_credit, login_as, reset_test_user

reset_test_user("alice-m3@example.com")
reset_test_user("bob-m3@example.com")

alice = login_as("google-sub-alice-m3", "alice-m3@example.com", "Alice")
bob = login_as("google-sub-bob-m3", "bob-m3@example.com", "Bob")
alice_token = alice["access_token"]
bob_token = bob["access_token"]
grant_wallet_credit("alice-m3@example.com")  # pay-as-you-go: uploads charge the wallet

# 1. Create a key for Alice via session token
r = client.post("/api/keys", headers=auth_header(alice_token), json={"name": "CI pipeline"})
assert r.status_code == 201, r.text
created = r.json()
raw_key = created["key"]
assert raw_key.startswith("vd2_"), created
assert created["name"] == "CI pipeline"
print("Created API key OK, prefix =", created["key_prefix"])

# 2. Cannot create a new key using an API key (no self-propagation)
r = client.post("/api/keys", headers={"X-API-Key": raw_key}, json={"name": "should fail"})
assert r.status_code == 401, r.text
print("Creating a key via X-API-Key correctly rejected (401) OK")

# 3. List keys for Alice via session token -- masked, no raw key/hash
r = client.get("/api/keys", headers=auth_header(alice_token))
assert r.status_code == 200, r.text
keys_list = r.json()["keys"]
assert len(keys_list) == 1
assert "key" not in keys_list[0] and "key_hash" not in keys_list[0]
assert keys_list[0]["key_prefix"] == raw_key[:12]
print("List keys OK, masked correctly:", keys_list[0])

# 4. Empty name rejected
r = client.post("/api/keys", headers=auth_header(alice_token), json={"name": "   "})
assert r.status_code == 400, r.text
print("Empty name correctly rejected (400) OK")

# 5. Use the raw API key to call GET /api/auth/me -- should resolve to Alice
r = client.get("/api/auth/me", headers={"X-API-Key": raw_key})
assert r.status_code == 200, r.text
assert r.json()["email"] == "alice-m3@example.com", r.text
print("API key resolves to correct user via /api/auth/me OK")

# 6. Use the raw API key for a real video upload
with open(SAMPLE_VIDEO, "rb") as f:
    r = client.post(
        "/api/convert_to_doc",
        headers={"X-API-Key": raw_key},
        files={"video": ("apchem.mp4", f, "video/mp4")},
    )
assert r.status_code == 202, r.text
job_id = r.json()["job_id"]
print("Upload via API key OK, job_id =", job_id)

# job should belong to Alice, not Bob
r = client.get(f"/api/get_status?job_id={job_id}", headers=auth_header(alice_token))
assert r.status_code == 200, r.text
r = client.get(f"/api/get_status?job_id={job_id}", headers=auth_header(bob_token))
assert r.status_code == 404, r.text
print("Job correctly scoped to the API key's owning user (Alice), not Bob OK")

# 7. Bob cannot revoke Alice's key (ownership, 404 not 403)
key_id = created["id"]
r = client.delete(f"/api/keys/{key_id}", headers=auth_header(bob_token))
assert r.status_code == 404, r.text
print("Bob cannot revoke Alice's key (404) OK")

# 8. Alice revokes her own key
r = client.delete(f"/api/keys/{key_id}", headers=auth_header(alice_token))
assert r.status_code == 204, r.text
print("Alice revoked her own key OK")

# 9. Revoking again is a 404 (already revoked)
r = client.delete(f"/api/keys/{key_id}", headers=auth_header(alice_token))
assert r.status_code == 404, r.text
print("Re-revoking an already-revoked key correctly 404s OK")

# 10. The revoked key no longer authenticates
r = client.get("/api/auth/me", headers={"X-API-Key": raw_key})
assert r.status_code == 401, r.text
print("Revoked API key correctly rejected (401) OK")

# 11. Bob creates his own key, lists show only his own
client.post("/api/keys", headers=auth_header(bob_token), json={"name": "bob's key"})
r = client.get("/api/keys", headers=auth_header(bob_token))
bob_keys = r.json()["keys"]
assert len(bob_keys) == 1 and bob_keys[0]["name"] == "bob's key"
r = client.get("/api/keys", headers=auth_header(alice_token))
alice_keys = r.json()["keys"]
assert len(alice_keys) == 1 and alice_keys[0]["revoked_at"] is not None
print("Key lists are correctly isolated per-user OK")

print("\nALL MILESTONE 3 CHECKS PASSED")
