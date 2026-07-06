# Milestone validation scripts

One script per milestone from `plan/` (see the plan doc's phased build
order), each a linear, readable script that exercises real HTTP flows
through the actual FastAPI app (in-process via `TestClient` — no server to
start) against a real Postgres database. Not pytest tests: no fixtures/
parametrization, just `assert` and `print` in a straight line, meant to be
read top to bottom as a record of what was checked and why.

The only thing mocked is the network call to Google's token-verification
endpoint (`google.oauth2.id_token.verify_oauth2_token`) — everything else,
including our own Google-verification code, JWT issuance, database writes,
and real video uploads through the real pipeline entrypoint, runs for real.

## Prerequisites

1. Postgres running and migrated:
   ```bash
   cd backend
   docker compose up -d postgres
   DATABASE_URL="postgresql+psycopg2://vid2doc:dev-postgres-password@localhost:55432/vid2doc" \
     alembic upgrade head   # or: pip install -r ../validation/requirements.txt first
   ```
   **If the `worker` container is also running** (e.g. you left the full stack up with
   `docker compose up -d`), it shares this same Postgres database and *will* pick up and
   really process any video these scripts upload — real transcription, real LLM API calls,
   real cost/time. Run `docker compose stop worker` first if you only want to check the API
   contracts (job creation, listing, ownership) and don't need full pipeline execution.
2. A small local `.mp4` for upload-flow scripts. `local_test/apchem.mp4` (gitignored, not checked in) works if you already have it locally; otherwise set `VALIDATION_SAMPLE_VIDEO=/path/to/any.mp4`.
3. Dependencies:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r validation/requirements.txt
   ```

## Running

From the repo root, with the venv active:

```bash
python validation/milestone_2_auth.py
python validation/milestone_3_api_keys.py
python validation/milestone_4_jobs_list.py
python validation/milestone_4_document_bundle.py
python validation/milestone_4_jobs_list.py
```

Each prints one line per check and ends with `ALL MILESTONE N CHECKS
PASSED`, or raises an `AssertionError` at the first failing check.

## Adding a new milestone script

Import shared setup from `common.py` (`client`, `login_as`, `reset_test_user`,
`auth_header`, `SAMPLE_VIDEO`) rather than duplicating it — see the existing
scripts for the pattern. At the top of your script, call `reset_test_user`
for every fake email your script logs in as, *then* call `login_as` for
each — this deletes any leftover user/jobs/keys from a previous run first,
so the script produces identical results every time it's re-run instead of
accumulating state. (`login_as` itself never resets — some scripts
deliberately log in as the same identity twice in a row to test re-login
idempotency, which an automatic reset would silently defeat.)

If your script's assertions depend on a job's live `status`/`progress_stage`,
remember a real worker (if running, see Prerequisites) can advance those
fields between two of your requests — that's correct behavior, not a bug, so
avoid asserting exact equality across two separate reads of an in-flight
job; compare structure/stable fields instead (see
`milestone_4_jobs_list.py`'s shape check for the pattern).
