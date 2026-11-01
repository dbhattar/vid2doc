# Meetings: a bot that joins Zoom / Meet / Teams, then native Zoom import

## Context
A user asked whether Framewrite can take a Zoom recording, or join a meeting itself, and produce the documents automatically. They then asked for Teams and Google Meet too.

Today Framewrite only ingests uploaded files, YouTube links (admin-only) and live in-browser recordings. Nothing in the repo knows about meetings.

Chosen direction, from your answers:
- **Approach:** both, phased. Phase 1 is a meeting bot through a vendor API that covers all three platforms. Phase 2 is native Zoom cloud-recording import.
- **Trigger:** the user pastes a meeting link and the bot joins. Calendar auto-join is out of scope for now.
- **Output:** speaker-labelled transcript, summary, decisions and action items. The user is emailed when it is ready. No automatic Drive save in v1.

Why a vendor bot: Zoom, Teams and Meet each hand out recordings differently (Zoom Marketplace review; Teams needs tenant-admin consent; Meet needs Workspace and restricted Drive scopes). A bot service such as Recall.ai joins any of the three from a link and returns the recording and transcript by webhook. That is one integration for all three platforms, and the host needs no connection.

## Phase 1: meeting bot

### Flow
1. The user opens a new **Meetings** page and pastes a Zoom/Meet/Teams link.
2. The API validates the host, creates a `meetings` row, and asks the vendor to send a named bot ("Framewrite Notetaker") into the meeting.
3. The vendor webhook reports status changes. On done, we fetch the transcript and audio and convert them to our segment format. We charge the wallet, create an **audio** job with precomputed segments, and the existing worker finishes it.
4. The pipeline adds summary, decisions and action items to the document, and the existing done-email notifies the user.

### Backend changes
- **Migration `0028`** adds a `meetings` table: id, user_id, platform, meeting_url, vendor_bot_id, status (`joining|recording|processing|done|failed|cancelled|awaiting_payment`), title, job_id (nullable), error_message and timestamps. The model goes in `backend/app/models.py` and a small CRUD module `backend/app/meetings.py` follows the `drive_connections.py` style (dict returns, own sessions).
- **`backend/app/meeting_bots.py`** is a thin vendor wrapper: `create_bot(url, name)`, `delete_bot(id)`, `fetch_transcript(id)`, `fetch_audio(id)`. Vendor specifics stay in this one module so the vendor can be swapped. Check the vendor's current API and pricing before coding.
- **`backend/app/routes/meetings.py`**:
  - `POST /api/meetings` (`{url, title?}`) allowlists hosts (`zoom.us` and subdomains, `meet.google.com`, `teams.microsoft.com`, `teams.live.com`) and requires a wallet balance covering a minimum charge. It returns 402 otherwise, mirroring `routes/youtube.py`.
  - `GET /api/meetings` lists the caller's meetings.
  - `DELETE /api/meetings/{id}` removes the bot from a scheduled or active meeting.
  - `POST /api/meetings/webhook` is unauthenticated. It verifies the vendor's signature on the raw body and dedups with the existing `billing.claim_webhook_event` (`billing.py:294`). This copies `routes/billing.py:61-77`.
- **Completion handler** (inside the webhook, or queued for the worker):
  - Convert the vendor transcript to `[{speaker, text, start_ts, end_ts}]`.
  - Write it as `OUTPUT_DIR/<job_id>/precomputed_segments.json`. This is the same trick `routes/live.py::finalize_live_session` uses, so `_transcribe_segments` (`pipeline.py:202`) skips paid transcription.
  - Compute duration from the max `end_ts`, charge with `billing.charge_for_job(..., "audio")`, and call `jobs.create_job(job_type="audio", source_path=None)`.
  - If `InsufficientBalanceError` is raised, set the meeting to `awaiting_payment` and email the user. Add `POST /api/meetings/{id}/process` to finish it after a top-up. This case needs a defined behavior because a webhook has no caller to return 402 to.
- **Meeting notes step.** The audio path deliberately skips summaries (`pipeline.py`, audio branch). For jobs linked to a meeting, `_build_audio_sections` also generates summary, decisions and action items. Reuse `compose.generate_summary_and_key_points` and add a structured-output call using `transform._call_json` with a schema for decisions and action items (owner, item). A failure must soft-fail, as `_prepend_summary_section` does.
- **Config** in `backend/app/config.py`: `MEETINGS_ENABLED`, `RECALL_API_KEY`, `RECALL_API_BASE`, `RECALL_WEBHOOK_SECRET`, `MEETING_BOT_NAME` and `MEETING_MAX_SECONDS`. Document them in `backend/.env.example` and the `backend/README.md` env table.
- **Cost guard:** set the bot to leave after `MEETING_MAX_SECONDS`, because the vendor charges per hour of meeting time that we then recoup via the wallet.

### Frontend changes
- New page `frontend/app/(app)/meetings/page.tsx`: link input, a note that the bot will appear in the meeting under its name, and a list of meetings with status and a link to the resulting job at `/dashboard/jobs/[id]`. Reuse `Card`, `Button`, `StatusBadge` and the polling pattern in `dashboard/video/page.tsx`.
- Add a "Meetings" entry in `frontend/components/Sidebar.tsx`.
- Add the `Meeting` type to `frontend/lib/jobs.ts` (or a new `lib/meetings.ts`).

### Legal and trust
- Recording other people needs consent. The bot joins visibly under its own name, and the Meetings page states that the user is responsible for notifying attendees.
- Update `marketing/src/pages/privacy.astro` (name the bot vendor as a processor) and `marketing/src/pages/terms.astro` (recording-consent responsibility). The privacy page already lists third-party processors.

## Phase 2: native Zoom recording import
Value: cheaper than the bot for users who already record to the Zoom cloud, and it needs no bot in the call. It depends on a Zoom Marketplace app that must pass Zoom's review.
- **Connection** (copy the Drive pattern): `zoom_connections` table, `zoom_connections.py`, `routes/zoom.py` with status/connect/disconnect, and an entry on `settings/integrations/page.tsx`.
  - This is a redirect OAuth flow with `state`, unlike Google's popup flow.
  - Zoom refresh tokens rotate on every refresh, so the new token must be saved after each refresh. The Drive code never has to do this.
  - Reuse `crypto.py` for encryption.
- **Webhook** `POST /api/zoom/webhook` for `recording.completed`:
  - Verify Zoom's HMAC (`v0:{timestamp}:{body}`) and answer the `endpoint.url_validation` challenge.
  - Dedup with `claim_webhook_event`.
- **Import:**
  - Prefer the M4A audio file plus the VTT transcript when present, to avoid downloading the large MP4.
  - Add a branch to `_download_if_needed` (`pipeline.py:312`) that downloads with the owner's Zoom token.
  - If a VTT exists, convert it to segments and skip transcription. Otherwise fall through to normal transcription.
  - Reuse the Phase 1 meeting-to-job code path.
- Native Teams (Microsoft Graph) and Meet (Meet REST API) imports are not planned: they require tenant-admin consent or Workspace-only features and restricted-scope verification. The bot already covers them.

## Implementation note (changed from the plan above)
The bot only **records mixed audio** -- we don't buy Recall's transcription (~$0.15/hr extra). The
audio is downloaded and run through our own transcribe/diarize pipeline as an ordinary audio job
(`source_path` set, no `precomputed_segments.json`), so the stages below that convert a vendor
transcript are not used. Trade-off: speakers are "Speaker N" (renameable), not Recall's participant
names. Meetings are billed at $1.00/hour (`billing.SECONDS_PER_CENT_MEETING`).

## Open items to confirm before building
- **Vendor and unit economics:** confirm Recall.ai (or an alternative) pricing, then set a wallet rate for meetings. The current audio rate is $0.40/hour, which may not cover a per-hour bot cost.
- **Minimum balance** held at join time, and the `MEETING_MAX_SECONDS` cap (suggest 2 hours).
- **Consent wording** for the Meetings page and Terms; have a lawyer review it.

## Verification
- **Conversion:** unit-check the vendor-transcript-to-segments converter against a saved sample payload, including speaker names and an empty transcript.
- **Webhook:** send signed and unsigned payloads at `/api/meetings/webhook` with curl. Confirm that bad signatures are rejected, that replaying an event is a no-op, and that a valid event creates one audio job with `precomputed_segments.json` and no transcription call.
- **Billing:** confirm the ledger shows a single charge for a completed meeting, a refund if the job fails, and the `awaiting_payment` path when the wallet is empty, followed by `process` after a top-up.
- **End to end:** with a vendor sandbox key, join a real Google Meet, a Zoom meeting and a Teams meeting from pasted links. Confirm the bot appears by name, the meeting reaches `done`, the job document contains the transcript plus summary and action items, and the done-email arrives.
- **Cancel:** removing a scheduled bot, and a meeting ending early, both leave a clean final status.
- **Frontend:** run `npx tsc --noEmit` and `npm run lint` in `frontend/`. Walk through the Meetings page in a browser.
- **Backend:** there is no test suite and the local env lacks `boto3`, so run these checks with `./restart-containers.sh --dev` from the repo root.
