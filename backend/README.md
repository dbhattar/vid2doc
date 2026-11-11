# Framewrite backend (v1)

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

## AI agents (proof of concept)

Users can assemble an agent from a knowledge base (finished documents,
snapshotted into the DB on attach so they outlive the 7-day retention),
tools and skills picked from the in-code catalog (`app/agent_catalog.py`),
and memory (a rolling summary written when a new conversation starts).
`app/agents.py` runs an OpenAI Responses API tool loop (`AGENT_OPENAI_MODEL`);
routes are in `routes/agents.py`. Free for now (rate limit + turn cap only).
Verify with `validation/milestone_agents.py`.

### Adding an agent tool

Tools are auto-discovered: drop a module into `app/agent_tools/` that defines
a module-level `TOOL` dict -- no route, migration or frontend change (the
picker renders from `GET /api/agents/catalog`). The file name is the tool id
stored on agents, so never rename a shipped one; `_`-prefixed modules are
helpers. Shape:

```python
TOOL = {
    "order": 70,                      # catalog sort order (optional)
    "name": "Shown in the picker",
    "description": "One line for the picker.",
    "available": lambda user: None,   # optional; return a reason string if this
                                      # user can't use it right now (e.g. not connected)
    "functions": [{                   # OpenAI function tool(s), plus the callable
        "type": "function", "name": "my_tool", "description": "...",
        "parameters": {...}, "strict": True,
        "run": run,                   # run(ctx, args) -> str for the model
    }],                               # (or "builtin": {...} for an OpenAI-hosted tool)
}
```

`ctx` is `{"documents", "client", "user"}`. Return plain-string messages for
expected failures (not connected, not configured) so the model can relay
them; exceptions become a generic "tool failed". Re-check `available` inside
`run` (state can change after an agent is created), wrap anything from outside
Framewrite with `_common.wrap_untrusted`, and rate-limit side-effecting tools
with `_common.rate_limited`. Results are capped at `MAX_TOOL_RESULT_CHARS`.
Add a chip label in `frontend/components/AgentChat.tsx`'s `TOOL_LABELS`.

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

### `GET` / `PATCH /api/me/preferences`

The caller's own settings, edited on the app's Settings page. Fields:
`notify_job_done` (email when a document is ready), `notify_topic_alerts`
(email when a public agency meeting covers a topic the user follows),
`notify_review_reminder`
(the one-day review reminder), `notify_meeting_notes` (default for the
per-meeting "email me when the notes are ready" box), `product_announcements`
(inverse of `users.announcements_opt_out`) and `default_bot_name` (the meeting
notetaker's default name; blank clears it). `PATCH` takes any subset. Only the
"ready" and reminder emails are optional: failures, payment problems and
account emails always send. A meeting's own `notify_when_ready` (set at
creation, changeable with `PATCH /api/meetings/{id}`) overrides
`notify_job_done` for that meeting's notes.

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

Optional form fields: `transformation` (`document` | `notes` | `study_guide` |
`research`) and, for `research` only, `review_topics` (default `false`). With
`review_topics=true` the job pauses at `status: "awaiting_review"`,
`progress_stage: "awaiting_topic_review"` after proposing topics;
`GET /api/jobs/{job_id}/topics` lists them and
`POST /api/jobs/{job_id}/topics` (`{"topics": [{"topic", "context"}]}`)
confirms an edited/extended list and resumes the job, so the paid web research
only runs on topics the user approved. Whenever a job pauses for review (frame,
scene, or topic review) the user is emailed (`emails.notify_review_needed`), and
reminded once if it is still waiting a day later (`review_reminders.py`, a worker
thread; `REVIEW_REMINDER_AFTER_HOURS`).

#### More documents from a finished video or audio transcript

The app no longer asks what to make up front: a video always produces the
initial set (the formatted document, the transcript, and the images unless
frame extraction was skipped), and `transformation` above defaults to
`document` (the field is kept for API clients; the UI always sends the
default). Notes, a study guide and research are made afterwards from the
finished job (`app/derived.py`, `routes/derived.py`):

- `POST /api/jobs/{job_id}/derive` `{"transformation": "notes" | "study_guide" | "research", "review_topics"?}`
  creates a **child job** (`jobs.parent_job_id`) that skips download, frames and
  transcription: the parent's `transcript.json` is copied to the child's
  `precomputed_segments.json`, so only the text transformation runs. A child is
  an ordinary job (own progress, cancel, refund, email, topic-review pause) but
  is left out of `GET /api/jobs`; list a video's children with
  `GET /api/jobs/{job_id}/derived` (also returns what can be made and the price).
  One live document per type per video (a partial unique index enforces it).
  Notes and study guide are free for now; research is charged at the research
  rate and refunded on failure like any job. It needs the parent's transcript, so
  it stops working once retention sweeps the parent (archived jobs are rebuilt).
- The same works from a finished **audio** job (`job_type == "audio"`, including
  live recordings and captured meetings): its transcript's speaker names are
  applied, so the documents say "Jane Doe", not "Speaker 2". The child is a
  `video`-type job either way (that is what the text-transformation path runs
  on), and keeps those names in its own `transcript.json`.
- Retrying a failed child (`POST /api/jobs/{job_id}/retry`) re-derives it.
- `GET /api/jobs/{job_id}/images`, `GET /api/documents/{job_id}/images.zip` and
  `GET /api/documents/{job_id}/transcript.txt` serve the rest of the initial set
  (`transcript.json` has speaker labels normalized to "Speaker N").

### Runtime settings (admin Settings page)

Operational settings -- per-type prices, upload/duration limits, feature
switches, meeting and reminder timings, LLM provider/model, worker intervals --
can be changed live from **Admin → Settings** (`/admin/settings`) instead of
env vars and a redeploy. The allowed settings and their bounds are the registry
in `app/tunables.py` (no secrets, nothing infrastructural). Overrides are stored
in `app_settings` under `setting:<NAME>` (with who/when), and `config.Settings`
resolves those names through `runtime_config.get`, so existing `settings.X`
reads see them with no call-site changes; each process re-reads the DB at most
every 10 seconds. A setting nobody has changed uses its env var / code default,
and Reset on the page returns to it. To make another setting tunable, add a
`Param` to `tunables.py` (and give it an env/default attribute on `Settings`).

### Speaker identification from the transcript

Audio jobs (uploads, live recordings, meetings) with 2+ speakers get one extra
LLM call (`stages/speaker_ids.py`, stage `identifying_speakers`) that reads the
diarized transcript for self-introductions, roll calls and "thank you, Chair
Smith"-style hand-offs. High-confidence names are filled into `speaker_names`
automatically; medium-confidence ones are kept in `transcript.json`'s
`speaker_hints` and offered as one-click suggestions in the viewer; the quote
each relied on is stored alongside. Meeting notes are written against the
identified names. Failures are soft (you just get "Speaker N"), and
`SPEAKER_AUTO_ID_ENABLED=false` turns it off. Users can still rename any speaker.

### Meeting notetaker (`/api/meetings`)

`POST /api/meetings` (`{"url", "title"?, "start_time"?}`; with a timezone-aware `start_time` more than ~2 minutes ahead (max 30 days) the bot is booked at Recall with `join_at` and the meeting sits at `scheduled` until then) sends a [Recall.ai](https://recall.ai)
bot to a pasted Zoom, Google Meet or Teams link; `GET /api/meetings` lists them;
`DELETE /api/meetings/{id}` makes the bot leave. The bot only records audio --
when Recall reports `bot.done` (via `POST /api/meetings/webhook`,
Svix-signature-verified), the audio is downloaded, the wallet charged at
$1.00/hour, and a normal audio job queued, so our own pipeline
transcribes/diarizes it and adds summary, decisions and action items. A wallet
too low at that point leaves the meeting at `awaiting_payment` (emailed);
`POST /api/meetings/{id}/process` retries after a top-up.

Setup: set `RECALL_API_KEY` / `RECALL_API_BASE` (region must match your Recall
account) and add a webhook in the Recall dashboard pointing at
`<public api url>/api/meetings/webhook`, with its `whsec_...` secret in
`RECALL_WEBHOOK_SECRET`. Recall must be able to reach the API, so local dev
needs a tunnel (e.g. ngrok). Who can use the feature is an admin toggle
(per user, or generally available).

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

`retention.py` is a one-shot script, not part of the API or worker process, and
**nothing runs it unless a scheduler does** -- if the VPS's disk fills up with
`data/uploads` and `data/output`, check that it is scheduled first
(`fab ... retention-status`). It does three things:

1. For every `done` job older than 7 days with `deleted_at IS NULL`, it deletes
   that job's `data/uploads/{job_id}` and `data/output/{job_id}` directories,
   then nulls `document_path` and sets `deleted_at` on the row (the row itself
   -- id, `duration_seconds`, `user_id`, `billed_cents`, timestamps -- is kept,
   since usage/billing history still needs it). `awaiting_review` jobs older
   than 7 days are swept too, refunded and marked `failed`.
2. The same files-only cleanup for `failed`/`cancelled` jobs older than 7 days
   (they never produced a document, and were already refunded; retrying one
   after this asks the user to re-upload).
3. Job-id-named folders under `uploads/` and `output/` that no job row owns and
   that are older than 7 days (e.g. an upload rejected after its file was
   written).

Applies to every job regardless of who owns it; there's no plan tier with
unlimited retention. `python retention.py --dry-run` lists what would go (and
the space it would free) without deleting anything.

Schedule it on the VPS -- not folded into `worker.py`'s poll loop, since that
loop synchronously blocks on a video's full processing time and shouldn't also
carry cleanup latency. From `deploy/`:

```bash
fab -H deploy@YOUR_VPS_IP -i ~/.ssh/your_key retention-run            # preview (dry run)
fab -H deploy@YOUR_VPS_IP -i ~/.ssh/your_key retention-run --delete   # actually delete
fab -H deploy@YOUR_VPS_IP -i ~/.ssh/your_key install-retention-cron   # daily at 03:00
fab -H deploy@YOUR_VPS_IP -i ~/.ssh/your_key retention-status         # is it scheduled / last runs
```

or by hand, as a crontab line (`-T` because cron has no terminal):

```cron
0 3 * * * cd /path/to/vid2doc/backend && docker compose run --rm -T api python retention.py >> /var/log/framewrite-retention.log 2>&1
```

Disk diagnostics for the VPS are in `deploy/fabfile.py`: `disk`, `disk-top`,
`docker-disk`, `job-disk`; `cap-journal` limits the systemd journal.

## Public agency meetings

Framewrite itself watches public recording archives (agencies' YouTube
channels or playlists), publishes a summary, topics and transcript for each
meeting on public pages, and emails people who follow a topic it covered.
Code: `app/agency_ingest.py` (sources, polling, queueing, finishing),
`app/topics.py` (topic list, LLM tagging, public queries), `app/topic_alerts.py`
(email queue). A daemon-thread loop in `worker.py` runs each:

1. **Poll** (only while the `AGENCY_INGEST_ENABLED` setting is on): each
   enabled `meeting_sources` row's newest recordings become `agency_meetings`.
   Recordings older than `AGENCY_BACKFILL_DAYS`, live, longer than
   `AGENCY_MAX_DURATION_SECONDS` or not matching the source's title filter are
   stored as `skipped` so they aren't looked up again.
2. **Queue**: a discovered meeting becomes an owner-less (`user_id` NULL),
   unbilled `audio` job -- diarized transcript with speaker names, nothing to
   review -- at most `AGENCY_MAX_NEW_PER_DAY` a day. Its download is audio-only
   with the agency length cap (`pipeline._download_if_needed`), and the queue
   serves owner-less jobs after user jobs (`jobs.claim_next_queued_job`).
   YouTube captions, when the video has them, replace paid transcription.
3. **Finish**: when the job is done the transcript is copied into the meeting
   row (the job's files can then be swept by retention), the LLM tags it
   against the admin-curated `topics`, it becomes `ready` (public), and one
   `topic_notifications` row per follower is queued. A subject the model sees
   that isn't a listed topic becomes a new active topic on the spot (people can
   follow it right away, and it has no followers yet so it notifies no one);
   an admin can deactivate it, and a deactivated topic is never recreated.
   With the `TOPICS_AUTO_CREATE` tunable off it becomes a `topic_suggestions`
   row for an admin to approve instead. An LLM failure leaves the meeting
   public but untagged -- an admin re-tags it.
4. **Send**: one email per follower per meeting listing their matching topics,
   with `List-Unsubscribe` and a footer link (a `topic_unsubscribe` token that
   only switches off `users.notify_topic_alerts`, via
   `POST /api/announcements/unsubscribe`). A failed send is retried by running
   alert queueing again (an admin re-tag does).

API: public `GET /api/public/topics[/{slug}[/meetings]]` and
`GET /api/public/agency-meetings/{id}` (ready meetings only); signed-in
`GET`/`PUT /api/me/topic-subscriptions`; admin `/api/admin/agency/...`
(sources, topics, suggestions, meetings: add by URL, retag, retry, hide).
Admin UI at `/admin/agency`; public pages at `/topics`, `/topics/{slug}` and
`/agency-meetings/{id}` (server-rendered, so the frontend container needs
`API_INTERNAL_URL`). Tunables are under "Agency ingest" on the admin Settings
page. Only YouTube is supported as a source so far (`MeetingSource.adapter`).

## Importing from a link

`POST /api/convert_from_youtube` (admin-only) takes a YouTube URL or a direct
link to a video/audio file (`app/direct_media.py`), so a recording doesn't
have to be downloaded and re-uploaded. The same goes for "add one recording"
in `/admin/agency`. The server fetches whatever address it's given, so
`direct_media` only allows http(s), requires the host to resolve to public
addresses only, and follows redirects by hand, re-checking each hop. A link
that opens a web page (a Zoom/Teams share link) is refused with an
explanation, since it isn't a file. A direct link is downloaded whole in the
worker, capped by `MAX_UPLOAD_BYTES` (`AGENCY_MAX_DOWNLOAD_BYTES` for public
meetings). Only the file's own link works: it must be reachable without a
login and not expire before the worker fetches it.

## Public showcase

A user can opt a completed `job_type == "video"` job into the public
showcase (see `app/public_jobs.py`, `routes/public_jobs.py`) in exchange for
a full refund of what they were billed, or choose "public" when uploading
(`make_public` on `/api/convert_to_doc` and `/api/convert_from_youtube`), in
which case the job costs nothing and is submitted for review automatically
when it finishes (`Job.public_upfront`). An admin must approve it
(`/admin/public-jobs`) before the refund is issued or it's publicly listed.
Either way it is permanent: the owner can't delete a job once it's in the
showcase flow, and a rejected upfront job is still free.
Approved content needs to survive forever, so it's archived to S3 at
opt-in time (before admin review, not after) rather than relying on the
`data/` directories retention.py sweeps after 7 days — see that file's
module docstring for the full design rationale, and
[`s3-showcase-setup.md`](s3-showcase-setup.md) for one-time bucket setup
(policy, CORS, credentials).

`GET /api/public/showcase` (`app/showcase_feed.py`) is one merged feed: the
approved documents above plus every ready, un-hidden public agency meeting
(see "Public agency meetings"). Each item has a `kind` (`document` or
`meeting`; meetings carry `agency`, `summary` and `topics` instead of a video
and document URL) and the list is newest-first with `limit`/`offset`, or with
`random=true` a random sample of `limit` (the marketing homepage's five).
Meetings join the showcase on their own once ready; hiding one from
`/admin/agency` removes it. The marketing site's `/showcase` page and homepage
carousel read this endpoint.

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
| `GOOGLE_CLIENT_SECRET` | Only needed for the Google Drive integration (see below) — plain Sign-In-with-Google doesn't need it |
| `JWT_SECRET` | Signs the app session token returned by `/api/auth/google` (default is dev-only — generate a real one for prod, e.g. `openssl rand -hex 32`) |
| `ENCRYPTION_KEY` | Encrypts stored Google Drive refresh tokens (see below). Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `ADMIN_EMAILS` | Comma-separated emails auto-granted admin access (`/admin` dashboard) on every login — only ever grants, never revokes |
| `PAYMENTS_ENABLED` | Kill switch for new top-ups (default `true`) — set to `false` to disable `POST /api/billing/checkout/topup` during a Stripe-side incident, without affecting existing balances or job processing |
| `CORS_ALLOWED_ORIGINS` | Comma-separated browser origins allowed to call this API (default `http://localhost:3000`) — add the production frontend origin here once deployed |
| `ASSEMBLYAI_API_KEY` | Real hosted diarization |
| `BASETEN_API_KEY`, `BASETEN_MODEL_URL` | GPU-hosted Whisper + pyannote via a custom Truss deployment (see `baseten/transcribe-diarize/`) |
| `ANTHROPIC_API_KEY` | Frame classification + document composition via Claude (used when `LLM_PROVIDER=anthropic`, the default) |
| `OPENAI_API_KEY` | Frame classification + document composition via OpenAI (used when `LLM_PROVIDER=openai`) |
| `LLM_PROVIDER` | `anthropic` (default) or `openai`. Both stages are skipped entirely if the selected provider's key isn't set -- the document then falls back to the raw merged transcript under one heading, no images/topic organization |
| `OPENAI_MODEL` | Default `gpt-5.4-mini` (vision + structured outputs, cost-efficient). Only used when `LLM_PROVIDER=openai` |
| `TRANSCRIPTION_ENGINE` | `auto` (default) / `assemblyai` / `baseten`. `auto` picks `assemblyai` if `ASSEMBLYAI_API_KEY` is set, else `baseten` if configured, else the job fails with a clear config error -- there's no local-CPU fallback anymore (see below) |
| `WHISPER_MODEL` | `tiny`/`base`/`small`/`medium`/`large` -- passed through to Baseten's remote model, which runs Whisper on a GPU; this backend no longer runs Whisper itself |
| `MAX_UPLOAD_BYTES`, `MAX_DURATION_SECONDS` | Upload guardrails (defaults: 2GB, 90 min) |
| `POSTGRES_PASSWORD` | Password for the self-hosted `postgres` compose service |
| `DATABASE_URL` | SQLAlchemy connection string for `api`/`worker`, e.g. `postgresql+psycopg2://vid2doc:$POSTGRES_PASSWORD@postgres:5432/vid2doc` — host must match the `postgres` service name when running under compose |
| `STRIPE_SECRET_KEY` | Stripe API secret key (test-mode for dev) — no Price ids needed, top-up amount is chosen at checkout time |
| `STRIPE_WEBHOOK_SECRET` | Verifies `POST /api/billing/webhook` signatures — from `stripe listen` locally, or the dashboard's webhook config in prod |
| `RECALL_API_KEY` / `RECALL_API_BASE` | Recall.ai API key and regional host (default `https://us-east-1.recall.ai`; must match your account's region) for the meeting notetaker (`/api/meetings`, see above) |
| `RECALL_WEBHOOK_SECRET` | `whsec_...` signing secret of the Recall webhook pointed at `POST /api/meetings/webhook` |
| `SPEAKER_AUTO_ID_APPLY_CONFIDENCE` | `high` (default) or `medium`: lowest confidence at which a name found in the transcript is applied automatically |
| `SECONDS_PER_CENT_VIDEO` / `_AUDIO` / `_VIDEO_GEN` / `_RESEARCH` / `_MEETING` | Prices as seconds of media per cent (36 = $1.00/hour; defaults 36 / 90 / 20 / 18 / 36) |
| `SPEAKER_AUTO_ID_ENABLED` | `false` skips naming speakers from the transcript text (one extra LLM call per audio job with 2+ speakers; default on) |
| `REVIEW_REMINDER_AFTER_HOURS` / `REVIEW_REMINDER_CHECK_SECONDS` | How long a job may wait for the user's review before the one reminder email (default 24h), and how often the worker checks (default 15 min) |
| `MEETING_BOT_NAME` / `MEETING_MAX_SECONDS` | Name the notetaker joins under, and how long it records before leaving (default 2h). Admins enable the feature per user or for everyone from the admin dashboard |
| `FRONTEND_URL` | Where Stripe Checkout redirects back to after a session |
| `PUBLIC_ARCHIVE_S3_BUCKET`, `PUBLIC_ARCHIVE_S3_REGION`, `PUBLIC_ARCHIVE_BASE_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Permanent S3 archive for the public showcase — see [`s3-showcase-setup.md`](s3-showcase-setup.md) for one-time bucket setup |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend build arg (not read by the backend itself) — public URL the browser uses to reach this API |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Frontend build arg — same value as `GOOGLE_CLIENT_ID` above |
| `NEXT_PUBLIC_GA_MEASUREMENT_ID` | Frontend build arg — Google Analytics measurement ID, same property as the marketing site |
| `MAILGUN_API_KEY`, `MAILGUN_DOMAIN` | Transactional email (welcome email, job-completion/failure email) — no-op if unset, so local dev/CI never need real credentials |
| `MAILGUN_NEWSLETTER_LIST` | Mailgun mailing list address (e.g. `news@mg.framewrite.cc`) the marketing site's newsletter signup adds subscribers to — the list itself is a one-time manual creation in the Mailgun dashboard, not something the code creates. No-op if unset |
| `ANNOUNCEMENT_SEND_DELAY_SECONDS` | Pause between individual admin-announcement emails (default `2`). Announcements are queued as per-user deliveries and sent one at a time by a thread in the `worker` container — see `app/announcements.py` |

To apply schema changes without restarting a container: `docker compose run --rm api alembic upgrade head` (this also runs automatically on every container boot).

## Deploying to a VPS

The `frontend` service's build context is `../frontend` (see
`docker-compose.yml`), so **the whole repo needs to be on the VPS, not just
`backend/`** — this now deploys the full stack (Postgres, API, worker,
frontend) from one `docker compose up`, not just the API.

1. Clone the repo onto the VPS (not just `backend/`).
2. Install Docker + the Compose plugin on the VPS.
3. `cd backend && cp .env.example .env` and fill in real values for
   everything in the table above, in particular:
   - A real `JWT_SECRET` (`openssl rand -hex 32`) — the dev default must
     never be used in production.
   - `CORS_ALLOWED_ORIGINS` — your real frontend origin (e.g.
     `https://app.framewrite.cc`), not `http://localhost:3000`.
   - `NEXT_PUBLIC_API_BASE_URL` — your real public API origin (e.g.
     `https://api.framewrite.cc`), not `http://localhost:8000`. This is a
     Docker **build** arg — changing it later requires rebuilding the
     `frontend` image, not just restarting the container.
   - `FRONTEND_URL` — your real frontend origin, used for Stripe redirect URLs.
   - `STRIPE_SECRET_KEY` — a **live-mode** key when you're ready to accept
     real payments (test-mode keys/cards work fine before that).
4. Add the production frontend origin to the Google Cloud OAuth client's
   Authorized JavaScript origins (Console → APIs & Services → Credentials) —
   `GOOGLE_CLIENT_ID` alone isn't enough; Google also checks the origin the
   sign-in request came from. If you're using the Google Drive integration
   (Settings > Integrations), also: enable the Drive API for the project
   (Console → APIs & Services → Library), add the `drive.file` scope to
   that OAuth client's consent screen, and set `GOOGLE_CLIENT_SECRET` +
   `ENCRYPTION_KEY` in `.env`.
5. Register a production webhook endpoint in the Stripe Dashboard
   (Developers → Webhooks → Add endpoint) pointing at
   `https://<your-api-domain>/api/billing/webhook`, and put the signing
   secret it gives you into `STRIPE_WEBHOOK_SECRET`. (Locally this is
   `stripe listen` instead — see Billing above. Test mode and live mode each
   need their own webhook endpoint registered separately.)
6. `docker compose up -d --build`
7. YouTube import (`POST /api/convert_from_youtube`) is admin-only for now
   (403 for everyone else, and hidden in the frontend) because it is unreliable
   -- it will likely fail on a
   VPS with `Sign in to confirm you're not a bot` -- YouTube bot-checks
   datacenter IPs even for public videos. Fix: export cookies from a real,
   logged-in YouTube session in a browser (e.g. the "Get cookies.txt
   LOCALLY" extension, Netscape format) and place the file at
   `backend/data/youtube_cookies.txt` on the VPS -- `app/youtube.py` picks
   it up automatically (via `--cookies`) if present, no restart needed. Not
   committed to git (`data/` is gitignored); re-export and replace it if it
   ever stops working (exported cookies do eventually expire).
8. Put a reverse proxy (Caddy/nginx/Traefik) in front of it for TLS, routing
   your frontend domain to the `frontend` container (port 3000) and your API
   domain to the `api` container (port 8000) — not included here, since it
   depends on your domain/certs setup. Stripe and the browser both require
   real HTTPS; plain HTTP won't work for either.

The `data/` directory (Postgres's own data dir + uploads + output) lives on
the VPS's local disk via the compose volume mounts — back it up like any
other stateful service if you care about surviving a host rebuild.

## What's not in v1

- No request-level rate limiting beyond the size/duration upload caps — the
  wallet balance check is the only real cost/abuse guardrail right now.
- No job retry on worker crash mid-processing — a killed worker leaves a
  job stuck in `processing` with no automatic recovery. Fine for a
  single-VPS v1; add a staleness check + requeue before scaling traffic.
