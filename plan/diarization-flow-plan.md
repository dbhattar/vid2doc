# Diarization flow upgrade: JSON transcript, speaker identities, summary, viewer

## Context

Today, `job_type == "audio"` jobs already run full diarization
(`transcribe.transcribe_diarize()`, `backend/app/pipeline.py:76`) but the
speaker/timestamp data is discarded the moment it's turned into a plain
verbatim document (`_verbatim_transcript_sections`, `pipeline.py:46-62`) --
no JSON export, no way to tell the app who "Speaker A" actually is, no
summary, and no UI that shows who said what. Video jobs also run diarization
internally, but their LLM composition step (`compose.py`) intentionally
rewrites segments into prose with no per-speaker attribution preserved --
**that stays exactly as-is, untouched by this plan.**

**Confirmed with the user:**
1. Scope: this upgrades the **Audio job type in place** -- Audio's whole
   purpose is already diarized transcription, so it gets: a persisted
   `transcript.json`, speaker-identity renaming (reflected in the
   regenerated document), an automatic summary section, and a "who said
   what" viewer on the job detail page. Video is not touched at all. No new
   job type, no new upload flow, no upload-time choice to add.
2. The summary is generated automatically as part of every audio job run
   (one more LLM call, same idea as video's existing classify/compose
   calls), folded into the existing $0.40/hour audio price -- no new
   billing logic. **Worth knowing:** `backend/app/billing.py`'s
   `SECONDS_PER_CENT_AUDIO` comment currently says audio "skips... compose
   LLM calls entirely" -- that becomes slightly inaccurate (audio now makes
   exactly one summary LLM call, still skips frame capture/vision
   classification/full compose) and should be reworded as part of this
   change. This does shift audio's actual cost-to-serve slightly even
   though the price doesn't change.

No database migration is needed -- everything new (segments, speaker
names, summary text) lives in one JSON file already housed alongside the
generated documents, mirroring how `document.md`/`.docx`/`.pdf` already
work.

## 1. Speaker label normalization

Raw diarization engines emit inconsistent speaker labels (pyannote:
`SPEAKER_00`/`SPEAKER_01`, AssemblyAI: `A`/`B`). Normalize once, right after
`transcribe_diarize()` returns in `pipeline.py:77`, into clean, consistent
`Speaker 1`, `Speaker 2`, ... ordered by first appearance in the transcript
-- engine-agnostic, and a much better default label to show a new user
before they've assigned real names. Mutate each segment's `"speaker"` field
in place; capture the ordered unique list (`["Speaker 1", "Speaker 2", ...]`)
for `transcript.json`. Scope this to the `is_audio_job` branch only --
video's path is untouched.

## 2. Summary generation -- new function in `backend/app/stages/compose.py`

Add `generate_summary(segments, provider=None) -> str`, reusing this file's
existing machinery directly rather than duplicating it:
- `_get_client_and_fns(provider)` for client acquisition (ignore the two
  compose/title function slots it also returns).
- `_make_windows(segments)` / `_window_text(window)` for chunking -- same
  ~3500-word windows already used for video composition, so arbitrarily
  long audio (capped at 90 min today via `MAX_DURATION_SECONDS`) is handled
  the same proven way.
- New `SUMMARY_SYSTEM_PROMPT` constant: instruct the model to write a
  concise summary paragraph, and **explicitly refer to speakers using their
  exact given labels** (e.g. "Speaker 1") rather than paraphrasing them
  away -- this is what makes speaker renames later a plain text
  substitution instead of a re-generation.
- Map-reduce for multi-window transcripts: summarize each window, then feed
  the concatenated partial summaries through one more summarization pass.
  Single window (the common case) just summarizes directly.
- Mirror `compose_document`'s dual anthropic/openai tool-call structure
  (`_compose_window_anthropic`/`_compose_window_openai` pattern) for a
  `{"summary": "..."}` structured-output schema, consistent with this
  file's existing style.

In `pipeline.py`'s `is_audio_job` branch: call `generate_summary(segments)`
only if `_llm_available()` (mirrors the existing video-path check exactly --
audio stays fully functional with zero LLM keys configured, summary is just
gracefully skipped). Wrap in try/except like the existing DOCX/PDF export
try/excepts (`pipeline.py:119-126`) -- a summary failure logs and skips the
section, never fails the job.

## 3. Document section changes (audio only)

`_verbatim_transcript_sections(segments)` gains an optional
`speaker_names: dict[str, str] | None = None` param, resolving each
segment's display name via `speaker_names.get(seg["speaker"], seg["speaker"])`
before formatting the `"**{name}** (timestamp): {text}"` paragraph line.

New small helper, `_build_audio_sections(segments, summary, speaker_names)`,
used both at initial job-run time and by the rename endpoint (section 5) so
the logic isn't duplicated:
- If `summary`: prepend a `{"heading": "Summary", "blocks": [{"type":
  "paragraph", "text": summary, ...}]}` section.
- Append `_verbatim_transcript_sections(segments, speaker_names)`.

## 4. Persist `transcript.json`

Right after `doc_dir.mkdir(...)` (`pipeline.py:111`), for audio jobs only,
write `doc_dir / "transcript.json"`:

```json
{
  "speakers": ["Speaker 1", "Speaker 2"],
  "speaker_names": {},
  "summary": "...",
  "segments": [{"speaker": "Speaker 1", "text": "...", "start_ts": 0.0, "end_ts": 5.2}]
}
```

`speaker_names` starts empty (raw labels shown until the user assigns real
names). This file lives in the same directory as `document.md` etc., so:
- It's automatically cleaned up by the existing retention job (which
  deletes the whole per-job output directory, not individual files -- no
  retention.py change needed).
- It's servable for free via the **existing** generic file endpoint
  `GET /api/documents/{job_id}/{file_path:path}` in
  `backend/app/routes/documents.py` -- no new download route needed,
  `.json` gets the correct `application/json` content type automatically
  via Starlette's `FileResponse` mimetype detection.

## 5. New endpoint: rename speakers + regenerate

New file `backend/app/routes/transcript.py`, registered in
`backend/app/main.py` next to the other routers.

```
POST /api/jobs/{job_id}/speakers
  body: { "speaker_names": { "Speaker 1": "Alex", "Speaker 2": "Jamie" } }
```

Flow:
1. `documents._owned_done_doc_dir(job_id, current_user)` for the standard
   ownership/status/retention guard (reuse, don't duplicate). Additionally
   404 if `job["job_type"] != "audio"` -- this feature is audio-only.
2. Read `transcript.json`; 404 if missing (pre-this-change job with no
   transcript file).
3. Validate submitted keys are a subset of the stored `speakers` list --
   reject unknown keys with 400.
4. Merge into the stored `speaker_names` (keyed by the stable normalized
   label, so re-renaming is always idempotent regardless of what the
   previous custom name was) and write `transcript.json` back.
5. Rebuild sections via `pipeline._build_audio_sections(segments, summary,
   speaker_names)` -- the summary text gets speaker names substituted via
   plain `str.replace()` per mapped entry (safe because labels are the
   normalized `"Speaker N"` form, not free text).
6. Re-render all three formats in place: `assemble.render_markdown/
   render_docx/render_pdf` overwriting `document.md/.docx/.pdf` in the same
   `doc_dir`, using the job's existing stored `title`.
7. This runs synchronously in the request handler, not queued to the
   worker -- all three renders are local (reportlab/python-docx, no
   external API calls) and fast; no async job needed for a rename.
8. Return the updated transcript JSON so the frontend can refresh its view
   immediately without a second fetch.

## 6. `status.py`: expose the transcript URL

In `build_job_response` (`backend/app/routes/status.py`), add
`document_transcript_json_url` following the exact same conditional-
existence-check pattern already used for `document_docx_url`/
`document_pdf_url` (check `(doc_dir / "transcript.json").exists()`).

## 7. Frontend

**`frontend/lib/jobs.ts`**: add `document_transcript_json_url?: string` to
`Job`. New exported types:
```ts
export type TranscriptSegment = { speaker: string; text: string; start_ts: number; end_ts: number };
export type TranscriptData = {
  speakers: string[];
  speaker_names: Record<string, string>;
  summary: string;
  segments: TranscriptSegment[];
};
```
Plus a `formatTimestamp(seconds: number): string` helper mirroring
`pipeline.py`'s `_format_timestamp` (h:mm:ss / m:ss).

**New `frontend/components/TranscriptViewer.tsx`**: fetches
`job.document_transcript_json_url` via `apiFetch` on mount. Renders:
- Summary card at the top (if `data.summary` is non-empty).
- Speaker renaming: a text input per entry in `data.speakers`, pre-filled
  with `data.speaker_names[speaker] ?? speaker`, local state tracked as
  edits happen, a "Save names" button posting the full mapping to
  `POST /api/jobs/{job_id}/speakers`, refetching transcript data on success.
- Segment list grouped by speaker turn (already merged upstream by
  `_merge_fragments`), each row showing a colored avatar-initial bubble
  (color picked from a small fixed palette, indexed by
  `data.speakers.indexOf(segment.speaker)` so it's stable), the resolved
  display name, formatted timestamp, and text.
- A talk-time breakdown bar: sum `end_ts - start_ts` per speaker from
  `data.segments` (computed client-side, no new backend data needed),
  render as a small horizontal stacked bar with the same per-speaker
  colors and percentages -- a free, high-value "who talked how much"
  signal.

**Wire into `frontend/app/(app)/dashboard/jobs/[id]/page.tsx`**: below the
existing download-buttons block, when `job.job_type === "audio" &&
job.status === "done" && job.document_transcript_json_url`, render
`<TranscriptViewer jobId={job.job_id} transcriptUrl={job.document_transcript_json_url} />`.

**Downloads row**: add `transcript.json` as its own download entry (icon +
label, matching the existing Markdown/Word/PDF/Drive row) on both
`DocumentCard.tsx` and the job detail page -- verify at implementation time
whether lucide ships `FileJson`; fall back to reusing `FileCode` if not.

**`backend/app/routes/drive.py`**: add `transcript.json` to the existing
existence-checked upload list (one line, same pattern as the docx/pdf
checks already there) -- Save-to-Drive should include it for audio jobs.

## Making it more intuitive -- included above vs. deferred

**Included in this plan** (cheap, high-value, already folded into the
design above):
- Engine-agnostic, clean `Speaker 1`/`Speaker 2` labels instead of raw
  engine output.
- Inline, direct-manipulation renaming right where the transcript is read
  (not a buried settings form elsewhere).
- Colored speaker avatars for instant visual "who's talking" recognition.
- Talk-time breakdown bar -- free insight computed from data already
  fetched.
- `transcript.json` also offered as a plain download and included in
  Save-to-Drive, for programmatic/API-key users.

**Deferred (flagged, not in scope for this plan)**:
- Cross-job speaker memory (recognizing "this is the same person as last
  week's recording" automatically) -- would need voice-embedding/speaker-
  fingerprinting infrastructure the current diarization models don't
  provide. Real feature, real complexity, separate project.
- A dedicated full-page transcript view instead of inline-on-job-detail --
  easy follow-up if transcripts prove too long for the inline layout; not
  worth building preemptively.
- Playback-synced transcript (audio player + click-a-line-to-seek) -- would
  require embedding an audio player tied to timestamps; a natural v2, not
  needed for the core "who said what" viewer.

## Verification (manual end-to-end)

1. Upload an audio file with 2+ distinct speakers via the existing
   `/dashboard` upload flow (still auto-routes by extension to
   `/api/transcribe_audio` -- unchanged).
2. Once `done`, confirm on the job detail page: a Summary section appears
   (if an LLM key is configured), the transcript is grouped by speaker with
   colored bubbles, and a talk-time bar is shown.
3. Download `document.md`/`.docx`/`.pdf` and confirm the Summary section
   and `**Speaker 1**`-style labels appear correctly in all three formats.
4. Download/open `transcript.json` directly and confirm the shape (speakers
   list, empty `speaker_names`, summary, full segment list).
5. Rename a speaker via the UI, save, and confirm: the transcript view
   updates immediately, and re-downloading `document.md`/`.docx`/`.pdf`
   shows the new name in place of "Speaker 1" everywhere (including inside
   the summary paragraph, if it mentioned that speaker).
6. Confirm renaming does not change `billed_cents`, does not create a new
   job row, and completes near-instantly (no worker/queue involvement).
7. Test with **no LLM key configured**: confirm the job still completes
   successfully with no Summary section, everything else (JSON, speaker
   renaming, transcript viewer) works exactly the same.
8. Test Save-to-Drive on an audio job: confirm the uploaded Drive folder
   now also contains `transcript.json`.
9. Confirm a **video** job is completely unaffected -- no transcript.json,
   no viewer, no speaker endpoint access (should 404 job_type check).
10. Confirm an **old** audio job from before this change (no
    `transcript.json` on disk) degrades gracefully: `document_transcript_json_url`
    is absent, the viewer section simply doesn't render, no errors.

### Critical files
- `backend/app/pipeline.py` -- label normalization, summary call, section
  building, `transcript.json` write, in the `is_audio_job` branch
- `backend/app/stages/compose.py` -- new `generate_summary()`, reusing
  `_get_client_and_fns`/`_make_windows`/`_window_text`
- `backend/app/routes/transcript.py` -- new, `POST /api/jobs/{job_id}/speakers`
- `backend/app/routes/documents.py` -- reuse `_owned_done_doc_dir`; no
  changes needed, `transcript.json` rides the existing generic file route
- `backend/app/routes/status.py` -- add `document_transcript_json_url`
- `backend/app/routes/drive.py` -- add `transcript.json` to upload list
- `backend/app/billing.py` -- reword the `SECONDS_PER_CENT_AUDIO` comment
- `backend/app/main.py` -- register the new router
- `frontend/lib/jobs.ts` -- new types + `formatTimestamp`
- `frontend/components/TranscriptViewer.tsx` -- new
- `frontend/app/(app)/dashboard/jobs/[id]/page.tsx` -- wire in the viewer
- `frontend/components/DocumentCard.tsx`, job detail page -- transcript.json
  download entry
