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

Every endpoint except `/health` requires an `X-API-Key` header. The key is a
single hardcoded shared secret for v1 (`API_KEY` env var) — per-user dynamic
keys are a future iteration once API key management exists.

### `POST /api/convert_to_doc`

Multipart upload, field name `video`.

```bash
curl -X POST http://localhost:8000/api/convert_to_doc \
  -H "X-API-Key: $API_KEY" \
  -F "video=@lecture.mp4"
```

- `202` — `{"job_id": "...", "status": "queued"}`
- `400` — bad/missing file, unsupported extension, unreadable video, or
  duration exceeds `MAX_DURATION_SECONDS`
- `401` — missing/invalid API key
- `413` — file exceeds `MAX_UPLOAD_BYTES`

### `GET /api/get_status?job_id=...`

```bash
curl -H "X-API-Key: $API_KEY" "http://localhost:8000/api/get_status?job_id=$JOB_ID"
```

- `200` — `{"job_id", "status", "progress_stage", "document_url"?, "document_docx_url"?, "document_pdf_url"?, "error"?}`
  - `status`: `queued` | `processing` | `done` | `failed`
  - `document_url` (Markdown) present whenever `status == "done"`; `document_docx_url`/`document_pdf_url` present only if those best-effort exports actually rendered successfully
  - `error` present only when `status == "failed"`
- `404` — unknown job id

### `GET /api/documents/{job_id}/{file_path}`

Serves the generated document in any of its rendered forms (`document.md`,
`document.docx`, `document.pdf`) plus `images/xxxxx.jpg`. This is what the
`document_*_url` fields above point to.

### `GET /health`

No auth. Liveness check for whatever platform runs the container.

## Local development

```bash
cd backend
cp .env.example .env    # fill in API keys as you get them
docker compose up --build
```

`.env` variables:

| Variable | Purpose |
|---|---|
| `API_KEY` | Shared secret required on every request (default `dev-secret-key` — change before exposing this publicly) |
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

To apply schema changes without restarting a container: `docker compose run --rm api alembic upgrade head` (this also runs automatically on every container boot).

## Deploying to a VPS

1. Copy this `backend/` directory to the VPS (or clone the repo there).
2. Install Docker + the Compose plugin on the VPS.
3. `cp .env.example .env` and fill in real secrets, including a strong
   `API_KEY` (the default `dev-secret-key` must not be used in production).
4. `docker compose up -d --build`
5. Put a reverse proxy (Caddy/nginx/Traefik) in front of port 8000 for TLS —
   not included here, since it depends on your domain/certs setup.

The `data/` directory (Postgres's own data dir + uploads + output) lives on
the VPS's local disk via the compose volume mounts — back it up like any
other stateful service if you care about surviving a host rebuild.

## What's not in v1

- No auth beyond the single shared API key — no per-user accounts, no
  request-level rate limiting (the size/duration caps are the only
  cost/abuse guardrail right now).
- No job retry on worker crash mid-processing — a killed worker leaves a
  job stuck in `processing` with no automatic recovery. Fine for a
  single-VPS v1; add a staleness check + requeue before scaling traffic.
- No cleanup of old uploads/output — disk usage grows unbounded. Add a
  retention job before this runs unattended for a long time.
