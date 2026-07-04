# vid2doc backend (v1)

A minimal API + worker service that wraps the video-to-document pipeline
validated in `../local_test/`. Two containers, one shared codebase:

- **api** — FastAPI app, handles uploads and status/document lookups. Never
  runs the pipeline itself.
- **worker** — polls the shared jobs table and runs the pipeline for each
  queued job. Kept separate from `api` so a long-running video never blocks
  HTTP request handling.

State is intentionally self-contained for v1 — no external database or
object storage to provision:
- **SQLite** (`data/jobs.db`) for job records, shared by both containers via
  a mounted volume. A single atomic `UPDATE ... WHERE status='queued'`
  claims each job, so it's safe to run multiple worker replicas without a
  Postgres-style `SKIP LOCKED`.
- **Local disk** (`data/uploads/`, `data/output/`) for uploaded videos and
  generated documents, also on the shared volume.

This trades durability/scalability for "runs anywhere with just Docker" —
the natural next step (in the original plan) is swapping SQLite for Postgres
and local disk for object storage (R2/S3) once this needs to survive a
VPS being rebuilt or scale past one host.

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

- `200` — `{"job_id", "status", "progress_stage", "document_url"?, "error"?}`
  - `status`: `queued` | `processing` | `done` | `failed`
  - `document_url` present only when `status == "done"`
  - `error` present only when `status == "failed"`
- `404` — unknown job id

### `GET /api/documents/{job_id}/{file_path}`

Serves the generated document and its images (e.g. `document.md`,
`images/xxxxx.jpg`). This is what `document_url` points to.

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
| `ANTHROPIC_API_KEY` | Enables vision judgment + topic segmentation stages; without it, documents are just the raw formatted transcript with no images/headings |
| `TRANSCRIPTION_ENGINE` | `auto` (default) / `assemblyai` / `whisper-diarized` / `whisper` |
| `WHISPER_MODEL` | `tiny`/`base`/`small`/`medium`/`large`, used by the whisper engines |
| `MAX_UPLOAD_BYTES`, `MAX_DURATION_SECONDS` | Upload guardrails (defaults: 2GB, 90 min) |

## Deploying to a VPS

1. Copy this `backend/` directory to the VPS (or clone the repo there).
2. Install Docker + the Compose plugin on the VPS.
3. `cp .env.example .env` and fill in real secrets, including a strong
   `API_KEY` (the default `dev-secret-key` must not be used in production).
4. `docker compose up -d --build`
5. Put a reverse proxy (Caddy/nginx/Traefik) in front of port 8000 for TLS —
   not included here, since it depends on your domain/certs setup.

The `data/` directory (jobs.db + uploads + output) lives on the VPS's local
disk via the compose volume mount — back it up like any other stateful
service if you care about surviving a host rebuild.

## What's not in v1

- No auth beyond the single shared API key — no per-user accounts, no
  request-level rate limiting (the size/duration caps are the only
  cost/abuse guardrail right now).
- No job retry on worker crash mid-processing — a killed worker leaves a
  job stuck in `processing` with no automatic recovery. Fine for a
  single-VPS v1; add a staleness check + requeue before scaling traffic.
- No cleanup of old uploads/output — disk usage grows unbounded. Add a
  retention job before this runs unattended for a long time.
