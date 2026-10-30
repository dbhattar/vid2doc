# Output previews, research topic review, and review-needed emails

Historical record of design intent -- the code and READMEs are authoritative.

## Goals
1. Let users see what Concise notes / Study guide / Deeper research produce before choosing one.
2. Add a user-interaction step before the paid web research of a research job.
3. Email the user whenever a job pauses waiting for their review.

## Decisions
- **Previews**: static, hand-written samples (no LLM cost, no backend), all from one imaginary source
  video so they're comparable. Shown under the option cards on the Video page
  (`frontend/lib/outputExamples.ts`, `components/OutputExamplePreview.tsx`) with a "See full example"
  expander, and as a "See an example" `<details>` on the homepage outputs cards. The full document gets
  no preview -- the homepage already shows real samples of it.
- **Topic review** (opt-in checkbox, default on, research only; `jobs.review_topics`): after
  transcription the worker extracts candidate topics (cheap), writes `topics.json` +
  `precomputed_segments.json` (so resuming doesn't pay for transcription twice) and pauses at
  `status=awaiting_review`, `progress_stage=awaiting_topic_review`. `GET/POST /api/jobs/{id}/topics`
  (`routes/topic_review.py`) lists / confirms the topics -- the user can edit wording, untick, and add
  their own (max `RESEARCH_MAX_REVIEWED_TOPICS`). Confirming re-queues with
  `resuming_after_topic_review`; web research then runs only on the confirmed topics. Price unchanged.
- **Emails**: `emails.notify_review_needed(job_id)` after each pause (frame review, scene review, topic
  review); best-effort, same contract as `notify_job_status_change`.
