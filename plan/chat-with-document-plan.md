# Chat with your document

## Context

Users currently get a static generated document from a video/audio job.
The ask: let a user ask follow-up questions about a *completed* job's
document, get an answer grounded in that document, and have the answer
point back to the moment in the original media it came from — so the user
can replay that moment to verify.

Confirmed with the user this session:
- Scope: `job_type in ("video", "audio")` only (not `video_gen`).
- Billing: a **flat one-time fee charged at opt-in** (unlimited messages
  after that).
- Chat history **persists** per job (new table).
- **Opt-in is irreversible, and archives both the document and the original
  media to S3** — the same shape as the existing Public Showcase feature
  (`backend/app/public_jobs.py`), not the reversible `share_token` toggle.
  Unlike showcase, this archive is **private** to the owner (a new,
  non-public S3 prefix), with no admin review step.

## Why this mirrors Public Showcase's design almost exactly

Public Showcase already solved the hard problem this feature has too: a
completed job's local files are not permanent (`backend/retention.py`
sweeps them after 7 days), but the feature needs them to survive past that.
Showcase's answer — archive to S3 **synchronously, at opt-in time, before**
the job could ever be swept — applies here unchanged. That means:
- **`retention.py` needs zero changes.** Exactly like showcase's own module
  docstring argues: opt-in requires `status=="done" and deleted_at is None`
  (the same gate `share.py`/`public_jobs.py` already use), so by
  construction the archive exists before the 7-day sweep could ever run.
  After that, chat reads from S3, never local disk — local sweep is
  irrelevant to it either way.
- The opt-in deadline is the same as showcase's: a job whose local files
  have *already* been swept (`deleted_at is not None`) can no longer opt in
  — there'd be nothing left to archive.
- **`public_jobs._upload_job_archive(job_id, doc_dir, source_path, prefix)`
  can be reused as-is** (already prefix-agnostic, already does the
  all-or-nothing upload-with-rollback-on-failure this needs) — just called
  with a new private prefix instead of showcase's `public/{job_id}/`.

## Key pipeline finding (unchanged from first pass)

Video jobs **do not persist `transcript.json` today** — only audio jobs do
(`backend/app/pipeline.py:471-497`). Video's `document.md` is LLM-rewritten
from transcript segments (`stages/compose.py`) with no timestamp
back-reference surviving into it. Since opt-in happens *after* completion,
there's no recovering per-segment timestamps retroactively — so **video
jobs must start persisting `transcript.json` unconditionally**, the same
way audio already does (cheap text, written regardless of whether chat is
ever used). Audio needs no pipeline change.

Chat answers are grounded by giving the LLM both `document.md` and the
transcript segments together, and having it pick the `start_ts` of the most
relevant segment as the citation — not a pre-baked mapping.

## Backend

**`backend/app/models.py`** — new `Job` columns, modeled on
`public_archive_prefix`/`public_video_key` (not `share_token` — this is
permanent/archived, not a revocable flag):
- `chat_enabled_at: Mapped[datetime | None]` — NULL means never opted in;
  once set, permanent (no un-enable path, same as showcase's
  `public_status` once "approved").
- `chat_archive_prefix: Mapped[str | None]` — e.g. `chat/{job_id}/`.
- `chat_video_key: Mapped[str | None]` — archived source media's filename
  relative to the prefix (same convention as `public_video_key`).

**New table `ChatMessage`**: `id` (uuid pk), `job_id` (FK `jobs.id`,
indexed), `role` (`"user"|"assistant"`), `content` (Text),
`citation_seconds` (Float, nullable — assistant-only), `created_at`.

**Migration `0018_chat_with_document.py`**: the three `jobs` columns above
+ `chat_messages` table with an index on `job_id`.

**`backend/app/pipeline.py`**: in the video branch
(`_compose_and_finalize` / `resume_after_review`, ~lines 228-256), write
`transcript.json` via `extra_files` the same way the audio branch already
does (`pipeline.py:471-497`) — `{"segments": [{"speaker","text","start_ts","end_ts"}, ...]}`.

**`backend/app/jobs.py`**: add the three new columns to `_job_to_dict`. No
other changes — `list_jobs_eligible_for_retention` stays exactly as-is.

**`backend/app/billing.py`**: new `CHAT_ENABLE_FEE_CENTS` constant (via
`settings`) and `charge_for_chat(user_id, job_id) -> int`, mirroring
`charge_for_job`'s lock-check-charge shape (`entry_type="chat_enable_charge"`,
added to `net_spent_cents`'s filter list). Charge **before** archiving
(fail fast on insufficient balance before doing any S3 work); if the
archive then fails, refund via the existing `refund_job_charge` and return
502 — mirrors how a mid-pipeline failure is already refunded elsewhere.

**`backend/app/config.py` / `.env.example`**: new `CHAT_ENABLE_FEE_CENTS` —
placeholder, flagged "CHANGE THIS before launch" (same convention as
`PUBLIC_CONSENT_REFUND_PERCENT`).

**New `backend/app/chat_jobs.py`** (business logic, mirrors
`public_jobs.py`):
- `archive_prefix_for(job_id) -> f"chat/{job_id}/"` — a **private** prefix,
  distinct from showcase's `public/{job_id}/`. The existing bucket policy
  (`deploy/aws/bucket-policy.json`) only grants public read on `public/*`,
  so anything under `chat/*` is private by default (no policy grants it
  access) — no new bucket needed, just a different prefix.
- `enable_chat(job, doc_dir) -> dict`: calls
  `public_jobs._upload_job_archive(job["id"], doc_dir, Path(job["source_path"]), prefix)`
  (reused directly), then persists `chat_enabled_at`/`chat_archive_prefix`/
  `chat_video_key` on the job.
- `answer_question(job, history, question) -> {"answer": str, "citation_seconds": float | None}`
  — reads `document.md` + `transcript.json` **from S3** (via
  `s3_client`'s `get_object`, not local disk — local files may already be
  gone by the time of any given chat message), same provider-switched
  structured-output pattern every pipeline stage uses
  (`stages/compose.py`/`stages/classify.py`'s `_get_client_and_fn` +
  forced-tool-use/JSON-schema helpers), with schema
  `{"answer": string, "citation_seconds": number|null}`. Prompt: answer
  using only the document; cite the `start_ts` of the single most relevant
  transcript segment if the answer corresponds to a specific moment, else
  `null`; never fabricate a citation. Feeds in prior `history` for
  multi-turn context.

**New `backend/app/routes/chat.py`**:
- `POST /api/jobs/{job_id}/chat/enable` — owner-only; requires
  `job_type in ("video","audio")`, `status=="done" and deleted_at is None`,
  `chat_enabled_at is None` (not already enabled). Charges the flat fee,
  then archives (refund-and-502 on archive failure, as above).
- `GET /api/jobs/{job_id}/chat/messages` — owner-only, lists persisted
  history.
- `POST /api/jobs/{job_id}/chat/messages` — owner-only, requires
  `chat_enabled_at is not None`; persists the user message, calls
  `chat_jobs.answer_question`, persists and returns the assistant message.
- `GET /api/jobs/{job_id}/chat/media-url` — owner-only, requires chat
  enabled; returns a short-lived **presigned S3 GET URL**
  (`s3_client`'s `generate_presigned_url`, ~15 min expiry) for the archived
  source media. The frontend points a plain `<video>`/`<audio>` element's
  `src` directly at this URL — no proxy-streaming through the API, and S3
  natively supports HTTP Range requests, so seeking/scrubbing works with no
  extra backend code.
- No disable/un-enable endpoint — irreversible by design, matching
  showcase's "no un-publish path."
- Register `chat.router` in `backend/app/main.py`.

**Deploy/infra follow-up (not application code, flagging so it isn't
missed)**: the app's runtime IAM policy (`deploy/aws/user-access.json`)
currently scopes `PutObject`/`GetObject`/`DeleteObject` to
`arn:...:bucket/public/*` only. It needs the same actions added for the new
`chat/*` prefix too, then re-applied via
`deploy/configure-s3-bucket.sh --iam-user <user>`.

## Frontend

**`frontend/lib/jobs.ts`**: add `chat_enabled?: boolean` to `Job`; new
`ChatMessage` type.

**New `frontend/components/ChatPanel.tsx`**: message list + input, calls
the chat endpoints; an assistant message with non-null `citation_seconds`
renders a clickable timestamp badge.

**New `frontend/components/MediaPreviewPlayer.tsx`**: fetches the presigned
URL once from `/chat/media-url`, renders a plain `<video>`/`<audio>` with
that URL as `src` (no custom auth-header fetching needed — the presigned
URL carries its own signed auth), exposing a `seekTo(seconds)` via
`forwardRef`/`useImperativeHandle` so a chat citation click can jump
playback. Simpler than a blob-fetch approach specifically because the URL
is presigned.

**`frontend/app/(app)/dashboard/jobs/[id]/page.tsx`**: for
`job_type in ("video","audio")`, `status==="done"`, not retention-expired —
new section after `ShareControl`: if not enabled, an opt-in card stating
**both** the flat fee **and** that this is permanent/irreversible (mirrors
`PublicConsentControl`'s existing inline-confirm pattern for
money-moving, irreversible actions); if enabled, `MediaPreviewPlayer` +
`ChatPanel` side by side.

## Verification

1. Migration applies/rolls back cleanly on top of `0017`.
2. Complete a real video job — confirm `transcript.json` now exists locally
   (previously video jobs never wrote this).
3. Opt into chat — confirm the flat fee is deducted exactly once, confirm
   the S3 objects appear under `chat/{job_id}/` (document + transcript +
   source media), and confirm that prefix is **not** publicly readable
   (anonymous `curl` → 403/AccessDenied, unlike the `public/` prefix).
4. Confirm a second opt-in call on the same job is rejected.
5. Confirm a job whose `deleted_at` is already set (past the 7-day sweep)
   can no longer opt in.
6. Ask a question answered by the document — confirm a plausible
   `citation_seconds`, and that clicking it seeks the player to the right
   moment via the presigned media URL.
7. Ask something not covered — confirm `citation_seconds` is `null` and the
   model says so rather than fabricating a moment.
8. Reload the page — confirm chat history persists.
9. Manually backdate the job's `created_at` past 7 days and run
   `retention.py` — confirm local files are swept exactly as normal (no
   special-casing needed) while chat continues to work fully afterward,
   reading from S3.
