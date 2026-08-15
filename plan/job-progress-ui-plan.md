# Engaging Job-Progress UI

## Context

Today, a running job shows nothing but a single plain-text label —
`StatusBadge.tsx` renders `job.progress_stage.replaceAll("_", " ")` in small
mono text, with no visual sense of how far along the job is or that anything
is actively happening. This is confusing across all three job types (video,
audio, video_gen), each of which actually runs through a known, ordered
sequence of `progress_stage` values — we're just not using that structure.
This plan replaces the flat label with a compact segmented progress bar for
list views and a full animated vertical stepper for the job detail page,
both driven by real per-job-type stage data, plus light personality (flavor
text) and a live elapsed-time ticker to make waiting feel less inert.

**Decisions locked in during brainstorming:**
- Both a compact segmented bar (list views) and a full vertical
  stepper/checklist (detail page), same underlying stage data.
- Include short, personable flavor text per stage — not purely dry labels.

## Stage sequences (verified directly against `backend/app/pipeline.py`)

- **video**: `downloading`\* → `extracting_frames` → `filtering_frames` →
  `classifying_frames`\*\* → `captioning_frames`\*\* → `awaiting_review` →
  `extracting_audio` → `transcribing` → `composing_document` →
  `rendering_document`
- **audio**: `extracting_audio` → `transcribing` → `summarizing`\*\* →
  `rendering_document`
- **video_gen**: `extracting_audio` → `transcribing` → `segmenting_scenes` →
  `generating_headlines` → `fetching_stock_media` → `awaiting_scene_review`
  → `rendering_scenes` → `assembling_video`

  \* YouTube-imported video jobs only. \*\* Only when an LLM/classifier is
  configured or there's something to classify/summarize.

**Known, accepted simplification**: the frontend only ever sees the
*current* `progress_stage` via polling — there's no stage-history log. So a
skipped conditional stage (e.g. no LLM configured) will just flash past as
instantly-"done" once the job moves beyond it, rather than being detected as
skipped. This is fine and not worth solving further.

## 1. Stage metadata — new `frontend/lib/jobStages.ts`

A new file (not an extension of `jobs.ts`, which is generic job
shape/formatting, not curated pipeline copy). Exports:

```ts
type StageStatus = "done" | "current" | "awaiting-input" | "failed" | "pending";
type StageDef = { key: string; label: string; flavor: string; awaitingInput?: boolean };

const VIDEO_STAGES: StageDef[] = [ /* the 10 stages above, in order */ ];
const AUDIO_STAGES: StageDef[] = [ /* the 4 stages above */ ];
const VIDEO_GEN_STAGES: StageDef[] = [ /* the 8 stages above */ ];

function getStagesForJobType(jobType: JobType): StageDef[]
function getStageStatuses(job: Job): { stage: StageDef; status: StageStatus }[]
```

- `awaiting_review`/`awaiting_scene_review` are real entries in the array
  (`awaitingInput: true`) — one uniform index lookup handles every status,
  only the *rendering* of that row is special-cased.
- `done` is **not** an array entry — `job.status === "done"` is its own
  branch (treat as "past the end, everything checked"), avoiding a
  redundant final "Done" row on a page that already has a full done-state UI.
- `queued` (and the transient `resuming_after_review`/
  `resuming_after_scene_review` markers) naturally fall through to "no
  match → every row pending, nothing current" — no dedicated queued stage
  needed.
- `getStageStatuses` does all done/current/awaiting-input/failed/pending
  branching once, so `ProgressBar` and `ProgressStepper` only render, never
  re-derive status logic.

**Flavor text** (confident/dry tone, matching existing marketing copy —
not loading-screen humor): one line per stage, e.g. `transcribing` →
"Listening closely and writing down every word.", `awaiting_scene_review` →
"Your call — review the scenes and swap in better footage." Full copy list
for all 22 stage entries to be written directly into `jobStages.ts` during
implementation, following this tone.

## 2. `ProgressBar` — new `frontend/components/ProgressBar.tsx`

Compact, for `JobRow` and any other list view. `{ job, className }` props,
same convention as `StatusBadge`. Renders a flex row of thin, sharp-edged
segments (no rounded corners — matches the brand's blocky `border-2`
aesthetic, no pill styling anywhere else in the app): `bg-line` for
pending, `bg-status-warning` for done-so-far and current, current segment
additionally gets a `stage-pulse` CSS class (new keyframe, see §5). Current
stage's label shown alongside using `StatusBadge`'s exact text classes, so
it reads as "the same status text, now paired with a bar." Flavor text
surfaces as a native `title` tooltip on the bar (zero layout cost) rather
than a second visible line — a dense list row shouldn't grow a permanent
line of prose per processing job; the full always-visible flavor treatment
lives in `ProgressStepper` instead.

## 3. `ProgressStepper` — new `frontend/components/ProgressStepper.tsx`

Full vertical `<ol>` for the job detail page, one `<li>` per stage:

- **done**: checkmark (new `CheckIcon` in `icons.tsx`, wrapping lucide's
  `Check` — following the file's one-wrapper-per-icon convention).
- **current**: small square indicator (deliberately square, not circular,
  to match the brand's no-rounded-pill aesthetic) with the `stage-pulse`
  animation, flavor text shown beneath with a fade-in, plus the live
  elapsed ticker (§4) next to the label, e.g. "Transcribing · 0:42".
- **awaiting-input**: explicitly **not** animated (a pulse means "system is
  working," which is wrong when it's actually idle waiting on the user) —
  accent-colored row (`border-accent`/`bg-accent-soft`) instead, label
  reads as an instruction ("Awaiting your review"). No extra CTA needed
  inside the stepper — `FrameReviewPanel`/`SceneReviewPanel` already
  render immediately below on the page.
- **failed**: a new `AlertIcon` in `icons.tsx` (lucide's `CircleAlert` —
  not the existing `CloseIcon`, which wraps `X` and is semantically a
  "dismiss" icon, not an error one), tinted `text-status-error`, row using
  the same `--status-error-soft` token the page's existing error banner uses.
- **pending**: dim outlined square, muted (`text-ink-soft`) label, no
  flavor text.

## 4. Elapsed-time ticker — new `frontend/lib/useElapsedSeconds.ts`

```ts
function useElapsedSeconds(startedAt: string, active: boolean): number
```

Ticks via its own `setInterval` (confirmed `formatElapsed` in `jobs.ts`
can't be reused — it's an explicit one-shot `updated_at - created_at`
computation, not live). No new formatter needed either: the existing
`formatTimestamp(seconds)` in `jobs.ts` already does unrounded `m:ss`
formatting, exactly what a live ticker wants. Called as
`useElapsedSeconds(job.updated_at, job.status === "processing")` —
`updated_at` (not `created_at`) because `update_job()` refreshes it on
every stage transition, so this measures time-in-current-stage, not
whole-job age.

## 5. New CSS — `frontend/app/globals.css`

Two new `@keyframes`, both wrapped in
`@media (prefers-reduced-motion: no-preference)` (matching the marketing
site's existing pattern for `rec-pulse`):
- `stage-pulse` (opacity 1 → 0.45 → 1, ~1.6s ease-in-out infinite) — applied
  to the current bar segment / stepper indicator.
- `fade-in` (opacity 0 → 1, ~200ms ease-out) — applied to the flavor-text
  paragraph, which naturally remounts with new content on every stage
  change, so no manual `useEffect` toggle is needed to replay it.

## 6. Integration points

- **`frontend/components/JobRow.tsx`**: when `status === "processing"`,
  render `<ProgressBar job={job} className="w-32" />` instead of
  `<StatusBadge job={job} />`; every other status keeps `StatusBadge`
  unchanged (Retry/Delete/Review affordances are already gated on other
  statuses, no overlap).
- **`frontend/app/(app)/dashboard/jobs/[id]/page.tsx`**: remove the existing
  conditional "Stage" `<dl>` row (now redundant), add
  `{job.status !== "done" && <ProgressStepper job={job} className="mt-6" />}`
  right after the `<dl>` closes, before the failed-error paragraph. Not
  rendering it once `"done"` avoids a fully-checked 9-row list adding bulk
  to a page that already has a rich reward state (downloads/preview/share).
  `queued`/`awaiting_review`/`awaiting_scene_review`/`failed` all fall out
  of `getStageStatuses` automatically — no extra page-level branching.

## 7. Backend change — `backend/app/pipeline.py`

One-line fix in `run_job`'s except block (currently line 390):
```python
jobs.update_job(job_id, status="failed", progress_stage=None, error_message=str(e))
```
→ drop `progress_stage=None` so the last real stage survives the failure,
letting the stepper show which step it died on instead of a blank list.
**Verified safe**: `jobs.py`'s `update_job` is a plain per-kwarg `setattr`
loop (omitting the field just leaves the column untouched); every read site
(`routes/status.py`, `routes/trial.py`, `jobs.py::_job_to_dict`, and all
three frontend read sites) treats `progress_stage` as a plain
pass-through/truthy-check, never an `is None` special case. `retention.py`
has its own, unrelated `progress_stage=None` (line 71, for an
awaiting-review job whose 7-day window expired unused) — leave that one
alone, it's a different, already-well-explained scenario.

## Verification

- Run a real job of each type through the local dev stack
  (`./restart-containers.sh` from repo root) and watch both the dashboard
  list view (`ProgressBar`) and the job detail page (`ProgressStepper`)
  advance through real stages as the worker processes it.
- Confirm the `awaiting_review`/`awaiting_scene_review` row renders as a
  static, accent-colored "awaiting your review" state (not pulsing) and
  that the review panel still appears directly below it.
- Force a failure (e.g. an invalid API key mid-pipeline) and confirm the
  stepper shows completed stages checked, the actual failed stage flagged
  in red, and the rest pending — verifying the `pipeline.py` fix took effect.
- Check `prefers-reduced-motion: reduce` in devtools and confirm the pulse/
  fade animations are suppressed (elements should still render, just static).

### Critical files
- `frontend/lib/jobStages.ts`, `frontend/lib/useElapsedSeconds.ts` (new)
- `frontend/components/ProgressBar.tsx`, `frontend/components/ProgressStepper.tsx` (new)
- `frontend/components/icons.tsx` (add `CheckIcon`, `AlertIcon`)
- `frontend/components/JobRow.tsx`, `frontend/app/(app)/dashboard/jobs/[id]/page.tsx`
- `frontend/app/globals.css`
- `backend/app/pipeline.py`
