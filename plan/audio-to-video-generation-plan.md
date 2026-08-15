# Audio → Video Generation (`job_type="video_gen"`)

## Context

Framewrite's existing pipeline turns a video into a document (transcribe + extract
frames + classify + compose). This plan is the reverse: turn an existing **audio**
file (a voiceover/podcast, not raw text) into a **video** — narration plus
auto-generated visuals (templated highlight cards + matched stock footage/images),
timed captions, and the original audio track muxed in.

The goal is a v1 that ships fast and cheap by reusing as much of the existing
single-worker pipeline, LLM-client plumbing, and human-in-the-loop review pattern
as possible, rather than standing up new infrastructure. AI-generated (fully
synthetic) visuals are explicitly deferred to a v2 upgrade of one stage, not part
of this plan.

**Decisions locked in during brainstorming (do not re-litigate):**
- Input is an existing audio file; reuse `transcribe.py`'s diarized ASR. No TTS.
- Visuals are templated highlight cards + stock media (Pexels), not AI-generated.
- New `job_type` in the existing pipeline (no separate service).
- On-screen text = full timed captions AND per-scene LLM-generated headlines.
- Output is 16:9 for v1 (schema parameterized for future ratios, not implemented).
- No background music in v1 — original narration audio only.
- Stock media source: Pexels API.
- Scenes are segmented via LLM topic segmentation (mirrors `compose.py`'s windowing).

## Pipeline stage order

```
transcribe (reuse _transcribe_segments)
  → segment_scenes (LLM)         [new: stages/scenes.py]
  → generate_headlines (LLM)     [new: stages/highlights.py]
  → fetch_scene_media (Pexels)   [new: stages/stock_media.py]
  → PAUSE: status="awaiting_review" (scenes.json written)
────────── user reviews/edits headlines + swaps stock picks, submits ──────────
  → render_scene_clip × N (ffmpeg)     [new: stages/render_scene.py]
  → concat + burn captions + mux audio [new: stages/assemble_video.py]
  → status="done", document_path=<final .mp4>
```

This preserves the existing pipeline's cost-avoidance philosophy: the genuinely
expensive step (ffmpeg rendering) is deferred until the user commits via review.

## 1. Data model changes

`job_type` needs **no migration** — `backend/app/models.py`'s `Job.job_type` is a
plain `String` with no CHECK constraint (confirmed by reading the model). `"video_gen"`
is just a new string value.

**New columns on `Job`**, added via `backend/alembic/versions/0013_video_gen_job_type.py`:
```python
aspect_ratio: Mapped[str] = mapped_column(String, nullable=False, server_default="16:9")
video_template: Mapped[str | None] = mapped_column(String, nullable=True, server_default="highlight_card")
stock_media_provider: Mapped[str | None] = mapped_column(String, nullable=True, server_default="pexels")
```
`aspect_ratio`/`video_template` are forward-compat placeholders for v2 (only one value
implemented in v1); `stock_media_provider` is an audit trail. Update `jobs.py`'s
`_job_to_dict` and `create_job()` accordingly.

**Reuse `document_path`** for the final rendered `.mp4` path — it already functions
generically as "path to this job's deliverable," so `retention.py`'s sweep and
`routes/status.py::build_job_response` need only a `job_type` branch to expose
`video_url` instead of `document_url`, no new column.

**Scene data as a JSON file, not a new table** — `output_dir/scenes.json`, following
the exact `review.json` precedent (`routes/review.py`, `pipeline.py::resume_after_review`):
an ordered array of `{id, start_ts, end_ts, title, query, headline, media candidates}`.
Job-scoped, ephemeral, no cross-job querying need today — same shape/lifetime as
`review.json`.

## 2. New pipeline stages (`backend/app/stages/`)

- **`scenes.py`** — `segment_scenes(segments, provider=None)`. Reuses `compose.py`'s
  `_make_windows` for chunking; one LLM call per window (same `_get_client_and_fns`
  dual-provider pattern as `compose.py`) returns `{start_ts, end_ts, title, query}` per
  scene. Critical: `_snap_scene_boundaries()` snaps proposed timestamps to real segment
  boundaries and validates scenes tile `[0, duration]` with no gaps/overlaps; falls back
  to fixed-length (~30s) chunking if the LLM's shape is invalid, so segmentation can
  never hard-fail the job.
- **`highlights.py`** — `generate_headlines(scenes, segments, provider=None)`. One batched
  LLM call (same client pattern) producing a short on-screen headline per scene. Runs
  before the review pause so headlines are actually present to review/edit.
- **`stock_media.py`** — `search_photos`/`search_videos`/`fetch_scene_media` against the
  Pexels API via plain `requests` (matches `transcribe.py`'s existing `requests.post`
  pattern for Baseten — no SDK needed). Tries video search first, falls back to photo,
  falls back to a plain gradient card if nothing matches. Fetches 2–3 candidates per
  scene so review can offer a swap without a second round-trip.
- **`render_scene.py`** — `render_scene_clip(scene, output_path, width=1920, height=1080, fps=30)`.
  Produces one silent clip per scene via ffmpeg subprocess calls (no moviepy — matches
  `frames.py`/`transcribe.py`'s existing raw-ffmpeg pattern, smaller image, no ImageMagick
  dependency): `zoompan` Ken Burns for photos (pre-upscale first to avoid jitter),
  `stream_loop`/`scale+crop` for stock video, `lavfi color=` gradient fallback, headline
  burned in via `drawtext`. Identical codec/fps/resolution across scenes so concat needs
  no re-encode.
- **`assemble_video.py`** — `concat_scenes` (ffmpeg concat demuxer, `-c copy`), `generate_srt`
  (hand-rolled, extends `pipeline.py`'s `_format_timestamp` pattern — **captions are
  global**, one `captions.srt` from the full merged transcript, burned in one pass over
  the concatenated video rather than per-scene, to avoid drift), `burn_captions` (ffmpeg
  `subtitles=` filter via libass), `mux_audio` (`-c:v copy -c:a aac`), and an orchestrating
  `render_final_video()`.

**`pipeline.py` changes**: new `_transcribe_and_segment_scenes()` (transcribe → segment →
headlines → stock media → write `scenes.json` → `status="awaiting_review"`) and
`resume_after_scene_review()` (parallel to `resume_after_review`: reads user-edited
`scenes.json`, renders each scene, assembles final video, marks done). `run_job`'s
dispatch gains a `job_type == "video_gen"` branch and a `progress_stage ==
"resuming_after_scene_review"` branch.

**Scoping note**: v1's review step lets the user edit headline text and swap the stock
asset per scene — not delete/merge/reorder scenes, since scenes tile mandatory spans of
narration audio and reordering would require re-syncing audio, which is out of scope.

## 3. Human-in-the-loop pause point

Yes — reuse the existing `awaiting_review` pattern, sitting after stock media fetch
(last cheap step) and before ffmpeg rendering (expensive step). `retention.py`'s existing
sweep for stale `awaiting_review` jobs already works generically, no changes needed.

## 4. New routes

- **`routes/video_gen.py`** — `POST /api/generate_video` (multipart `audio` field, reuses
  `AUDIO_EXTENSIONS`/`save_upload`/`title_from_filename` from `routes/audio.py`), charges
  via billing with `job_type="video_gen"`.
- **`routes/scene_review.py`** (parallel to `routes/review.py`) — `GET .../scene-review`
  (list scenes), `GET .../scene-review/media/{scene_id}` (serve chosen/candidate asset),
  `POST .../scene-review` (persist edits to `scenes.json`, requeue with
  `progress_stage="resuming_after_scene_review"`).
- **`routes/video_output.py`** — `GET /api/videos/{job_id}/output.mp4` (owner-only, same
  ownership-guard pattern as `documents.py`), plus a thumbnail endpoint (`ffmpeg -ss 0
  -vframes 1` at render time).
- `routes/status.py::build_job_response` gets a `job_type == "video_gen"` branch exposing
  `video_url`/`thumbnail_url`. Register new routers in `main.py`.

## 5. Frontend integration

- `frontend/app/(app)/dashboard/video-gen/page.tsx` (new, parallel to `dashboard/audio/page.tsx`) —
  audio upload form, lists jobs via `/api/jobs?job_type=video_gen`, reuses the existing
  `setInterval` polling pattern.
- `frontend/lib/jobs.ts` — extend `JobType` union and `Job` shape with `video_url`/`thumbnail_url`.
- `frontend/components/SceneReviewPanel.tsx` (new, parallel to `FrameReviewPanel.tsx`) —
  scene list with thumbnail-cycle swap control, editable headline input, submit button.
- `frontend/app/(app)/dashboard/jobs/[id]/page.tsx` — add a `video_gen` branch: `<video
  controls>` on done, `SceneReviewPanel` on awaiting_review.
- **Auth'd video playback**: `<video src>` can't send an `Authorization` header — add
  `fetchAuthenticatedBlob()` to `lib/api.ts` (sibling to existing `downloadAuthenticated`),
  use `URL.createObjectURL(blob)` as the video src. Acceptable for short v1 outputs; flagged
  as not ideal for scrubbing/range-requests on longer videos.

## 6. New dependencies / config

- **No new Python packages** — Pexels via existing `requests`; SRT generation hand-rolled;
  no moviepy.
- **New env vars** (`backend/app/config.py`): `PEXELS_API_KEY`, `STOCK_MEDIA_PROVIDER`,
  `VIDEO_GEN_MAX_DURATION_SECONDS` (stricter cap than the existing 90-min `MAX_DURATION_SECONDS`,
  given CPU cost concerns below).
- **Verify at deploy time** (not a code change): the deployed ffmpeg build includes `libass`
  (needed for the `subtitles` filter) — this is the first feature to need it.

## 7. Billing

Extend `billing.py`'s `cost_for_duration_cents()` with a third rate,
`SECONDS_PER_CENT_VIDEO_GEN`, wired into the existing job_type branch. **This rate needs
real measurement before launch, not a guess** — ffmpeg render CPU-time (scaling with output
duration) is a genuinely new cost driver, unlike the existing two rates which were priced
against 3rd-party API $ costs. Note: the existing refund-on-any-failure behavior in
`run_job`'s except block refunds the full charge even if a job fails late (e.g. after most
scenes rendered) — an acceptable v1 tradeoff, matching existing all-or-nothing philosophy.

## 8. Risks / open questions

1. **Single-worker CPU contention** — `worker.py` processes one job at a time, serially.
   ffmpeg rendering is far more CPU/wall-clock-heavy than today's mostly I/O-bound jobs; one
   video_gen job could tie up the only worker for minutes, blocking all other queued jobs.
   Biggest architectural risk; may eventually need a second worker or priority queue, but out
   of scope to solve now.
2. **ffmpeg `libass`/`subtitles` filter availability** must be verified in the actual deployed image.
3. **Caption granularity is engine-dependent** — `_transcribe_segments` always calls the
   uniformly-merging `transcribe_diarize`, so v1 should ship phrase/segment-level subtitle
   cues (not true word-by-word/karaoke highlighting, which isn't achievable uniformly across
   the four transcription engines without engine-specific changes).
4. **Pexels licensing** — confirm current terms permit this use (commercial derivative output
   without attribution) before launch; consider a curated subset if the API exposes one.
5. **`zoompan` Ken Burns jitter** is a known finicky ffmpeg filter — needs real tuning
   (pre-upscale factor, frame-rate interaction), not a copy-paste recipe.
6. **Scene-boundary validation** — LLM segmentation must guarantee contiguous, gap/overlap-free
   scenes; the snap-to-boundary + fixed-length fallback (section 2) covers this.
7. **Audio/video duration drift at final mux** — use explicit `apad`/`tpad` padding to the
   audio's exact duration rather than relying on `-shortest`'s coarser truncation.
8. **Render wall-clock time is unknown until measured** — worth an estimated-time indicator
   on the dashboard once real numbers exist.

## Verification

- Confirmed against actual code (not assumed): `Job.job_type` is an unconstrained `String`
  (`backend/app/models.py`), the `awaiting_review`/`review.json` pause-resume pattern is real
  (`backend/app/pipeline.py`), `compose.py` has `_get_client_and_fns` and `_make_windows` as
  named, and `billing.py::cost_for_duration_cents` already branches on `job_type` string
  comparison — extending to a third value is a straightforward addition.
- End-to-end test plan once built: upload a short (~2 min) narration audio file through
  `/api/generate_video`, confirm it pauses at `awaiting_review` with populated `scenes.json`
  and downloaded stock candidates, edit a headline and swap a stock pick via the new scene
  review UI, submit, confirm the worker renders and produces a playable `.mp4` with burned-in
  captions matching the narration and correct total duration (no audio/video drift), then
  verify billing charged and (on a forced failure) refunded correctly.

### Critical files
- `backend/app/pipeline.py`, `backend/app/models.py`, `backend/app/jobs.py`, `backend/app/billing.py`
- `backend/app/stages/compose.py`, `backend/app/stages/transcribe.py`, `backend/app/stages/frames.py`
- `backend/app/routes/review.py`, `backend/app/routes/audio.py`, `backend/app/routes/status.py`
- `backend/app/config.py`, `backend/worker.py`
- `backend/alembic/versions/0004_job_type.py` (precedent for the new migration)
- `frontend/app/(app)/dashboard/audio/page.tsx`, `frontend/app/(app)/dashboard/jobs/[id]/page.tsx`
- `frontend/components/FrameReviewPanel.tsx`, `frontend/lib/jobs.ts`, `frontend/lib/api.ts`
