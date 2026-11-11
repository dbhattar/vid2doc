# Video workflow: one initial set of outputs, then derive more documents

## Context
Today a video upload starts with "What do you want to make?" (full document, notes, study guide, research) and the job produces exactly that one thing. You want a different flow: every video first produces the **initial set** (transcript, images, formatted document), and only once that exists can the user generate other documents from it. Decisions from you:
- **Images:** keep the "Extract frames" checkbox (skipping it still gives the $0.40/h transcript-only price, and then the initial set has no images).
- **Derived pricing:** free for now. Per the option text I chose, **notes and study guide are free; research is still charged** at its current rate ($2.00/h of video length) because it makes paid web-search calls. Tell me if research should be free too.

## Design

### Model: a derived document is a child job
A derived document is a normal `jobs` row with a new `parent_job_id` pointing at the video job it came from. This reuses everything the pipeline already does for a job (worker queue, progress stages, failure + refund, email on done, cancel, delete, retention, the research topic-review pause) instead of rebuilding it in a new table.

- `jobs.parent_job_id` (nullable, indexed, FK to `jobs.id`), migration **`0041`** from `0040`. (The stashed private-storage migration must then be renumbered to `0042`.)
- A child has `source_path=None`, `source_url=None`, `extract_frames=False`, the parent's `duration_seconds`, `job_type="video"`, `transformation` = notes | study_guide | research.
- Creating one writes `<OUTPUT_DIR>/<child>/precomputed_segments.json` from the parent's `transcript.json`. The worker already short-circuits transcription on that file (`pipeline._transcribe_segments`), and `run_job` already goes `_download_if_needed` (no-op without a source) -> `not extract_frames` -> `_compose_and_finalize` -> `transform.run`. So the pipeline itself needs no new branch.
- Children are hidden from the default job lists (`jobs.list_jobs_for_user` / `count_jobs_for_user` get `parent_job_id IS NULL`) so the dashboard, `/documents` and the Video page keep showing one row per upload. They show on the parent's page instead.

### New endpoints (`routes/jobs.py` or a new `routes/derived.py`)
- `POST /api/jobs/{id}/derive` `{transformation, review_topics?}`: parent must be the caller's, `job_type=video`, `transformation=document`, `status=done`, not retention-expired, with a readable `transcript.json` (via `archive_access.ensure_local` so archived jobs work). Rejects a type that already has a non-failed child (no accidental double-charge). Charges (research only) with `billing.charge_for_job` as `convert_to_doc` does, creates the child, returns its job id.
- `GET /api/jobs/{id}/derived`: the parent's children (type, status, progress, job id) for the "More documents" panel.
- `GET /api/jobs/{id}/images`: lists `document/images/*` with URLs (served by the existing `documents.get_document_file`), for the Images tab.
- `GET /api/documents/{id}/transcript.txt`: plain-text transcript (time, speaker, text) rendered on the fly from `transcript.json`, next to the existing JSON download.
- `routes/jobs.py` `retry_job`: a failed child is re-derived from its parent instead of demanding a source file.

### Billing (`billing.py`)
`billing_type_for` is unchanged; add one rule where `derive` creates the child: notes/study_guide `billed_cents=0`, research `charge_for_job(..., job_type="research")`. The pipeline's failure refund already refunds `billed_cents`, so a failed research child is refunded with no new code.

### Submit side: drop the up-front choice
- `routes/convert.py` and `routes/youtube.py` stop requiring `transformation`; the field stays accepted (default `document`) so API clients keep working, and `validate_options` still guards it. The UI always sends `document`.
- `make_public` stays on the initial document job; derived children are never public (`public_jobs` already requires `transformation == "document"`).

### Initial set made first-class
- **Transcript:** video `transcript.json` is written with raw engine labels (`SPEAKER_00`, `A`). Normalize speaker labels on the stored copy only (`pipeline._normalize_speaker_labels`, as the audio path does) so the viewer reads "Speaker 1". Not applied to the segments the document is composed from.
- **Images:** the `images/` folder and `bundle.zip` already exist; add the listing endpoint above and an "images only" zip download.
- **Document:** unchanged (`document.md/.docx/.pdf`, summary section, frame review pause).

### Frontend
- **`app/(app)/dashboard/video/page.tsx`:** remove the "What do you want to make?" fieldset, `OutputExamplePreview`, the research topic-review checkbox, and the per-transformation cost lines; keep the Extract-frames checkbox and the "$1.00/h with visuals / $0.40/h transcript-only" estimate (`estimatedCostCents` loses its transformation branches). Always send `transformation=document`.
- **`app/(app)/dashboard/jobs/[id]/page.tsx`:** for a finished video job show tabs: **Document** (today's preview), **Transcript** (read-only viewer + JSON/TXT downloads), **Images** (gallery + zip), **More documents** (cards for Notes, Study guide, Research with a Create button, price note, and the status/open link of any existing child; research offers the topic-review checkbox). Reuse `DocumentPreview`; the existing `TranscriptViewer` is audio-specific (speaker editing endpoints are audio-only), so add a `readOnly` mode to it rather than a new component.
- A child job's own page keeps working as today (it is just a job), with a "From <parent title>" back-link.
- **`lib/jobs.ts`:** `parent_job_id` on `Job`; `lib/jobStages.ts` unchanged.
- Marketing: `TransformationsSection.astro` and FAQ copy that describe choosing a format up front are reworded to "start with the document, then make notes, a study guide or research from it". Copy only.

### Compatibility and limits
- Existing jobs with `transformation != document` stay valid and display as before.
- Deriving needs the parent's `transcript.json`, which retention sweeps after 7 days (archived showcase/chat jobs are rebuilt from S3). After that the More-documents tab says so. Persisting transcripts longer is possible later but out of scope.
- Audio jobs and live recordings are untouched. Offering derived documents on them is a natural follow-up.

## Critical files
`backend/app/models.py`, `backend/alembic/versions/0041_*.py`, `backend/app/jobs.py`, `backend/app/routes/{convert,youtube,jobs,documents,status}.py` (+ new derive routes), `backend/app/pipeline.py` (label normalization only), `backend/app/stages/transform.py` (`validate_options`), `frontend/app/(app)/dashboard/{video,jobs/[id]}/page.tsx`, `frontend/components/TranscriptViewer.tsx`, `frontend/lib/jobs.ts`, `backend/README.md` and `marketing/src/components/TransformationsSection.astro`.

## Verification
- Backend has no test suite: run checks in the compose `worker` container with a fake `transform._call_json` and fake billing wallet, calling per-job functions only (no global sweeps, per the earlier incident). Cases: derive creates a child with `parent_job_id`, `billed_cents=0` (notes) and a research charge; a second derive of the same type is rejected; a not-done/foreign/expired parent is rejected; the child worker run produces `document.md` from the parent's transcript without transcription; a failed research child is refunded; `list_jobs_for_user` hides children; retry of a failed child re-derives; `transcript.txt` and `images` listing return the right content.
- Migration: `alembic upgrade head` on the dev DB and a clean DB.
- Frontend: `npx tsc --noEmit`, `npm run lint`, `npm run build`, then a browser pass: upload with and without frames, open the tabs, create notes, watch the child finish, create research with and without topic review.
- Not verifiable here: real LLM/web-search output quality and a real wallet charge against Stripe.
- After approval, save this plan to `plan/video-derived-documents-plan.md` per AGENTS.md.
