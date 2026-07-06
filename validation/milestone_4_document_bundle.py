"""Verifies the document bundle (zip) download endpoint added to Milestone 4.

Constructs a "done" job directly (writing fake document.md + images/ to disk)
rather than running the full real pipeline -- this endpoint's job is
zipping/serving files correctly and enforcing ownership, not re-testing
transcription. Run from the repo root:

    python validation/milestone_4_document_bundle.py
"""

import io
import uuid
import zipfile

from common import auth_header, client, login_as, reset_test_user

from app import jobs
from app.config import settings

reset_test_user("alice-m4b@example.com")
reset_test_user("bob-m4b@example.com")

alice = login_as("google-sub-alice-m4b", "alice-m4b@example.com", "Alice")
bob = login_as("google-sub-bob-m4b", "bob-m4b@example.com", "Bob")
alice_token = alice["access_token"]
bob_token = bob["access_token"]

# Unique per run (rather than a fixed id) so re-running never collides with
# the job row this script created last time -- reset_test_user only clears
# rows by user email, not by job id.
job_id = f"validation-bundle-{uuid.uuid4()}"
doc_dir = settings.OUTPUT_DIR / job_id / "document"
images_dir = doc_dir / "images"
images_dir.mkdir(parents=True, exist_ok=True)
(doc_dir / "document.md").write_text("# Test Document\n\n![a slide](images/slide1.jpg)\n")
(images_dir / "slide1.jpg").write_bytes(b"fake-jpeg-bytes")

jobs.create_job(job_id, "/tmp/fake-source.mp4", user_id=alice["user"]["id"])
jobs.update_job(job_id, status="done", progress_stage="done", document_path=str(doc_dir / "document.md"))

# get_status advertises the bundle URL once done
r = client.get(f"/api/get_status?job_id={job_id}", headers=auth_header(alice_token))
assert r.status_code == 200, r.text
assert r.json()["document_bundle_url"].endswith(f"/api/documents/{job_id}/bundle.zip"), r.json()
print("document_bundle_url advertised once done OK")

# Download the bundle and verify its contents
r = client.get(f"/api/documents/{job_id}/bundle.zip", headers=auth_header(alice_token))
assert r.status_code == 200, r.text
assert r.headers["content-type"] == "application/zip", r.headers
zf = zipfile.ZipFile(io.BytesIO(r.content))
names = set(zf.namelist())
assert names == {"document.md", "images/slide1.jpg"}, names
assert zf.read("document.md").decode() == (doc_dir / "document.md").read_text()
assert zf.read("images/slide1.jpg") == b"fake-jpeg-bytes"
print("Bundle zip contains document.md + images/ with correct contents OK")

# Ownership: Bob cannot download Alice's bundle
r = client.get(f"/api/documents/{job_id}/bundle.zip", headers=auth_header(bob_token))
assert r.status_code == 404, r.text
print("Bob correctly gets 404 on Alice's bundle OK")

# No credentials -> 401
r = client.get(f"/api/documents/{job_id}/bundle.zip")
assert r.status_code == 401, r.text
print("No-credentials 401 OK")

# The plain single-file download route still works unaffected (route
# ordering: bundle.zip is not swallowed by, and does not swallow, the
# {file_path:path} catch-all)
r = client.get(f"/api/documents/{job_id}/document.md", headers=auth_header(alice_token))
assert r.status_code == 200 and r.text == (doc_dir / "document.md").read_text(), r.text
print("Plain single-file document.md download still works OK")

print("\nALL MILESTONE 4 (document bundle) CHECKS PASSED")
