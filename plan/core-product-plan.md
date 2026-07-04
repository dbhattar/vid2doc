# vid2doc — Core Product Implementation Plan

> Once approved, save a copy of this plan to `plan/` in the `vid2doc` repo (e.g. `plan/core-product-plan.md`) as the first implementation step, so it's version-controlled alongside the code it describes.

## Context

The landing page and waitlist are live. This plan covers building the actual product: upload a video, get back a searchable, formatted document with diarized transcript, topic headings, and relevant frame images inserted at the right places. The repo currently contains only the static marketing site (`index.html`, `styles.css`, `script.js`, `thanks.html`, `netlify.toml`) — this is a greenfield backend + pipeline build, added alongside it as a new `backend/` directory (the marketing site is untouched).

Goal for this phase: the fastest path to a working, demoable end-to-end MVP — anonymous upload (no auth), minimal moving infra pieces, biased toward validating the product over building for scale.

## Locked-in architecture decisions

| Concern | Choice | Why |
|---|---|---|
| Backend | Python + FastAPI, one codebase, two processes (API + worker) | The pipeline (ffmpeg, OCR, scene-detection, vision/LLM calls) is Python-native end to end; avoids cross-language glue |
| Async jobs | Postgres-backed `jobs` table, worker polls with `SELECT ... FOR UPDATE SKIP LOCKED` | No Redis/Celery needed at MVP traffic; horizontally scales later with zero code change |
| Transcription + diarization | AssemblyAI (single API call, speaker labels + timestamps) | Better out-of-box diarization and a polling API that maps directly onto our own job-polling model |
| Object storage | Cloudflare R2 (uploaded video, extracted frames, doc images) | S3-compatible, zero egress fees — matters since generated docs get viewed repeatedly |
| Database | Neon Postgres | Instant hosted provisioning, real concurrent-writer support (API + worker) |
| Deployment | Railway (API service + worker service, same repo/Dockerfile, different start commands) | Fastest "push and get a URL" for a two-process Python app |
| Frontend | Separate minimal Vite + React app (own repo path, not bolted onto the static marketing site) | Marketing site is intentionally build-tool-free; product UI needs upload/poll/view state that's cleaner as its own small app |
| Auth | None for MVP — anonymous upload, shareable doc link | Explicitly deferred; add later once the pipeline is validated |
| Vision judgment model | Claude Sonnet 5 (Haiku 4.5 fallback for OCR-heavy/text-only frames) via Message Batches API | Judgment quality where it matters (diagrams/photos), cost-bounded via batching + prompt caching |
| Topic segmentation model | Claude Sonnet 5, plain text, sliding windows | Handles arbitrarily long transcripts at constant per-minute cost |
| Output format | Markdown + `images/` folder (relative paths, not base64) | Lightweight, diffable, easy to render or convert later |

## Repo structure

```
backend/
  app/
    main.py                    # FastAPI app
    api/
      routes_uploads.py        # POST /api/uploads (presigned R2 URL + job row)
      routes_jobs.py           # GET /api/jobs/{id} (status/progress)
      routes_documents.py      # GET /api/documents/{id}
    worker/
      worker_entrypoint.py     # polls jobs table, runs pipeline.py per job
      pipeline.py              # orchestrates stages in order/parallel per below
      stages/
        transcribe.py          # AssemblyAI call -> List[TranscriptSegment]
        extract_frames.py      # ffmpeg adaptive-interval extraction
        filter_frames.py       # phash dedup + OCR/edge/SSIM gating
        vision_judge.py        # Claude Sonnet 5 batched vision judgment
        topic_segmentation.py  # Claude sliding-window heading extraction
        assemble.py            # deterministic merge -> Markdown + images/
    models.py                  # SQLAlchemy: Job, Document, Frame
    db.py
    storage.py                 # R2 (boto3) client wrapper, presigned URLs
    config.py                  # pydantic-settings (API keys, bucket, DB URL)
  Dockerfile
  requirements.txt

frontend/                      # separate Vite + React app
  src/
    UploadForm.tsx
    JobStatus.tsx
    DocumentViewer.tsx
```

## Data model

```sql
CREATE TABLE jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  status TEXT NOT NULL DEFAULT 'queued',   -- queued|processing|done|failed
  progress_stage TEXT,                     -- transcribing|extracting_frames|judging_frames|segmenting|assembling
  source_video_url TEXT NOT NULL,
  video_duration_seconds INT,
  error_message TEXT,
  updated_at TIMESTAMPTZ DEFAULT now(),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID REFERENCES jobs(id),
  title TEXT,
  content_markdown TEXT NOT NULL,
  transcript_raw JSONB,          -- full diarized transcript, kept for future search
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE frames (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID REFERENCES jobs(id),
  timestamp_seconds FLOAT NOT NULL,
  storage_url TEXT NOT NULL,
  is_relevant BOOLEAN,
  caption TEXT,
  content_type TEXT              -- slide|diagram|whiteboard|code|photo|chart|other
);
```

## Pipeline stages (the core of the product)

Runs in the worker process, one job at a time per worker slot. `transcribe_diarize` and `extract_frames`/`filter_candidate_frames` run in parallel (independent inputs); `judge_frames_with_vision_llm` and `segment_transcript_into_sections` run in parallel once their inputs are ready; both must finish before `assemble_document`.

1. **`extract_audio`** — ffmpeg, mono 16kHz wav.
2. **`transcribe_diarize`** — AssemblyAI call, returns speaker-labeled, timestamped segments.
3. **`extract_frames`** — ffmpeg `fps=0.5` (1 frame/2s) as the base rate; drop to 1 frame/10s during detected "talking head only" stretches (flat edge-density over 30s windows) to avoid wasting frames on static webcam shots. Brief slides are still caught because scene-change detection (next stage) is interval-independent, not because of the sampling rate itself.
4. **`filter_candidate_frames`** — cheap, no API calls, two gates:
   - *Dedup*: perceptual hash (`imagehash.phash`), drop frame if Hamming distance from last **kept** frame < 5.
   - *Content gate* (OR of three signals): OCR text-density (`pytesseract`, >40 confident chars), edge-density (Canny, ratio > 0.08 — catches diagrams/photos with no text), layout-change (SSIM < 0.85 vs last accepted frame — catches progressive whiteboard fills). A 2-hour video should shrink from ~3,600 raw frames to roughly 150–400 candidates.
5. **`judge_frames_with_vision_llm`** — batch 6–8 candidate frames per Claude call (images downscaled to ≤1568px long edge) plus ±30s of surrounding transcript text, requesting structured JSON output per frame: `include`, `confidence`, `caption`, `content_type`, `placement_anchor` (a transcript quote used later for disambiguation). Use the **Message Batches API** (not latency-sensitive, 50% cost cut) and a `cache_control`-marked system prompt (stable rubric, reused across every batch). Sonnet 5 by default; Haiku 4.5 acceptable for OCR-gated (text-heavy) frames specifically if cost needs trimming later.
6. **`match_frame_timestamps`** — pure logic, no API calls. Anchor each accepted frame to the transcript segment containing its timestamp; if mid-segment, anchor to segment end rather than mid-sentence; snap to a nearby boundary within a 3s grace window; use the vision LLM's `placement_anchor` text as a tie-breaker when it fuzzy-matches a different segment (corrects timestamp drift).
7. **`segment_transcript_into_sections`** — sliding windows of ~3,000–4,000 words with ~500-word overlap, one Claude call per window (plain text) requesting `{start_timestamp, heading, one_line_summary}` boundaries; dedupe boundaries within 60s across overlapping windows. Cost stays flat per-minute-of-audio regardless of total video length.
8. **`assemble_document`** — deterministic merge, no API calls: group transcript segments and accepted frames under each section, render `## {heading}` + summary + `**{speaker}** ({timestamp}): {text}` lines, inserting each frame's `![caption](images/{frame_id}.jpg)` immediately after its anchor segment. Copy accepted frame images into an `images/` folder next to the output `.md`.

## Frontend (MVP)

Three states in one page: upload form → job status (polls `GET /api/jobs/{id}` every few seconds) → document viewer (renders the returned Markdown + images, shareable via `/d/{document_id}` URL). Browser uploads directly to R2 via a presigned URL obtained from `POST /api/uploads` (avoids proxying large video files through the API). Deployed to Netlify/Vercel as its own site, calling the Railway backend — requires explicit CORS origin allowlisting on FastAPI (not `*`).

## Phased build order

0. **Provisioning** — before any code: create/collect accounts and credentials for the services this plan depends on, since not all are set up yet:
   - **Anthropic API key** (vision judgment + topic segmentation calls)
   - **AssemblyAI API key** (transcription + diarization)
   - **Cloudflare R2** — create a bucket, generate S3-compatible API tokens (access key/secret/endpoint)
   - **Neon** — create a Postgres project, grab the connection string
   - **Railway** — create a project, connect the GitHub repo, prepare to add the two services (API + worker) once the Dockerfile exists

   Store these as environment variables (`.env` locally, Railway service variables in deployment) referenced by `backend/app/config.py` — never commit real keys to the repo.
1. **Upload + transcription only** — presigned upload to R2, worker runs `extract_audio` + `transcribe_diarize`, job returns raw transcript JSON. Validates the async job plumbing and storage.
2. **Diarized transcript as a plain document** — render `Speaker A: ...` formatted output as the "document." Validates diarization quality is usable.
3. **Frame extraction + heuristic filtering, no LLM** — stages 3–4 only; log candidate count reduction. Validates the frame pipeline math.
4. **Vision judgment on candidates** — stage 5 wired in; verify cost per video stays in the expected ~$0.30–0.50/2hr range.
5. **Topic segmentation** — stage 7 wired in; validates the actual "structured document" value proposition.
6. **Full assembly** — stage 6 + 8; images inserted into the finished Markdown document.
7. **Frontend polish** — document viewer, shareable link, upload size/length caps surfaced in the UI, error states.

Each milestone is independently demoable end to end.

## Guardrails (from day one, not retrofitted)

- Enforce a hard video length cap (e.g. 90 min) and file size cap (e.g. 2GB) in both the upload form and the API — bounds hosted-API cost and worker processing time given there's no auth to rate-limit by account.
- Basic IP-based rate limiting on `POST /api/uploads` — the only real defense against runaway hosted-API bills with anonymous upload.
- Worker heartbeat: update `jobs.updated_at` periodically during processing; a cron-ish check requeues jobs stuck in `processing` past a staleness threshold (crashed worker otherwise leaves a job stuck forever with no user-visible error).
- Dockerfile must explicitly `apt-get install ffmpeg` and `tesseract-ocr` — not present in slim Python base images.
- Presigned browser-to-R2 upload from Milestone 1 — retrofitting this after a proxy-upload path would be wasted work.

## Verification

- Milestone 1: upload a short (~2 min) test video, confirm a `jobs` row transitions `queued → processing → done` and the raw AssemblyAI transcript JSON is retrievable via `GET /api/jobs/{id}`.
- Milestone 3: log raw frame count vs. surviving candidate count on a test video with both slide content and talking-head stretches; confirm candidate count is in the expected 5–15% range of raw frames.
- Milestone 4: manually review vision-judge output on a handful of known frames (a real slide, a duplicate/near-duplicate, a blank transition) to confirm `include`/`caption` quality before trusting it at scale.
- Milestone 6: open the final generated `.md` file in a Markdown viewer and confirm images appear in sensible positions relative to the surrounding transcript text.
- End to end: run a real ~20–30 min test video (mixed talking-head + slides) through the full pipeline via the frontend, from upload to viewing the finished document, and sanity-check total processing time and Claude API cost against the estimates above.
