# Playable video clips in per-job chat answers

## Context
Per-job chat (chat-with-document, `backend/app/chat_jobs.py`, `frontend/components/ChatPanel.tsx`) already answers with a single `citation_seconds` and a "Jump to mm:ss" button that seeks the side-by-side `MediaPreviewPlayer`. It plays from that point onward with no end, and only one moment per answer. Goal: each answer carries one or more start/end ranges, and the user can play just that portion.

Decisions (from user): extend the per-job chat only; play clips client-side (seek to start, auto-pause at end) on the existing presigned S3 URL. No server-side ffmpeg, no new media endpoints. Agent chat is out of scope.

## Backend
1. **Schema** (`ANSWER_TOOL` and `ANSWER_JSON_SCHEMA` in `backend/app/chat_jobs.py`): replace `citation_seconds` with `citations: [{start_seconds, end_seconds}]` (array, may be empty). The OpenAI strict schema needs `additionalProperties: False` and all fields required.
2. **Prompt** (`SYSTEM_PROMPT_INSTRUCTIONS`): cite the transcript segment(s) that best support the answer, using start_ts of the first and end_ts of the last contiguous supporting segment. Max ~3 citations, each ideally under ~60s. Empty array when no specific moment applies; never fabricate.
3. **Validation** in `answer_question`: drop citations with non-finite values, end <= start, or start outside the transcript's range. Clamp end to the last segment's end_ts and cap clip length (e.g. 120s). This guards against hallucinated times.
4. **Persistence**: add `ChatMessage.citations` JSON column (nullable) in `backend/app/models.py` plus Alembic migration `0025_chat_message_citations.py`, modeled on `0024_agent_message_sources.py`. Keep `citation_seconds` populated with the first citation's start for back-compat with existing rows.
5. `_message_to_dict` / `add_chat_message` / the POST handler in `backend/app/routes/chat.py` pass `citations` through. For old rows with only `citation_seconds`, `_message_to_dict` returns `citations=[{start_seconds: s, end_seconds: null}]` so history still renders.

## Frontend
1. `frontend/lib/jobs.ts`: add `ChatCitation = {start_seconds: number; end_seconds: number | null}` and `ChatMessage.citations`.
2. `frontend/components/MediaPreviewPlayer.tsx`: add `playRange(start, end?)` to `MediaPreviewHandle`. It sets `currentTime = start`, calls `play()`, and attaches a `timeupdate` listener that pauses at `end` and removes itself. Any user seek or manual pause outside the range cancels the stop (listen for `seeking`), and a new `playRange` replaces the previous listener. Keep `seekTo` for compatibility.
3. `frontend/components/ChatPanel.tsx`: replace the single Jump button (lines ~95-100) with one button per citation, "▶ Play 1:23–1:45" (open-ended falls back to "▶ Jump to 1:23"). `onCitationClick(start, end)` signature. Reuse the local `formatTimestamp`.
4. `frontend/app/(app)/dashboard/jobs/[id]/page.tsx:366-374`: wire `onCitationClick` to `chatMediaRef.current?.playRange`. Scroll the player into view on small screens since it stacks above the chat.
5. Presigned URL expires after 15 minutes (`MEDIA_URL_EXPIRES_SECONDS`) and is fetched once. In `MediaPreviewPlayer`, on the media element's `error` event, refetch `/chat/media-url` and restore `currentTime` / pending range, so a long chat session doesn't break clips.

## Out of scope / notes
- Chat is still only available after the paid enable. The source video is retained only through the S3 archive (non-enabled jobs lose it at 7 days), so no change there.
- Audio jobs use the same flow (`<audio>`), so clips work there too.

## Verification
- Backend: ask a question on a chat-enabled job and check the POST response has valid `citations`; ask something not in the document and confirm `citations: []`. Unit-test the citation validation helper with bad values (end < start, NaN, out of range). Run `alembic upgrade head` locally (`./restart-containers.sh --dev`).
- Frontend: `npm test` and `npm run lint`/typecheck. Manual: click a clip and confirm it starts at the right time and pauses at the end; scrub away mid-clip and confirm it doesn't re-pause; reload and confirm old messages (citation_seconds only) still render; wait out the URL expiry (or shorten `MEDIA_URL_EXPIRES_SECONDS` temporarily) and confirm recovery.
- Per repo convention, save this approved plan to `plan/chat-video-clips-plan.md`.
