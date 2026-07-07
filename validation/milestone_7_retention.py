"""Verifies Milestone 7: retention sweep.

Constructs jobs directly (writing fake document/upload files to disk,
backdating created_at) rather than running the full real pipeline or
waiting 7 real days -- retention.py's job is finding the right rows and
deleting the right files, not re-testing transcription. Exercises three
cases in the same sweep: an old done job (should be cleaned up), a fresh
done job (should NOT be touched), and an old but non-done job (should NOT
be touched -- retention only applies to done jobs). Run from the repo root:

    python validation/milestone_7_retention.py
"""

import uuid
from datetime import datetime, timedelta, timezone

from common import auth_header, client, login_as, reset_test_user

import retention
from app import jobs
from app.config import settings

reset_test_user("alice-m7@example.com")
alice = login_as("google-sub-alice-m7", "alice-m7@example.com", "Alice")
alice_token = alice["access_token"]
alice_id = alice["user"]["id"]

EIGHT_DAYS_AGO = datetime.now(timezone.utc) - timedelta(days=8)


def make_done_job(created_at: datetime) -> str:
    job_id = f"validation-retention-{uuid.uuid4()}"
    doc_dir = settings.OUTPUT_DIR / job_id / "document"
    images_dir = doc_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "document.md").write_text("# Test\n")
    (images_dir / "slide1.jpg").write_bytes(b"fake-jpeg")
    upload_dir = settings.UPLOADS_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / "source.mp4").write_bytes(b"fake-video")

    jobs.create_job(job_id, str(upload_dir / "source.mp4"), user_id=alice_id, duration_seconds=60)
    jobs.update_job(job_id, status="done", document_path=str(doc_dir / "document.md"), created_at=created_at)
    return job_id


# Case 1: an old `done` job -- should be cleaned up
old_done_job_id = make_done_job(EIGHT_DAYS_AGO)

# Case 2: a fresh `done` job -- should NOT be touched
fresh_done_job_id = make_done_job(datetime.now(timezone.utc))

# Case 3: an old but `failed` job -- should NOT be touched (retention only applies to `done`)
old_failed_job_id = f"validation-retention-{uuid.uuid4()}"
jobs.create_job(old_failed_job_id, "/tmp/fake.mp4", user_id=alice_id, duration_seconds=60)
jobs.update_job(old_failed_job_id, status="failed", error_message="boom", created_at=EIGHT_DAYS_AGO)

retention.main()

# --- Case 1 assertions: cleaned up ---
job = jobs.get_job(old_done_job_id)
assert job["deleted_at"] is not None, job
assert job["document_path"] is None, job  # source_path is left as historical metadata, not nulled (NOT NULL column)
assert not (settings.OUTPUT_DIR / old_done_job_id).exists(), "output dir should have been deleted"
assert not (settings.UPLOADS_DIR / old_done_job_id).exists(), "uploads dir should have been deleted"
print("Old done job: files deleted, row kept with deleted_at set OK")

r = client.get(f"/api/get_status?job_id={old_done_job_id}", headers=auth_header(alice_token))
body = r.json()
assert body["status"] == "done" and body["retention_expired"] is True, body
assert "document_url" not in body and "document_bundle_url" not in body, body
print("get_status reflects retention_expired, no document URLs OK")

r = client.get(f"/api/documents/{old_done_job_id}/document.md", headers=auth_header(alice_token))
assert r.status_code == 404 and "retention policy" in r.json()["detail"], r.text
print("Downloading a retention-swept document correctly 404s with a clear message OK")

r = client.get(f"/api/documents/{old_done_job_id}/bundle.zip", headers=auth_header(alice_token))
assert r.status_code == 404, r.text
print("Bundle download of a retention-swept document also correctly 404s OK")

# --- Case 2 assertions: untouched (too recent) ---
job = jobs.get_job(fresh_done_job_id)
assert job["deleted_at"] is None
assert (settings.OUTPUT_DIR / fresh_done_job_id).exists()
r = client.get(f"/api/get_status?job_id={fresh_done_job_id}", headers=auth_header(alice_token))
body = r.json()
assert "retention_expired" not in body and body.get("document_url"), body
print("Fresh done job untouched by the sweep OK")

# --- Case 3 assertions: untouched (not done) ---
job = jobs.get_job(old_failed_job_id)
assert job["deleted_at"] is None
print("Old failed job untouched by the sweep (retention only applies to done jobs) OK")

# Running the sweep again is a no-op for the already-cleaned job (idempotent)
retention.main()
job = jobs.get_job(old_done_job_id)
assert job["deleted_at"] is not None
print("Re-running the sweep is idempotent OK")

print("\nALL MILESTONE 7 (retention) CHECKS PASSED")
