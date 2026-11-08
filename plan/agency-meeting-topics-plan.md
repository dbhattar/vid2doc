# Public agency meetings: ingest, topic-tag, subscribe, notify

## Context
Framewrite would watch public government meetings, turn each recording into a summary and transcript, tag it with topics, and email people who subscribed to those topics. Decisions from you:
- **Source:** public recording links (an agency's YouTube channel or similar archive), polled. No live bot.
- **Visibility:** processed meetings are public to everyone, with no consent flow. Subscribing needs an account.
- **First release:** one agency, end to end. More agencies are added later through an admin page. I still need you to name the agency and give its recording archive URL before the build starts (you mentioned CAISO earlier).

## Design

### Data (migration `0040`, chained from `0039`)
- `meeting_sources`: agency name, slug, `adapter` (`youtube` first), `feed_url`, optional `title_filter` regex, `enabled`, `last_polled_at`.
- `agency_meetings`: `source_id`, `external_id` (unique per source), title, meeting date, `source_url` (link back to the official recording), `job_id`, `status` (`discovered | processing | ready | failed | hidden`), duration, `summary`, `document_md`, `transcript` JSON, error, `processed_at`.
  - Text lives in the DB, not on disk. The 7-day sweep in `retention.py` then doesn't matter for these, and we don't re-host government video.
- `topics`: slug, name, description, `active`. A curated list managed by an admin.
- `agency_meeting_topics`: meeting, topic, short summary of what was said, `start_ts`/`end_ts`. This gives a timestamp deep link in each alert.
- `topic_subscriptions`: `(user_id, topic_id)`.
- `topic_notifications`: `(meeting_id, user_id)` unique, status `pending | sent | failed`, claim/sent timestamps. This is a delivery queue, so a retry never double-sends.
- `users.notify_topic_alerts` boolean, default true (added to `users.PREFERENCE_FIELDS`, `routes/preferences.py` and the Settings page).

### Ingest (new `backend/app/agency_ingest.py`, loop started from `worker.py`)
Copy the shape of `review_reminders.run_loop` (try/except around a sweep, then sleep). Each tick, per enabled source:
1. **Discover:** the adapter lists recent items (yt-dlp `--flat-playlist` for `youtube`). Insert new `agency_meetings` rows. Only items newer than `AGENCY_BACKFILL_DAYS` (default 14) are processed, so a first run doesn't transcribe a channel's whole history.
2. **Queue:** create a job with `jobs.create_job(user_id=None, source_url=..., billed_cents=0, job_type="video", extract_frames=False, transformation="document", review_topics=False)`. This avoids every user-review pause, which would otherwise stall a job with no owner. A tunable `AGENCY_MAX_NEW_PER_DAY` caps spend.
3. **Reconcile:** each tick checks `processing` meetings against their job. `done` copies the document, summary and transcript into the row, then tags it and queues notifications. `failed` records the error. Doing this in the loop means no pipeline edit, and a crashed tick just retries.

Three existing-code changes this needs:
- `pipeline._download_if_needed` (`pipeline.py:429`) caps jobs at 90 minutes unless the owner is an admin. Meetings run hours, so add `AGENCY_MAX_DURATION_SECONDS` (tunable) for owner-less jobs.
- `jobs.claim_next_queued_job` is oldest-first, so a 5-hour agency job would hold up customers. Order by `user_id IS NULL` last, then `created_at`.
- `youtube.py` and `_download_if_needed` are YouTube-only (`_ALLOWED_HOSTS`, no host dispatch). Allow the agency's host, driven by the source row.

Cost note: the YouTube path already downloads English captions when they exist and uses them as `precomputed_segments.json`, which skips paid transcription. Agency channels often have them. Without captions Framewrite pays for transcription of every meeting hour. That is the main running cost, so the daily cap matters.

### Topic tagging (new `backend/app/topics.py`)
- Copy `stages/speaker_ids.py`: a system prompt, a JSON schema, and `transform._call_json`. It already handles both OpenAI and Anthropic structured output.
- Long meetings are split into transcript chunks (about 8k tokens). Each chunk call gets the active topic list and returns topics with a one-line summary and start/end time. Results are merged per topic, keeping the earliest start.
- The model may also propose a topic that isn't in the list. Those go into an admin review list (suggested topics) and never notify anyone until approved.
- A failed or empty tagging leaves the meeting `ready` but untagged and sends nothing. An admin can re-run it.

### Notifications
- When a meeting becomes `ready`, insert one `topic_notifications` row per subscriber who matches any of its topics. One email per person per meeting, listing all their matching topics with timestamp links.
- A delivery loop modelled on `announcements._claim_next_delivery` (`FOR UPDATE SKIP LOCKED`, stale-claim timeout, per-send delay) sends via `mailgun_client.send_email` with an HTML body from the `emails._job_status_email_shell` shell.
- Respect `notify_topic_alerts`. Every email carries a `List-Unsubscribe` header and a footer link.
- The existing unsubscribe token only flips `announcements_opt_out`. Add a second token purpose in `tokens.py` and a POST route (the page confirms by button, as the existing `/unsubscribe` page does, so mail scanners can't trigger it).
- Slack can plug in later as a second channel on the same queue. Not in this release.

### API
- Public: `GET /api/public/topics`, `GET /api/public/topics/{slug}/meetings`, `GET /api/public/agency-meetings/{id}`.
- Signed-in: `GET/PUT /api/me/topic-subscriptions`.
- Admin (`routes/admin.py` pattern): sources CRUD, topics CRUD, suggested-topic approval, meetings list with re-run/hide, and a manual "add a meeting by URL" for testing.
- Tunables in `tunables.py`: a new "Agency ingest" group (`AGENCY_INGEST_ENABLED`, `AGENCY_POLL_INTERVAL_SECONDS`, `AGENCY_BACKFILL_DAYS`, `AGENCY_MAX_NEW_PER_DAY`, `AGENCY_MAX_DURATION_SECONDS`).

### Frontend
- Public, unauthenticated pages outside the `(app)` group, mirroring `app/showcase/[job_id]`: `/topics` (browse and subscribe), `/topics/[slug]`, and a meeting page (summary, topics with timestamps, transcript, link to the official recording, "AI-generated, may contain errors" notice).
- Subscribe from those pages: a signed-out visitor goes to login and comes back.
- Settings page: a "Topic alerts" section listing subscriptions, plus the `notify_topic_alerts` toggle.
- Admin pages `/admin/sources`, `/admin/topics`.
- `frontend/AGENTS.md` says this Next.js version has breaking changes, so read the relevant guide in `node_modules/next/dist/docs/` before writing the pages. Public pages should render on the server so search engines can read them.

### Risks to decide before shipping
- **YouTube from the VPS:** the existing route is admin-only because YouTube bot-checks datacenter IPs. Polling needs the cookies file (`DATA_DIR/youtube_cookies.txt`) and may still get blocked. Downloading also touches YouTube's terms. If the agency hosts its own files, that avoids both.
- **Public record, real people:** transcripts include named officials and members of the public. Add a visible takedown/contact path and update the privacy and terms pages.
- **Accuracy:** speaker names come out as "Speaker N" unless the existing speaker identification works on these recordings. Label summaries as AI-generated.

## Build order
1. Tables, ingest loop and tagging, with "add a meeting by URL" in admin. Run one real meeting through before polling is enabled.
2. Public topic and meeting pages.
3. Subscriptions, notification queue, email, unsubscribe, Settings section.
4. Admin source and topic management, then enable polling for the first agency.

## Verification
- Backend has no test suite, so run checks in the compose `worker` container with a fake adapter and a fake `_call_json`, as in the earlier fake-S3 tests.
- **Test hygiene:** do not call global sweeps (`retention.main()`, the delivery loops) against the dev database. The last test run deleted real dev data that way. Call per-row functions directly, prefix test rows, clean them up, and mock mail sending.
- Cases:
  1. A discovered item becomes a job with no owner, `billed_cents=0`, no review pause. A duplicate poll doesn't create a second job.
  2. A `done` job fills the meeting row. A `failed` job marks it failed with the error.
  3. Chunked tagging merges topics. An unknown topic goes to the suggestion list, not to subscribers.
  4. Notifications: one row per matching subscriber, no duplicates on re-run, opted-out users skipped, a send failure stays retryable.
  5. Unsubscribe token: wrong purpose is rejected, and the right one flips `notify_topic_alerts`.
  6. A user job queued after an agency job is claimed first.
  7. The owner-less job is allowed past 90 minutes.
- Migration: `alembic upgrade head` on a clean DB and on the dev DB. The stashed private-storage migration will need renumbering to `0041`.
- Frontend: `npx tsc --noEmit`, `npm run lint`, and a browser pass over the public pages and Settings.
- One real recording from the chosen agency through the whole path, including a real subscriber email, before enabling polling.
- Not verifiable here: real Mailgun, real YouTube access from the VPS, and real LLM output quality on long meetings.
- After approval, save this plan to `plan/agency-meeting-topics-plan.md` per AGENTS.md.
