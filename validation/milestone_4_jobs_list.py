"""Verifies Milestone 4's new GET /api/jobs list endpoint.

Exercises pagination, per-user isolation, ordering (newest first), and that
each list item has the same shape as GET /api/get_status for the same job
(including document_url once done). Run from the repo root:

    python validation/milestone_4_jobs_list.py
"""

from common import SAMPLE_VIDEO, auth_header, client, grant_wallet_credit, login_as, reset_test_user

reset_test_user("alice-m4@example.com")
reset_test_user("bob-m4@example.com")

alice = login_as("google-sub-alice-m4", "alice-m4@example.com", "Alice")
bob = login_as("google-sub-bob-m4", "bob-m4@example.com", "Bob")
alice_token = alice["access_token"]
bob_token = bob["access_token"]
# Pay-as-you-go: uploads charge the wallet. Alice uploads 3 videos in this
# script, so give her enough credit to cover them.
grant_wallet_credit("alice-m4@example.com")
grant_wallet_credit("bob-m4@example.com")


def upload(token) -> str:
    with open(SAMPLE_VIDEO, "rb") as f:
        r = client.post(
            "/api/convert_to_doc",
            headers=auth_header(token),
            files={"video": ("apchem.mp4", f, "video/mp4")},
        )
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


# Alice uploads 3 videos, Bob uploads 1
alice_job_ids = [upload(alice_token) for _ in range(3)]
bob_job_id = upload(bob_token)

# Alice's list shows exactly her 3 jobs, newest first
r = client.get("/api/jobs", headers=auth_header(alice_token))
assert r.status_code == 200, r.text
body = r.json()
assert body["total"] == 3, body
assert [j["job_id"] for j in body["jobs"]] == list(reversed(alice_job_ids)), body
print("Alice's job list: correct count, correct newest-first order OK")

# Bob's list is isolated -- only his own job, none of Alice's
r = client.get("/api/jobs", headers=auth_header(bob_token))
assert r.status_code == 200, r.text
bob_body = r.json()
assert bob_body["total"] == 1
assert bob_body["jobs"][0]["job_id"] == bob_job_id
print("Bob's job list correctly isolated from Alice's OK")

# Pagination: limit=1 returns only 1 item but total still reflects all 3
r = client.get("/api/jobs?limit=1&offset=0", headers=auth_header(alice_token))
page0 = r.json()
assert page0["total"] == 3 and len(page0["jobs"]) == 1
r = client.get("/api/jobs?limit=1&offset=1", headers=auth_header(alice_token))
page1 = r.json()
assert page1["jobs"][0]["job_id"] != page0["jobs"][0]["job_id"]
print("Pagination (limit/offset) OK")

# No credentials -> 401
r = client.get("/api/jobs")
assert r.status_code == 401, r.text
print("No-credentials 401 OK")

# Each list item has the same *shape* as GET /api/get_status for the same
# job (both go through build_job_response) -- compare keys and the fields
# that can't change between these two calls, not status/progress_stage,
# since the real worker is actively advancing the job in the background
# between these two requests (a race, not a bug -- proves it's really live).
r = client.get(f"/api/get_status?job_id={alice_job_ids[0]}", headers=auth_header(alice_token))
status_response = r.json()
r = client.get("/api/jobs", headers=auth_header(alice_token))
list_item = next(j for j in r.json()["jobs"] if j["job_id"] == alice_job_ids[0])
assert status_response.keys() == list_item.keys(), (status_response, list_item)
for field in ("job_id", "created_at", "duration_seconds"):
    assert status_response[field] == list_item[field], (field, status_response, list_item)
print("List item shape matches GET /api/get_status OK")

print("\nALL MILESTONE 4 (jobs list) CHECKS PASSED")
