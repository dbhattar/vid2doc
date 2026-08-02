# Anonymous "try it free" upload on the marketing site (replaces the game)

## Context

The marketing homepage currently has an interactive game ("Spot the Slide") meant to engage
visitors. The user wants to replace it with something more directly convincing: let a visitor
upload a short video (~10 min) or audio (~30 min) file and get back a *real* Framewrite
document/transcript, with no login required. This is a much stronger conversion hook than a game,
but it opens an unauthenticated endpoint that triggers real backend compute cost (frame
extraction, vision classification, transcription, LLM composition) — so it needs deliberate abuse
prevention, since there's no billing gate to naturally throttle it the way authenticated uploads
are throttled today.

Per your decisions: bot defense is **Cloudflare Turnstile + a per-IP daily cap** (no CAPTCHA-only
or rate-limit-only), and trial video jobs **skip the interactive frame-review pause** — all
detected frames get auto-included, which also becomes a natural "sign up to get full control over
frame selection" upsell hook.

## Current state (from research)

- **Marketing site** (`marketing/`, Astro): the game is fully self-contained in
  `marketing/src/components/SpotTheSlide/` (`.astro` + `.ts` + `.css`), wired into
  `marketing/src/pages/index.astro` (import line 5, usage line 19, between `Hero` and
  `WhatsNewGrid`). No other references anywhere. The marketing site has **zero existing
  backend/API integration** — no `fetch`, no env-var convention, no forms — this trial widget
  will be the first.
- **Backend auth** (`app/deps.py`): `get_current_user` always requires a Bearer session token or
  API key; there's no anonymous path today. Every job route enforces `job["user_id"] ==
  current_user["id"]` for ownership.
- **`Job.user_id` is already nullable** (`models.py`) — a leftover from before auth existed, and
  every refund/delete/retention code path already guards on `if job.get("user_id")` before
  touching billing. This means **`user_id IS NULL` is already a safe, unambiguous signal for "this
  is a trial job"** — no new column needed for that distinction.
- **Upload flow** (`routes/convert.py`, `routes/audio.py`, `media.py`): extension check → stream to
  disk enforcing a byte cap → `ffprobe` duration → duration cap → charge wallet → create job.
  `media.save_upload(upload, upload_dir, dest_path, max_upload_bytes, max_duration_seconds, kind)`
  already takes the caps as parameters — trial-specific caps need no changes to `media.py`, just a
  new caller passing tighter constants.
- **No rate-limiting/CAPTCHA/Redis infra exists at all.** Postgres (already running) is the only
  available shared-state store. `docker-compose.yml`'s api service runs uvicorn with
  `--proxy-headers --forwarded-allow-ips=*` behind nginx, so `request.client.host` already reflects
  the real client IP — that plumbing is ready, nothing consumes it yet.
- **Alembic is set up** (`backend/alembic/`, migrations `0001`–`0007`) — adding a column is a normal
  migration, not a special case.
- **`retention.py`** is a single daily cron script (`0 3 * * *`) that soft-deletes (`deleted_at`,
  keeps the row) `done`/`awaiting_review` jobs older than 7 days, with a refund for
  `awaiting_review`. Trial jobs need a much shorter, unconditional **hard** delete instead (no
  refund ever happened, no billing history worth keeping) — cleanest as a second pass in the same
  daily script, not a new cron schedule.

## Design

### 1. New `client_ip` column (migration `0008_trial_client_ip.py`)

`jobs.client_ip: str | None`, nullable, populated only for trial submissions (via
`request.client.host`). This is the basis for the per-IP daily cap — check via a plain SQL count
(`WHERE user_id IS NULL AND client_ip = :ip AND created_at > now() - interval '1 day'`), no Redis
needed.

### 2. Trial-specific config (`app/config.py`)

```python
TRIAL_MAX_VIDEO_DURATION_SECONDS = 600   # 10 min
TRIAL_MAX_AUDIO_DURATION_SECONDS = 1800  # 30 min
TRIAL_MAX_UPLOAD_BYTES = 300 * 1024 * 1024  # 300MB -- generous for either cap, blocks garbage uploads
TRIAL_MAX_PER_IP_PER_DAY = 2
TRIAL_RETENTION_HOURS = 6
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")
```

### 3. Turnstile verification (`app/turnstile.py`, new)

One function, `verify_turnstile_token(token: str, remote_ip: str) -> bool`, POSTs to
`https://challenges.cloudflare.com/turnstile/v0/siteverify` with `secret`/`response`/`remoteip`
(via `requests`, already in `requirements.txt`) and returns the `success` field. Fails closed (any
error/exception → `False`).

### 4. New `routes/trial.py`

- **`POST /api/trial/convert_to_doc`** and **`POST /api/trial/transcribe_audio`** — mirror
  `routes/convert.py`/`routes/audio.py` but: no `Depends(get_current_user)`; take an added
  `turnstile_token: str = Form(...)`; order of checks: (1) verify Turnstile — 403 if it fails, (2)
  count this IP's trial jobs in the last 24h — 429 if `>= TRIAL_MAX_PER_IP_PER_DAY`, (3) extension
  check, (4) `save_upload(..., settings.TRIAL_MAX_UPLOAD_BYTES, settings.TRIAL_MAX_VIDEO_DURATION_SECONDS or TRIAL_MAX_AUDIO_DURATION_SECONDS, ...)`,
  (5) `jobs.create_job(..., user_id=None, billed_cents=0, client_ip=request.client.host)`. No
  `billing.charge_for_job` call at all — trial jobs are simply never charged (the per-IP cap +
  duration cap + Turnstile are what stand in for the missing billing gate).
- **`GET /api/trial/status/{job_id}`** — tokenless; 404 unless `job["user_id"] is None`. Same
  response shape as `status.build_job_response`, but document URLs point at the new tokenless
  routes below instead of `/api/documents/...` (which requires auth). Job ids are UUIDv4s
  (unguessable) — "possession of the id = access" is an intentional, appropriately-scoped model
  here since trial jobs hold nothing sensitive and are short-lived by design.
- **`GET /api/trial/documents/{job_id}/{file_path}`** and **`/bundle.zip`** — same pattern as
  `routes/documents.py`'s `_owned_done_doc_dir`, just swapping the ownership check for `job["user_id"]
  is None`.
- Register the router in `main.py` next to the others.

### 5. Pipeline: trial jobs skip the review pause (`app/pipeline.py`)

Extract the compose→title→finalize tail (currently duplicated conceptually between the "skip
review" fast path and `resume_after_review`) into one shared helper:

```python
def _compose_and_finalize(job, output_dir, images_meta, tables_meta):
    segments = _transcribe_segments(job, output_dir)
    jobs.update_job(job["id"], progress_stage="composing_document")
    sections = compose.compose_document(segments, images_meta + tables_meta)
    title = compose.generate_title(sections)
    jobs.update_job(job["id"], title=title)
    if not sections:
        sections = _fallback_sections(segments)
    _finalize_document(job, title, sections, images_meta, tables_meta)
```

`resume_after_review` becomes a thin wrapper: load `review.json`, filter to `included`, run
`classify.caption_frames`, call `_compose_and_finalize`.

In `run_job`'s video branch, where it currently checks `if images_meta or tables_meta:` and pauses
for review — add a branch for `job.get("user_id") is None`: caption everything (no filtering, since
trial has no review step to filter after) and call `_compose_and_finalize` directly instead of
writing `review.json`/setting `awaiting_review`. Real users keep today's exact behavior.

### 6. Retention: hard-delete trial jobs after `TRIAL_RETENTION_HOURS` (`retention.py`, `app/jobs.py`)

New `jobs.list_trial_jobs_eligible_for_cleanup(cutoff) -> list[dict]`: `Job.user_id.is_(None),
Job.created_at < cutoff` (any status — an abandoned/stuck trial job is just as safe to purge as a
finished one, since nothing was ever charged). `retention.py`'s `main()` gets a second pass after
the existing 7-day sweep: for each eligible trial job, `shutil.rmtree` its output/upload dirs and
call `jobs.delete_job(job_id)` (hard delete, reusing the existing helper — no soft-delete/refund
bookkeeping needed since trial jobs never had a charge). Same daily cron, no new schedule.

### 7. Marketing site: replace the game with the trial widget

- Delete `marketing/src/components/SpotTheSlide/` and its import/usage in `index.astro`; the new
  component takes the same slot in the homepage flow (between `Hero` and `WhatsNewGrid`).
- New `marketing/src/components/TrialUpload/` (`.astro` + `.ts` + `.css`, mirroring the deleted
  game's file layout): a single drop-zone-style file input (auto-detects video vs audio by
  extension, same UX as the app's original combined uploader), a Turnstile widget
  (`PUBLIC_TURNSTILE_SITE_KEY`), an Upload button, and a result area that polls
  `GET /api/trial/status/{job_id}` (plain `fetch`, no framework — matches this site's existing
  "vanilla script" convention from the game) and shows progress text, then on `done` shows
  markdown/docx/pdf download links plus a "Sign up for full control (and longer videos)" CTA
  linking to `https://app.framewrite.cc/login`; on `failed` shows the error and lets them retry.
- Client-side pre-check (UX nicety, not a security boundary): read the selected file's duration via
  a hidden `<video>`/`<audio>` element before uploading, and show an inline error immediately if
  it's over the cap, rather than waiting on a full upload+ffprobe round trip to find out.
- New env vars: `PUBLIC_API_URL` (backend base URL) and `PUBLIC_TURNSTILE_SITE_KEY`, read via
  `import.meta.env` (this is the first time the marketing site needs either kind of env var, since
  it's had no backend integration before now).
- Style with the existing tokens (`marketing/src/styles/tokens.css`): `--paper`/`--ink`/`--accent`,
  `--font-display` (Fraunces) for the heading, `--font-mono` for status text, no border-radius, no
  shadows — consistent with the rest of the site.

### 8. Deployment/ops steps (not code, but required for this to work)

- Set `TURNSTILE_SECRET_KEY` on the backend and create a Turnstile site + secret in the Cloudflare
  dashboard (get `PUBLIC_TURNSTILE_SITE_KEY` for the marketing site from the same place).
- Add the marketing site's production origin to the backend's `CORS_ALLOWED_ORIGINS` env var —
  today it only has the app's origin.

## Deferred / explicitly out of scope

- Interactive frame review for trial jobs (per your decision — trial auto-includes everything).
- Any lead-capture (email gate) before showing/downloading the trial result — not requested; the
  "sign up" CTA is offered but not required to see the result.
- Per-account (as opposed to per-IP) trial limits, or trial abuse analytics/dashboards.
- Reusing this same anonymous flow for anything beyond the homepage widget (e.g. an embeddable
  widget elsewhere).

## Files touched

- `backend/alembic/versions/0008_trial_client_ip.py` (new) — adds `jobs.client_ip`.
- `backend/app/models.py` — add `client_ip` column to `Job`.
- `backend/app/config.py` — trial caps + `TURNSTILE_SECRET_KEY`.
- `backend/app/turnstile.py` (new) — `verify_turnstile_token`.
- `backend/app/routes/trial.py` (new) — the routes in section 4.
- `backend/app/main.py` — register `trial.router`.
- `backend/app/jobs.py` — `create_job(...)` (currently: `job_id, source_path, user_id=None,
  duration_seconds=None, size_bytes=None, billed_cents=0, title=None, job_type="video"`) gains a
  `client_ip: str | None = None` param; new `list_trial_jobs_eligible_for_cleanup(cutoff)` and
  `count_trial_jobs_from_ip_since(ip, since)` (used by the per-IP cap check in `routes/trial.py`).
- `backend/app/pipeline.py` — `_compose_and_finalize` helper; trial-skip-review branch in
  `run_job`; `resume_after_review` simplified to use the new helper.
- `backend/retention.py` — second pass hard-deleting expired trial jobs.
- `marketing/src/components/SpotTheSlide/` — deleted.
- `marketing/src/components/TrialUpload/` (new).
- `marketing/src/pages/index.astro` — swap `SpotTheSlide` for `TrialUpload`.
- `marketing/.env.example` (new or updated) — document `PUBLIC_API_URL`,
  `PUBLIC_TURNSTILE_SITE_KEY`.

## Verification

1. From the deployed (or local) marketing homepage, upload a short (~1 min) test video with no
   login — confirm it's accepted, and confirm a matching `jobs` row exists with `user_id IS NULL`,
   `billed_cents = 0`, and a populated `client_ip`.
2. Confirm the trial job goes straight from classification to `composing_document` (never
   `awaiting_review`), and finishes `done` with a real, downloadable document (md + docx + pdf).
3. Confirm the status/document endpoints work with no `Authorization`/`X-API-Key` header, and that
   hitting `/api/trial/status/{job_id}` or `/api/trial/documents/{job_id}/...` for a real
   authenticated user's job id returns 404 (ownership check correctly excludes non-null-`user_id`
   jobs).
4. Upload a video longer than 10 minutes (or audio over 30) and confirm a clear 400 before the job
   is created; try a file over `TRIAL_MAX_UPLOAD_BYTES` and confirm a 413.
5. Submit `TRIAL_MAX_PER_IP_PER_DAY` trial jobs from the same IP, then a `+1`th — confirm 429.
6. Submit with a missing/invalid Turnstile token — confirm 403, no job created, no file left on disk.
7. Backdate a trial job's `created_at` past `TRIAL_RETENTION_HOURS` and run `retention.py` —
   confirm its row is fully gone (not soft-deleted) and its output/upload dirs are removed,
   while a real user's job untouched by the same run stays exactly as today's behavior does.
8. Confirm a real authenticated video upload is completely unaffected: it still pauses at
   `awaiting_review` exactly as before, review/caption/resume flow unchanged.
