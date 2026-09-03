# Video-to-document: optional frame extraction + AI summary/key points

## Context

Today, every `video` job always runs the full frame pipeline (extract →
filter → classify → pause for the user's `awaiting_review` selection) before
composing the document, and always bills at the video rate. This is wasted
work and cost for videos where the visual content doesn't matter (podcasts
recorded on camera, screen-share-less meetings, etc.) — the user wants a way
to skip it. Separately, composed video documents currently get no
summary/overview at all (that only exists for `audio` jobs today) — the user
wants every video document to open with an AI-written summary and key
points, so the reader gets the gist before diving into the full transcript.

**Decided with the user** (via AskUserQuestion):
1. Skipping frame extraction bills at the existing **audio rate** (~$0.40/hr,
   not ~$1.00/hr) — the work performed genuinely matches the audio pipeline
   (transcribe + compose, no frame capture/classification), and `audio`'s
   lower rate is already documented as being priced for exactly that.
2. The upload page shows a **live estimated cost** next to the toggle,
   computed client-side from the file's duration, so the price difference is
   visible before submitting.
3. The new summary/key-points feature is **video-only** — the existing audio
   summary path (`generate_summary`, `_build_audio_sections`,
   `TranscriptViewer.tsx`) stays untouched.

Both features touch the same call chain and the same upload page, so they
ship together: **migration → `jobs.py` → `pipeline.py`/`compose.py` →
routes → frontend**.

## Feature 1: optional frame extraction

### Data model
New Alembic migration `backend/alembic/versions/0015_extract_frames.py`
(revises `0014`, same shape as `0014_job_cancellation.py`):
```python
def upgrade() -> None:
    op.add_column("jobs", sa.Column("extract_frames", sa.Boolean(), nullable=False, server_default=sa.true()))

def downgrade() -> None:
    op.drop_column("jobs", "extract_frames")
```
`server_default=sa.true()` backfills existing rows to `True`, preserving
current behavior for every pre-existing job. Add the matching column to
`Job` in `backend/app/models.py` (`Mapped[bool]`, `default=True`), with a
comment noting it's only meaningful for `job_type == "video"`.

### Backend wiring
- `backend/app/jobs.py`: `create_job(...)` gets an `extract_frames: bool =
  True` param passed to `Job(...)`; `_job_to_dict` returns it.
- `backend/app/routes/convert.py`: new `extract_frames: bool = Form(True)`
  param on `POST /api/convert_to_doc`. Billing call becomes
  `billing.charge_for_job(user_id, job_id, duration, job_type="video" if
  extract_frames else "audio")` — reuses `cost_for_duration_cents`'s
  existing audio-rate branch (`backend/app/billing.py:36`), no new rate
  constant needed. The `Job.job_type` column itself stays `"video"` either
  way (pipeline dispatch is unaffected) — only the billing call's `job_type`
  argument changes. Pass `extract_frames=extract_frames` to `create_job`.
- `backend/app/routes/youtube.py`: add `extract_frames: bool = True` to
  `YoutubeConvertRequest`; same billing/create_job treatment using
  `body.extract_frames`.
- `backend/app/routes/jobs.py`'s `retry_job` (line 31): must preserve the
  flag and its billing consequence — read `job.get("extract_frames", True)`,
  derive `billing_job_type = "audio" if (job["job_type"] == "video" and not
  extract_frames) else job["job_type"]` for the `charge_for_job` call, and
  pass `extract_frames=extract_frames` to `create_job`. Without this, a
  frames-skipped job's retry would silently re-bill at the full video rate.
- `backend/app/routes/status.py`'s `build_job_response`: include
  `extract_frames` in the response when `job["job_type"] == "video"`, so the
  frontend can show it in the job detail view.

### Pipeline changes (`backend/app/pipeline.py`)
Add a new branch in `run_job`, right after `_download_if_needed` and before
the existing frame-extraction block (~line 435), parallel to the
`is_video_gen_job`/`is_audio_job` branches:
```python
if job.get("job_type") == "video" and not job.get("extract_frames", True):
    _check_not_cancelled(job_id)
    _compose_and_finalize(job, output_dir, [], [])
    return
```
**Unify this with the existing "nothing to review" fallback** (current tail
of the video branch, ~lines 468-472): that path is functionally the same
situation (no images/tables to render) just *discovered* instead of
*chosen*. Replace its manual `_transcribe_segments` + `_fallback_sections`
call with the same `_compose_and_finalize(job, output_dir, [], [])` call —
removing the duplicate transcription call (it already transcribes
internally) and, as a side effect, upgrading that edge case from a raw
transcript dump to a properly LLM-composed document (when an LLM *is*
available but simply found no frame candidates).

Update `_compose_and_finalize` (~line 197) to handle being called with no
images/tables and possibly no LLM at all (a case it previously never saw,
since it was only ever reached via `resume_after_review`, which implies
classified frames existed):
```python
def _compose_and_finalize(job, output_dir, images_meta, tables_meta):
    job_id = job["id"]
    segments = _transcribe_segments(job, output_dir)
    _check_not_cancelled(job_id)

    if not images_meta and not tables_meta and not _llm_available():
        title = job.get("title") or "Video Transcript"
        sections = _fallback_sections(segments)
    else:
        jobs.update_job(job_id, progress_stage="composing_document")
        sections = compose.compose_document(segments, images_meta + tables_meta)
        title = compose.generate_title(sections)
        jobs.update_job(job_id, title=title)
        if not sections:
            sections = _fallback_sections(segments)
        else:
            sections = _prepend_summary_section(job, segments, sections)

    _finalize_document(job, title, sections, images_meta, tables_meta)
```
This one function now correctly serves all three cases: normal
post-review composition, the new frames-skipped path, and the old
no-candidates/no-LLM path — and Feature 2's summary applies uniformly
wherever a document is actually composed (see below).

## Feature 2: AI summary + key points (video documents only)

### `backend/app/stages/compose.py`
Add `generate_summary_and_key_points(segments, provider=None) -> dict`
(`{"summary": str, "key_points": list[str]}`), reusing the exact same
`_make_windows`/map-reduce machinery and Anthropic-tool-use-vs-OpenAI-
structured-JSON dispatch as the existing `generate_summary` (line 293) —
same pattern, extended schema:
- New prompts `SUMMARY_KEY_POINTS_SYSTEM_PROMPT` /
  `FINAL_SUMMARY_KEY_POINTS_SYSTEM_PROMPT` (mirroring `SUMMARY_SYSTEM_PROMPT`
  / `FINAL_SUMMARY_SYSTEM_PROMPT`, extended to ask for 3-6 short standalone
  key points alongside the paragraph).
- New `SUMMARY_KEY_POINTS_TOOL` / `SUMMARY_KEY_POINTS_JSON_SCHEMA` (mirroring
  `SUMMARY_TOOL`/`SUMMARY_JSON_SCHEMA`, `{summary: string, key_points:
  string[]}`), new `_summarize_with_key_points_anthropic` /
  `_summarize_with_key_points_openai` (mirroring `_summarize_anthropic`/
  `_summarize_openai`).
- Single window → one call; multiple windows → per-window calls then one
  final merge call (same shape as `generate_summary`'s map-reduce). Truncate
  `key_points` to 6 in code (`[:6]`) rather than enforcing via schema,
  consistent with how sentence counts aren't hard-enforced elsewhere.

### `backend/app/pipeline.py`
Add `_prepend_summary_section(job, segments, sections) -> list[dict]`
(video-only; does not touch `_build_audio_sections`/`generate_summary`):
```python
def _prepend_summary_section(job, segments, sections):
    if not _llm_available():
        return sections
    job_id = job["id"]
    _check_not_cancelled(job_id)
    jobs.update_job(job_id, progress_stage="summarizing")
    try:
        result = compose.generate_summary_and_key_points(segments)
    except Exception as e:
        print(f"Summary/key-points generation failed for job {job_id}: {e}", flush=True)
        return sections
    blocks = [{"type": "paragraph", "text": result["summary"], "ref": 0, "caption": ""}]
    if result.get("key_points"):
        blocks.append({"type": "paragraph", "text": "Key Points:", "ref": 0, "caption": ""})
        blocks.extend(
            {"type": "paragraph", "text": f"• {kp}", "ref": 0, "caption": ""}
            for kp in result["key_points"]
        )
    return [{"heading": "Summary", "blocks": blocks}] + sections
```
Soft-fails exactly like the existing audio summary path (never breaks the
job over a summary failure), with `_check_not_cancelled` outside the
`try` so cancellation isn't swallowed. Called from `_compose_and_finalize`
only when `sections` is non-empty (i.e. real composed content exists, not
a raw verbatim fallback) — see the updated function above.

**Rendering**: `backend/app/stages/assemble.py`'s three renderers
(markdown/docx/pdf) all just print `block["text"]` verbatim for `type:
"paragraph"` blocks — none do markdown parsing. So each key point is its
**own** paragraph block prefixed with a literal `"• "`, never one block
containing `"- a\n- b"` (which would render as a single run-on line in
docx/pdf). No renderer changes needed — this is exactly the existing
block contract (`_fallback_sections`/`_build_audio_sections` already use
it the same way).

## Frontend changes

- `frontend/app/(app)/dashboard/video/page.tsx`: new `extractFrames`
  (default `true`) and `fileDurationSeconds` state. On file selection,
  probe duration via an offscreen `<video>` element's `loadedmetadata`
  event (`URL.createObjectURL` → set as `src` → read `.duration` → revoke).
  Render one checkbox toggle ("Extract frames (slides, diagrams, tables)")
  above the file/YouTube inputs, shared by both submit paths since they're
  on the same page. Show a cost estimate line using the two flat per-hour
  rates mirrored from `backend/app/billing.py` (`SECONDS_PER_CENT`,
  `SECONDS_PER_CENT_AUDIO` — comment pointing back at that file so they
  don't silently drift): for the file path, compute a dollar estimate once
  duration is known; for the YouTube path (no client-side duration
  available), show the flat per-hour rates instead (e.g. "$1.00/hr with
  visuals, $0.40/hr transcript-only") rather than building a new
  metadata-peek endpoint just for a live YouTube estimate. `handleUpload`
  appends `extract_frames` (stringified) to the FormData; `handleYoutubeSubmit`
  includes `extract_frames` in its JSON body.
- `frontend/lib/jobs.ts`: add `extract_frames?: boolean` to the `Job` type.
- `frontend/app/(app)/dashboard/jobs/[id]/page.tsx`: small polish — add a
  "Frames: Included / Excluded (transcript only)" row to the metadata `<dl>`
  when `job.job_type === "video" && job.extract_frames != null`.
- `frontend/components/DocumentPreview.tsx`: give the summary section a
  distinct visual treatment matching `TranscriptViewer.tsx`'s existing
  audio-summary box (`bg-paper-shade` rounded callout). Since
  `react-markdown`'s node-level overrides can't cleanly wrap an `## Summary`
  heading plus its following content, split the raw markdown string on a
  `^## Summary$` line before rendering (before/summary/after), render the
  middle slice inside the callout `<div>` using the same `components` map,
  and render `before`/`after` normally. Only triggers for a section
  literally titled "Summary" — everything else (including audio jobs, which
  don't use `DocumentPreview` for their summary at all) is unaffected.

## Edge cases

- **YouTube captions + frames skipped**: `_download_if_needed`'s caption
  fetch runs unconditionally, independent of `extract_frames`;
  `_transcribe_segments` still short-circuits on `precomputed_segments.json`
  regardless of which path reaches it. No interaction, no code change.
- **Cancellation**: both the new frames-skipped branch and
  `_prepend_summary_section` call `_check_not_cancelled` outside any
  soft-fail `try`, so a cancellation is never swallowed by the summary's
  `except Exception`.
- **Retry**: must read and re-pass `extract_frames`, and re-derive the
  billing `job_type` the same way the original charge did (see
  `routes/jobs.py` above) — otherwise a retried frames-skipped job gets
  silently re-billed at the full video rate.
- **No-LLM-at-all**: `_compose_and_finalize`'s new branch condition
  (`not images_meta and not tables_meta and not _llm_available()`) keeps
  the old plain-transcript fallback for this specific case, while a rarer
  "images/tables exist but the LLM key was removed mid-flight" case still
  goes through `compose_document` and fails loudly rather than silently
  dropping already-classified images/tables.
- **DOCX/PDF table of contents**: adding a "Summary" section increases the
  section count by one; `assemble.py`'s existing `len(sections) > 1` TOC
  threshold already handles this generically — no code change, just don't
  be surprised a previously single-section document now gets a TOC.

## Verification

No `pytest` harness exists in `backend/tests/` (empty directory) — follow
this session's established pattern of real functional checks via `docker
exec backend-api-1 python3 -c "..."` against the actual dev DB (create a
throwaway job/user, assert, clean up), same as prior features in this repo.

1. `jobs.create_job(..., extract_frames=False)` → `jobs.get_job(...)`
   round-trips `False`; omitting the param round-trips `True`.
2. `compose.generate_summary_and_key_points(segments)` — single-window
   transcript returns `{"summary": str, "key_points": [3-6 strings]}`;
   feed a >3500-word synthetic transcript to exercise the map-reduce branch.
3. `billing.cost_for_duration_cents(3600, "audio")` vs `(3600, "video")` —
   confirm the two rates convert.py/youtube.py's new billing branch relies on.
4. End-to-end via `/api/convert_to_doc` with `extract_frames=false`: confirm
   no `awaiting_review` pause (`queued → processing → done` directly),
   `billed_cents` matches the audio rate, `document.md` opens with a
   "Summary" section containing `•`-prefixed key points as separate lines
   (not one run-on line), and `document.docx`/`document.pdf` render the
   same key points as separate lines too.
5. End-to-end via `/api/convert_from_youtube` with `extract_frames: false`
   — same assertions, plus confirm a video with real captions still skips
   paid transcription.
6. End-to-end with `extract_frames` omitted/true (unaffected path): confirm
   it still pauses at `awaiting_review` and bills at the video rate as
   before — but note the finished document now *also* gets a prepended
   Summary section post-review, since `_compose_and_finalize` is shared;
   this is new, intended behavior for every video job, not a regression.
7. Retry a failed frames-skipped job via `/api/jobs/{id}/retry`: confirm the
   new job bills at the audio rate again.
8. With both `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` unset: confirm a
   frames-skipped video job still completes via the plain verbatim
   `_fallback_sections` output with no Summary section (soft no-LLM path).
9. Frontend: `npx tsc --noEmit`; manually verify in the browser that the
   cost estimate updates on file selection and on toggling extract_frames,
   that `DocumentPreview.tsx` renders the Summary callout only for a
   document containing a literal "## Summary" heading, and that audio jobs'
   `TranscriptViewer.tsx` summary box is visually/functionally unaffected.

### Critical files
- `backend/alembic/versions/0015_extract_frames.py` (new)
- `backend/app/models.py`, `backend/app/jobs.py`
- `backend/app/pipeline.py`, `backend/app/stages/compose.py`
- `backend/app/routes/convert.py`, `backend/app/routes/youtube.py`,
  `backend/app/routes/jobs.py`, `backend/app/routes/status.py`
- `frontend/app/(app)/dashboard/video/page.tsx`,
  `frontend/app/(app)/dashboard/jobs/[id]/page.tsx`
- `frontend/lib/jobs.ts`, `frontend/components/DocumentPreview.tsx`
