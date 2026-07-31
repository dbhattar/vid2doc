# Frame review step for video jobs + a document rendering redesign

## Context

Today, `backend/app/pipeline.py: run_job` processes a video fully automatically: extract audio →
transcribe → extract frames → filter → classify (vision LLM decides slide/diagram/table/filler) →
compose the document → render. There is no pause point anywhere — whatever the classifier picks is
what ends up in the document, sight unseen.

The user wants a human-in-the-loop step inserted after frames are classified but before the
document is composed: a dedicated review UI showing every candidate frame (all included by
default), letting the user skip ones they don't want, edit captions, and export already-detected
tables as standalone markdown. Per user decision, this first pass is **video-only** (audio has no
frames), does **not** add new paid on-demand extraction (only re-exporting tables the classifier
already found, which costs nothing extra), and an abandoned review gets swept by the existing
7-day retention job, same as a finished document.

The good news: there's already a working precedent for exactly this shape of problem — audio jobs
persist a `transcript.json` specifically so a user can rename speakers *after* the job is "done"
and get a cheap re-render (`routes/transcript.py: set_speaker_names`) without re-running
transcription. This plan applies the same pattern to video, just with the pause happening *before*
the job reaches "done" instead of after.

Separately, the user also wants the exported **PDF and Word documents redesigned** — today's
`assemble.render_docx`/`render_pdf` (`backend/app/stages/assemble.py`) use python-docx's/reportlab's
bare default styling: no brand fonts, a hardcoded arbitrary purple (`#6d5ef8`) table header
unrelated to any brand color, fixed-width images with no height cap, no cover page, no page
numbers, no table of contents. Per the user's decision this becomes a **full report treatment**:
real brand fonts and colors, a title/cover page, running header/footer with page numbers, and an
auto-generated table of contents. `render_markdown` is explicitly unchanged ("Markdown is okay").

## Backend: pipeline split + new "awaiting_review" status

**`status` is a free-text column already** (`backend/app/models.py`), not an enum — no migration
needed to add a new value. Same for `progress_stage`. The design uses both:

1. **`run_job` (`backend/app/pipeline.py`)** — for video jobs, stops right after
   `classify.classify_frames(candidates)` instead of immediately calling `compose_document`. It
   writes a new file, `{OUTPUT_DIR}/{job_id}/review.json`:
   ```json
   {
     "segments": [...],
     "items": [
       {"id": 1, "kind": "image", "timestamp": 12.4, "content_type": "slide", "caption": "...", "path": "...", "included": true},
       {"id": 2, "kind": "table", "timestamp": 30.1, "caption": "...", "headers": [...], "rows": [...], "path": "...", "included": true}
     ]
   }
   ```
   (`images_meta`/`tables_meta` unified into one `items` list, each tagged `kind` and defaulted
   `included: true` — this is exactly what the review grid renders and what compose consumes back
   after filtering.) Then `jobs.update_job(job_id, status="awaiting_review", progress_stage="awaiting_review")`
   and returns.

   **Skip review entirely** (unchanged current behavior) when there's nothing to review: audio
   jobs, no LLM configured (`_llm_available()` false — today's fallback-transcript path), or zero
   classified candidates. Only pause when there are actual items to show.

2. **`classify.classify_frames`** (`backend/app/stages/classify.py`) — small fix: table items
   currently drop `path` (the source frame image is discarded once classified as a table). Add
   `"path": frame["path"]` to the table dict too, so *any* reviewed frame's image can be viewed/saved
   regardless of classification kind (needed for "save frames individually" to work uniformly).

3. **New `resume_after_review(job)` in `pipeline.py`** — reads `review.json`, splits `items` back
   into `images_meta`/`tables_meta` filtered to `included: true` (using each item's — possibly
   user-edited — `caption`), then runs the exact same tail `run_job` already has today:
   `compose.compose_document` → `compose.generate_title` → `assemble.render_markdown/docx/pdf` →
   `status="done"`. Extract that tail into a small shared helper (e.g. `_finalize_document(...)`)
   so both the "review skipped" fast path and `resume_after_review` call the same code, not two
   copies.

4. **Resume trigger, reusing the existing worker/queue — no new polling path.** When the user
   submits their review, the route sets `status="queued"` again (not `"processing"` — the worker's
   `claim_next_queued_job()` only claims `queued` rows) with `progress_stage="resuming_after_review"`.
   `run_job`'s very first line becomes: `if job.get("progress_stage") == "resuming_after_review":
   return resume_after_review(job)`. The worker picks it up exactly like any other queued job; no
   changes to `worker.py` or `claim_next_queued_job` needed.

5. **`routes/jobs.py: delete_job`** — small addition: allow deleting an `awaiting_review` job too
   (currently only `failed`), so a user who changes their mind isn't stuck waiting on the 7-day
   sweep below.

## Backend: retention sweep also covers abandoned reviews

`backend/app/jobs.py: list_jobs_eligible_for_retention` currently only selects `status == "done"`
jobs older than `RETENTION_DAYS` (7). Widen the filter to `status IN ("done", "awaiting_review")`.
`retention.py`'s sweep then needs to branch on which one it found:

- **`done`** — unchanged: `shutil.rmtree` the output/upload dirs, null `document_path`, set
  `deleted_at`.
- **`awaiting_review`** — same disk cleanup (`output/{job_id}` — including `review.json` and
  `frames_raw/` — and the upload dir), but since no usable document was ever produced, transition
  the job to `status="failed"`, `error_message="Review wasn't completed within 7 days"`, set
  `deleted_at`, and **refund the original charge** via the exact same `billing.refund_job_charge`
  already used for pipeline failures — consistent with "no usable output → refunded," rather than
  leaving a job stuck in a state whose thumbnails now 404.

## Backend: new routes (new file `backend/app/routes/review.py`)

- **`GET /api/jobs/{job_id}/review`** — owned-job check (same pattern as `routes/documents.py`),
  404 unless `status == "awaiting_review"`, returns `review.json`'s `items` (without local `path`s
  — those get resolved via the frame-image route below, never leaked as raw filesystem paths).
- **`GET /api/jobs/{job_id}/review/frames/{item_id}`** — serves the actual JPEG for one item
  (`FileResponse`, resolving `path` from `review.json` by id). This one route covers both the
  review grid's thumbnails *and* "save this frame individually" (point 3) — a direct authenticated
  download of the same URL.
- **`POST /api/jobs/{job_id}/review`** — body `{"items": [{"id": 1, "included": true, "caption": "..."}, ...]}`.
  404 unless `status == "awaiting_review"`; merges `included`/`caption` back into `review.json`,
  then sets `status="queued"`, `progress_stage="resuming_after_review"` (step 4 above). Returns the
  updated job so the frontend can resume polling.
- **`GET /api/jobs/{job_id}/review/tables/{item_id}/markdown`** — for `kind == "table"` items only:
  renders just that table's `headers`/`rows` as a markdown table (extract the existing table-block
  formatting logic already in `assemble.render_markdown` into a small shared
  `assemble.render_table_markdown(table) -> str` helper so this route and the full-document
  renderer share one implementation) and returns it as a downloadable `.md` file. No LLM call, no
  new charge — this is a pure export of data already extracted during the normal pipeline run.

## Frontend

1. **`lib/jobs.ts`** — widen `JobStatus` to include `"awaiting_review"`.
2. **`components/StatusBadge.tsx`** — add a style/label for it (e.g. `text-status-info`, label
   "Needs review").
3. **Dashboard (`app/(app)/dashboard/page.tsx`)** — jobs in `awaiting_review` show a "Review
   frames →" link to the job detail page, alongside the existing in-progress list (same place
   failed jobs currently show Retry/Delete).
4. **Job detail page (`app/(app)/dashboard/jobs/[id]/page.tsx`)** — same route as today (no new
   URL), add a new conditional branch: when `job.status === "awaiting_review"`, render a new
   `FrameReviewPanel` component instead of the normal status/download panel — this keeps one
   bookmarkable URL for the whole job lifecycle while still being a distinct, dedicated UI, the
   same way `TranscriptViewer` is already conditionally shown inline on this same page today.
5. **New `components/FrameReviewPanel.tsx`**:
   - Fetches `GET /api/jobs/{id}/review` on mount.
   - Renders a grid of cards (reusing `Card`), each with: thumbnail, timestamp, an editable caption
     input (matches the `TranscriptViewer` speaker-name-input pattern), an include/exclude checkbox
     (checked by default), and for `kind === "table"` items, a "Save as Markdown" button hitting the
     table-export route directly (via `downloadAuthenticated`, same pattern already used for
     document downloads).
   - **Group/filter controls** (per your decision): a row of filter chips derived from the unique
     `content_type`s present (Slides / Diagrams / Tables / ... / All) that filter the grid
     client-side — no new endpoint needed, this is pure client-side filtering over the one
     `GET .../review` payload already fetched.
   - One batch "Continue" button at the bottom (matching `TranscriptViewer`'s single "Save names"
     action rather than per-field autosave) that `POST`s the full `items` array (included flags +
     any edited captions) and then resumes the existing job-detail polling loop already on this
     page, which will show the normal processing view again until `status` becomes `"done"`.
6. **New `components/AuthenticatedImage.tsx`** — a small wrapper needed because thumbnails must go
   through the same Bearer-token auth as everything else in this app (`lib/api.ts`'s
   `apiFetch`/`downloadAuthenticated` — there is no cookie-based session, so a plain `<img src=...>`
   can't authenticate). Fetches the frame URL as a blob on mount (same technique
   `downloadAuthenticated` already uses), creates an object URL, revokes it on unmount, and renders
   an `<img>` once loaded with a simple loading placeholder in the meantime.

## Deferred (explicitly out of scope for this pass, per your decisions)

- Paid on-demand table extraction from frames the classifier *didn't* flag as tables — needs its
  own per-request charge/pricing design later.
- Letting users pull in an additional raw frame the algorithm didn't surface as a candidate.
- Any auto-timeout/auto-proceed for an abandoned review.
- An equivalent review step for audio jobs (no frames exist there; the closest analog would be
  reviewing/editing transcript segments or the summary pre-finalization, a separate future design).

## Document rendering redesign (`backend/app/stages/assemble.py`)

Brand values are hardcoded directly in Python (there's no CSS here) — the same hex values as the
web brand's light-mode tokens (`marketing/src/styles/tokens.css`): ink `#14120f`, accent `#c81e3a`,
line `#dedbd4`, a paper-shade `#f2f0ec` for subtle backgrounds. Exported documents always use the
light palette — there's no "dark mode" concept for something meant to be printed/read as a
document.

**Fonts**: brand personality goes on headings/captions/labels only, exactly like the web brand
does (body copy stays a plain, always-available font — Helvetica in PDF, Word's default in DOCX —
so dense reading text isn't fighting a display face). Reuse the same Fraunces (900 + 600 + 500
italic) and IBM Plex Mono (400/500) `.ttf` files already fetched during the marketing site's design
pass — copy them into a new `backend/app/assets/fonts/` (plus the Google Fonts `OFL.txt` license
file alongside, standard practice for bundling OFL-licensed fonts) instead of re-downloading.
- **PDF**: real font embedding via `reportlab.pdfbase.pdfmetrics.registerFont(TTFont(...))` —
  title/headings in Fraunces, captions and the footer/page-number in IBM Plex Mono, body text
  stays Helvetica.
- **DOCX**: python-docx doesn't support true font embedding through its high-level API (would need
  hand-rolling raw OOXML font-table parts — disproportionate effort here); set the font *name*
  (Fraunces/IBM Plex Mono) on heading/caption styles instead, best-effort — Word substitutes a
  fallback on machines that don't have them installed, which is the standard/accepted tradeoff for
  generated Word docs.

**Cover page**: both renderers gain a first page before section 1 — large title, "Generated by
Framewrite" + generation date as a subtitle, then a page break (`doc.add_page_break()` in
python-docx; a `PageBreak()` flowable in reportlab).

**Header/footer + page numbers**:
- PDF: switch from a bare `SimpleDocTemplate(...).build(story)` call to a canvas callback
  (`onFirstPage`/`onLaterPages`) that draws a page number (and optionally the document title) in
  Plex Mono at the bottom of every page.
- DOCX: insert a real `PAGE` field into the footer via the well-established python-docx raw-oxml
  recipe for field codes (there's no high-level API for this, but it's a standard, documented
  pattern, not exotic).

**Table of contents** (only when a document has more than one section — skip for simple
single-section documents where a TOC would be redundant):
- DOCX: insert a real, clickable `TOC` field (`{ TOC \o "1-3" \h \z \u }`) via the same raw-oxml
  field-code technique as the page number — Word auto-populates/updates it from the heading styles
  already in use.
- PDF: reportlab's `BaseDocTemplate.multiBuild()` is designed for exactly this — a two-pass build
  where a `TableOfContents()` flowable resolves real page numbers against heading flowables
  registered via an `afterFlowable` hook. This is a documented reportlab pattern, not a hack.

**Tables**: replace the hardcoded purple header (both renderers) with an ink-background/paper-text
header row (mirroring the same high-contrast pairing the brand's primary buttons already use),
plain paper body rows, thin line-colored grid borders — no more arbitrary, brand-unrelated purple.

**Images**: cap by max width *and* max height (not just width) so a tall portrait screenshot can't
run off the page, and center on the page. Kept intentionally simple — no decorative image borders/
frames, to keep the polish budget on fonts/colors/cover/TOC/headers, which matter more for a report
that gets read or handed to someone else.

**Sequencing note**: this touches `assemble.py`'s `render_docx`/`render_pdf` fairly deeply, while
the frame-review feature above only needs a small, separate `render_table_markdown` extraction from
`render_markdown`. The two can be built/reviewed as genuinely separate phases even though they land
in the same file — do the table-markdown extraction first (small, low-risk), then the document
redesign (larger, self-contained), so a regression in one is easy to isolate from the other.

## Files touched

- `backend/app/pipeline.py` — split `run_job` (pause after classify), new `resume_after_review`,
  shared `_finalize_document` helper.
- `backend/app/stages/classify.py` — keep `path` on table items too.
- `backend/app/stages/assemble.py` — extract `render_table_markdown(table)` helper; redesign
  `render_docx`/`render_pdf` (fonts, colors, cover page, header/footer + page numbers, TOC, table
  styling, image sizing).
- `backend/app/assets/fonts/` (new) — Fraunces + IBM Plex Mono `.ttf` files + `OFL.txt`, reused from
  the marketing site's design pass rather than re-fetched.
- `backend/app/routes/review.py` (new) — the four routes above.
- `backend/app/routes/jobs.py` — allow `delete_job` on `awaiting_review` too.
- `backend/app/main.py` — register the new router (check existing router registration pattern).
- `backend/app/jobs.py` — widen `list_jobs_eligible_for_retention` to include `awaiting_review`.
- `backend/retention.py` — branch cleanup: `done` unchanged; `awaiting_review` → clean disk, mark
  `failed` with a clear message, and refund.
- `frontend/lib/jobs.ts` — widen `JobStatus`.
- `frontend/components/StatusBadge.tsx` — new status style.
- `frontend/components/FrameReviewPanel.tsx` (new), `frontend/components/AuthenticatedImage.tsx` (new).
- `frontend/app/(app)/dashboard/page.tsx` — "Review frames →" affordance.
- `frontend/app/(app)/dashboard/jobs/[id]/page.tsx` — render `FrameReviewPanel` when awaiting review.

## Verification

1. Submit a real video with a mix of slides, talking-head footage, and at least one frame with a
   table; confirm the job reaches `awaiting_review` (not `done`) and `review.json` contains the
   expected `items`, each with a real `path` that resolves.
2. Load the job detail page while `awaiting_review` — confirm the grid renders all items
   pre-checked, thumbnails load (via the authenticated frame route), and the content-type filter
   chips correctly narrow the grid.
3. Uncheck a couple of frames, edit a caption, click "Save as Markdown" on a table item and confirm
   the downloaded file's content matches that table's headers/rows.
4. Click Continue — confirm the job goes back to `processing` (`resuming_after_review` →
   `composing_document` → `rendering_document`) and finishes as `done`, with the final document
   containing only the kept frames and the edited caption text.
5. Confirm a job sitting in `awaiting_review` (never opened/submitted) can still be deleted from
   the dashboard as a cleanup path, per the `delete_job` change.
6. Confirm audio jobs and (if you can toggle `LLM_PROVIDER`/unset the API key) no-LLM video jobs
   are unaffected — they should go straight to `done` exactly as they do today, never touching
   `awaiting_review`.
7. Run `retention.py` against a job whose `created_at` is manually backdated past 7 days while
   `awaiting_review`: confirm its output/upload dirs are removed, it flips to `failed` with the new
   error message, and the original charge is refunded (check the wallet ledger for the matching
   `usage_refund` entry).
8. Generate a multi-section document's PDF and DOCX and confirm: a cover page renders before
   section 1; headings/captions use Fraunces/Plex Mono (PDF: visually embedded; DOCX: font name set
   even if substituted); page numbers appear on every page; a table of contents appears and its
   entries/page numbers (PDF) or field (DOCX, after "Update Field") are correct; table headers use
   ink/paper instead of the old purple; a tall portrait image doesn't overflow the page. Also
   generate a single-section document and confirm the TOC is correctly omitted.
