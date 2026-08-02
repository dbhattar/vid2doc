#!/usr/bin/env python3
"""Smoke tests for the anonymous trial upload flow (app/routes/trial.py) --
run inside the backend container, since the DB-level checks import app.*
directly and talk to the real database:

    docker compose exec api python3 tests/test_trial_flow.py

Captures the manual verification run during implementation: Turnstile
gating, ownership isolation on the tokenless status route (a real
authenticated user's job must never be reachable through it), the per-IP
daily counter, and the trial retention hard-delete pass.

Does NOT exercise a real successful trial upload end-to-end -- that needs a
real Cloudflare Turnstile secret + a token minted by solving a real
challenge, which this dev environment doesn't have. See
backend/scripts/test_e2e.py for the authenticated upload's equivalent.
"""

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# Running as a script (rather than `python -m`) puts this file's own
# directory on sys.path, not the repo root -- add it explicitly so `from
# app import ...` resolves regardless of how/from-where this gets invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API_URL = "http://localhost:8000"


def check(label: str, condition: bool) -> bool:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    return condition


def test_turnstile_gating() -> bool:
    ok = True

    r = requests.post(f"{API_URL}/api/trial/convert_to_doc")
    ok &= check("missing video/turnstile_token -> 422", r.status_code == 422)

    r = requests.post(
        f"{API_URL}/api/trial/convert_to_doc",
        files={"video": ("fake.mp4", b"\x00" * 1000)},
        data={"turnstile_token": "bogus"},
    )
    ok &= check("invalid turnstile token -> 403", r.status_code == 403)

    return ok


def _first_real_job_id() -> str | None:
    from app.db import get_session
    from app.models import Job

    session = get_session()
    try:
        row = session.query(Job.id).filter(Job.user_id.isnot(None)).first()
        return row.id if row else None
    finally:
        session.close()


def test_tokenless_status_isolation() -> bool:
    ok = True

    r = requests.get(f"{API_URL}/api/trial/status/{uuid.uuid4()}")
    ok &= check("nonexistent job id -> 404", r.status_code == 404)

    real_job_id = _first_real_job_id()
    if real_job_id is None:
        print("[SKIP] no authenticated job in DB to test cross-ownership isolation")
    else:
        r = requests.get(f"{API_URL}/api/trial/status/{real_job_id}")
        ok &= check("real authenticated job id -> 404 via tokenless trial route", r.status_code == 404)

    return ok


def test_per_ip_counter_and_retention_cleanup() -> bool:
    from app import jobs
    from app.config import settings
    from app.db import get_session
    from app.models import Job

    ok = True
    ip = f"203.0.113.{uuid.uuid4().int % 250}"
    job_ids = []
    for _ in range(2):
        job_id = str(uuid.uuid4())
        jobs.create_job(
            job_id,
            f"/data/uploads/{job_id}/source.mp4",
            user_id=None,
            duration_seconds=120,
            size_bytes=1000,
            billed_cents=0,
            title="smoke-test-trial-job",
            job_type="video",
            client_ip=ip,
        )
        job_ids.append(job_id)

    since = datetime.now(timezone.utc) - timedelta(days=1)
    count = jobs.count_trial_jobs_from_ip_since(ip, since)
    ok &= check("count_trial_jobs_from_ip_since counts both new jobs", count == 2)

    # Backdate past the retention window and confirm the cleanup query picks
    # them up, then actually purge them via the same hard-delete retention.py
    # uses, so this test doesn't leave junk rows behind either way.
    session = get_session()
    try:
        session.query(Job).filter(Job.id.in_(job_ids)).update(
            {Job.created_at: datetime.now(timezone.utc) - timedelta(hours=settings.TRIAL_RETENTION_HOURS + 1)},
            synchronize_session=False,
        )
        session.commit()
    finally:
        session.close()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.TRIAL_RETENTION_HOURS)
    eligible_ids = {j["id"] for j in jobs.list_trial_jobs_eligible_for_cleanup(cutoff)}
    ok &= check("backdated trial jobs picked up for cleanup", set(job_ids) <= eligible_ids)

    for job_id in job_ids:
        jobs.delete_job(job_id)
    ok &= check("jobs hard-deleted", all(jobs.get_job(j) is None for j in job_ids))

    return ok


def main() -> None:
    results = [
        test_turnstile_gating(),
        test_tokenless_status_isolation(),
        test_per_ip_counter_and_retention_cleanup(),
    ]
    if not all(results):
        sys.exit(1)
    print("\nAll trial-flow smoke tests passed.")


if __name__ == "__main__":
    main()
