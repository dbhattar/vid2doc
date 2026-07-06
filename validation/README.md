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
```

Each prints one line per check and ends with `ALL MILESTONE N CHECKS
PASSED`, or raises an `AssertionError` at the first failing check.

## Adding a new milestone script

Import shared setup from `common.py` (`client`, `login_as`, `auth_header`,
`SAMPLE_VIDEO`) rather than duplicating it — see the existing scripts for the
pattern. Test data accumulates in the Postgres DB across runs (users, jobs,
keys); these scripts use distinct fake `google_sub`/email values per
milestone specifically so re-running them doesn't collide with leftover data
from previous runs.
