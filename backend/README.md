# vid2doc backend (v1)

A minimal API + worker service that wraps the video-to-document pipeline
validated in `../local_test/`. Two containers, one shared codebase:

- **api** — FastAPI app, handles uploads and status/document lookups. Never
  runs the pipeline itself.
- **worker** — polls the shared jobs table and runs the pipeline for each
  queued job. Kept separate from `api` so a long-running video never blocks
  HTTP request handling.

State is still self-contained on a single VPS — no third-party database or
object storage provider to provision:
- **Postgres**, self-hosted as a third `postgres` service in
  `docker-compose.yml` (own volume, not exposed beyond `127.0.0.1` on the
  host). Schema is managed by Alembic (`alembic/`); both the `api` and
  `worker` containers run `alembic upgrade head` on boot via
  `docker-entrypoint.sh` before starting, so the schema is always current
  without a separate deploy step. `claim_next_queued_job()` uses
  `SELECT ... FOR UPDATE SKIP LOCKED`, so multiple worker replicas can safely
  claim jobs without racing each other.
- **Local disk** (`data/uploads/`, `data/output/`) for uploaded videos and
  generated documents, on the shared volume.

This still trades object-storage durability/scalability for "runs anywhere
with just Docker" — swapping local disk for R2/S3 remains a possible future
step if this needs to survive a VPS being rebuilt or scale past one host.

## Pipeline

1. **Transcribe** (`stages/transcribe.py`) — AssemblyAI, or local Whisper (+
   pyannote for diarization) as a no-API-key fallback. Consecutive same-speaker
   fragments are merged into readable paragraphs regardless of engine.
2. **Extract + filter frames** (`stages/frames.py`) — ffmpeg sampling, then
   perceptual-hash dedup + OCR/edge/SSIM heuristics narrow raw frames down to
   a small LLM-worthy candidate set, no API calls.
3. **Classify frames** (`stages/classify.py`) — a vision LLM (Claude or
   OpenAI, batched) labels each candidate as a slide/diagram/whiteboard/
   code/photo/chart/table (dropping filler frames like a talking-head shot),
   extracting real structured data for anything classified as a table.
4. **Compose** (`stages/compose.py`) — a text LLM writes the actual document:
   given a transcript slice and the images/tables available in that time
   range, it produces organized sections of real prose (not a mechanical
   transcript stitch) with images/tables placed wherever they topically fit.
   Runs over non-overlapping ~3500-word windows so cost/quality stays
   constant regardless of video length.
5. **Render** (`stages/assemble.py`) — deterministic, no LLM calls: draws the
   composed sections into Markdown (canonical), DOCX (`python-docx`), and PDF
   (`reportlab`) — pure-Python rendering, no external binaries or native
   libraries needed in the image.

## API

Every endpoint except `/health` and `/api/auth/google` requires
`Authorization: Bearer <token>`, where the token is issued by
`/api/auth/google` after verifying a Google Sign-In ID token — there is no
shared/static API key anymore. (Per-user long-lived API keys, for
programmatic/non-browser callers, are a separate upcoming mechanism alongside
this, not a replacement for it.)

### `POST /api/auth/google`

Exchanges a Google Identity Services ID token (obtained client-side, e.g. by
the frontend's "Sign in with Google" button) for an app session token.
Creates the user on first login.

```bash
curl -X POST http://localhost:8000/api/auth/google \
  -H "Content-Type: application/json" \
  -d '{"id_token": "<google-issued ID token>"}'
```

- `200` — `{"access_token": "...", "user": {"id", "email", "display_name", "avatar_url", ...}}`
- `401` — invalid/unverifiable Google ID token (wrong audience, expired, bad signature)

### `GET /api/auth/me`

Returns the caller's own user record. Mainly useful to confirm a token is
valid and to build an authenticated shell page.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/auth/me
```

### `POST /api/convert_to_doc`

Multipart upload, field name `video`. Jobs are scoped to the caller.

```bash
curl -X POST http://localhost:8000/api/convert_to_doc \
  -H "Authorization: Bearer $TOKEN" \
  -F "video=@lecture.mp4"
```

- `202` — `{"job_id": "...", "status": "queued"}`
- `400` — bad/missing file, unsupported extension, unreadable video, or
  duration exceeds `MAX_DURATION_SECONDS`
- `401` — missing/invalid/expired token
- `402` — insufficient wallet balance to cover this video's cost (see
  Billing below) — no free tier exists
- `413` — file exceeds `MAX_UPLOAD_BYTES`

### `GET /api/get_status?job_id=...`

```bash
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/get_status?job_id=$JOB_ID"
```

- `200` — `{"job_id", "status", "progress_stage", "created_at", "duration_seconds", "document_url"?, "document_bundle_url"?, "document_docx_url"?, "document_pdf_url"?, "retention_expired"?, "error"?}`
  - `status`: `queued` | `processing` | `done` | `failed`
  - `document_url` (Markdown) / `document_bundle_url` (zip of the Markdown + its `images/`) present whenever `status == "done"` and the document hasn't been swept by retention; `document_docx_url`/`document_pdf_url` present only if those best-effort exports actually rendered successfully
  - `retention_expired: true` instead of any `document_*_url` if the job succeeded but its files were deleted by the retention sweep (see Retention below)
  - `error` present only when `status == "failed"`
- `404` — unknown job id, or a job id that belongs to a different user (ownership is never revealed)

### `GET /api/jobs?limit=&offset=`

Paginated list of the caller's own jobs, newest first. `{"jobs": [...], "total": N}`, each item shaped exactly like a `get_status` response.

```bash
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/jobs?limit=20&offset=0"
```

### `GET /api/documents/{job_id}/{file_path}`

Serves the generated document in any of its rendered forms (`document.md`,
`document.docx`, `document.pdf`) plus `images/xxxxx.jpg`. This is what the
`document_*_url` fields above point to. Same ownership scoping as `get_status`.

### `GET /api/documents/{job_id}/bundle.zip`

Zips `document.md` together with its `images/` folder on the fly (Markdown
alone references images by relative path, so it's not self-contained without
them — DOCX/PDF don't have this problem since they embed images directly).
This is what `document_bundle_url` points to.

## Billing

Pure pay-as-you-go — **$1.00 per video-hour**, charged proportionally to the
exact video length (36 seconds = 1 cent), deducted from a prepaid wallet up
front at upload time. No plans, no tiers, no subscriptions. See
`app/billing.py`/`app/routes/billing.py`.

The wallet balance is never a stored/mutable number — it's always
`SUM(amount_cents)` over the append-only `wallet_ledger` table (`topup` /
`usage_charge` / `usage_refund` entries), so it can't drift and every
charge/refund has an audit trail. A failed job is refunded automatically
(see `pipeline.py`'s except block). Documents aren't guaranteed to be
retained past 7 days for anyone — see Retention below.

### `POST /api/billing/checkout/topup`

```bash
curl -X POST http://localhost:8000/api/billing/checkout/topup \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"amount_cents": 2000}'
```

- `200` — `{"url": "https://checkout.stripe.com/..."}` — redirect the browser here
- `amount_cents` must be between 500 ($5) and 100000 ($1000)

### `GET /api/billing/wallet`

- `200` — `{"balance_cents": N}`

### `POST /api/billing/webhook`

Stripe calls this directly (signature-verified via `STRIPE_WEBHOOK_SECRET`,
not `Authorization`). Handles `checkout.session.completed` (mode=payment)
by crediting the wallet. Idempotent — replayed/retried events are detected
via `processed_webhook_events` and skipped. For local dev:
`stripe listen --forward-to localhost:8000/api/billing/webhook`.

### `GET /health`

No auth. Liveness check for whatever platform runs the container.

## Retention

`retention.py` is a one-shot script, not part of the API or worker process:
for every `done` job older than 7 days with `deleted_at IS NULL`, it deletes
that job's `data/uploads/{job_id}` and `data/output/{job_id}` directories
from disk, then nulls `document_path` and sets `deleted_at` on the row (the
row itself — id, `duration_seconds`, `user_id`, `billed_cents`, timestamps —
is kept, since usage/billing history still needs it). Applies to every job
regardless of who owns it; there's no plan tier with unlimited retention.

Run it on a schedule via the VPS's own crontab — not folded into `worker.py`'s
poll loop, since that loop synchronously blocks on a video's full processing
time and shouldn't also carry cleanup latency:

```cron
0 3 * * * cd /path/to/vid2doc/backend && docker compose run --rm api python retention.py >> /var/log/framewrite-retention.log 2>&1
```

## Local development

```bash
cd backend
cp .env.example .env    # fill in API keys as you get them
docker compose up --build
```

`.env` variables:

| Variable | Purpose |
|---|---|
| `GOOGLE_CLIENT_ID` | Google OAuth Web Client ID, used to verify ID tokens on `/api/auth/google`. Also needed by the frontend as `NEXT_PUBLIC_GOOGLE_CLIENT_ID` |
| `JWT_SECRET` | Signs the app session token returned by `/api/auth/google` (default is dev-only — generate a real one for prod, e.g. `openssl rand -hex 32`) |
| `CORS_ALLOWED_ORIGINS` | Comma-separated browser origins allowed to call this API (default `http://localhost:3000`) — add the production frontend origin here once deployed |
| `ASSEMBLYAI_API_KEY` | Real hosted diarization |
| `HF_TOKEN` | Local diarization fallback (Whisper + pyannote) if no AssemblyAI key |
| `ANTHROPIC_API_KEY` | Frame classification + document composition via Claude (used when `LLM_PROVIDER=anthropic`, the default) |
| `OPENAI_API_KEY` | Frame classification + document composition via OpenAI (used when `LLM_PROVIDER=openai`) |
| `LLM_PROVIDER` | `anthropic` (default) or `openai`. Both stages are skipped entirely if the selected provider's key isn't set -- the document then falls back to the raw merged transcript under one heading, no images/topic organization |
| `OPENAI_MODEL` | Default `gpt-5.4-mini` (vision + structured outputs, cost-efficient). Only used when `LLM_PROVIDER=openai` |
| `TRANSCRIPTION_ENGINE` | `auto` (default) / `assemblyai` / `whisper-diarized` / `whisper` |
| `WHISPER_MODEL` | `tiny`/`base`/`small`/`medium`/`large`, used by the whisper engines |
| `MAX_UPLOAD_BYTES`, `MAX_DURATION_SECONDS` | Upload guardrails (defaults: 2GB, 90 min) |
| `POSTGRES_PASSWORD` | Password for the self-hosted `postgres` compose service |
| `DATABASE_URL` | SQLAlchemy connection string for `api`/`worker`, e.g. `postgresql+psycopg2://vid2doc:$POSTGRES_PASSWORD@postgres:5432/vid2doc` — host must match the `postgres` service name when running under compose |
| `STRIPE_SECRET_KEY` | Stripe API secret key (test-mode for dev) — no Price ids needed, top-up amount is chosen at checkout time |
| `STRIPE_WEBHOOK_SECRET` | Verifies `POST /api/billing/webhook` signatures — from `stripe listen` locally, or the dashboard's webhook config in prod |
| `FRONTEND_URL` | Where Stripe Checkout redirects back to after a session |

To apply schema changes without restarting a container: `docker compose run --rm api alembic upgrade head` (this also runs automatically on every container boot).

## Deploying to a VPS

1. Copy this `backend/` directory to the VPS (or clone the repo there).
2. Install Docker + the Compose plugin on the VPS.
3. `cp .env.example .env` and fill in real secrets, including a real
   `JWT_SECRET` (the default dev value must not be used in production) and
   your production `GOOGLE_CLIENT_ID`.
4. `docker compose up -d --build`
5. Put a reverse proxy (Caddy/nginx/Traefik) in front of port 8000 for TLS —
   not included here, since it depends on your domain/certs setup.

The `data/` directory (Postgres's own data dir + uploads + output) lives on
the VPS's local disk via the compose volume mounts — back it up like any
other stateful service if you care about surviving a host rebuild.

## What's not in v1

- No request-level rate limiting beyond the size/duration upload caps — the
  wallet balance check is the only real cost/abuse guardrail right now.
- No job retry on worker crash mid-processing — a killed worker leaves a
  job stuck in `processing` with no automatic recovery. Fine for a
  single-VPS v1; add a staleness check + requeue before scaling traffic.
