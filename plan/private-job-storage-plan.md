# Private S3 job storage, replacing 7-day local retention

## Context
Job files (uploads, documents, frames) live on the VPS disk and `retention.py` deletes them after 7 days. The disk fills up and users lose their documents. Instead, finished jobs go to a private S3 bucket and stay until the user deletes them. Only the signed-in owner can read them, through the existing API checks.

Decisions from you:
- Keep documents (md/docx/pdf, transcript.json, images) and the original video/audio. Scratch (frames_raw, audio.wav, stock media) is dropped once the job is done.
- No expiry. Files stay until the user deletes the job.
- Existing API URLs stay the auth gate. Media and large downloads use short-lived presigned URLs. Small text and images stream through the API.
- No backfill. Jobs already on disk keep the old 7-day behaviour until they age out.

Existing pieces to reuse (from exploration):
- `backend/app/s3_client.py::get_client()`.
- `public_jobs.upload_job_archive(job_id, doc_dir, source_path, prefix)` (prefix-agnostic, all-or-nothing) plus `_gather_archive_files`, `delete_s3_archive`, `archive_file_exists`.
- `chat_jobs.generate_media_url` and `GET /api/jobs/{id}/chat/media-url` (presigned, 900s) with the frontend `MediaPreviewPlayer` already using it.

## Design

### Storage
- A **separate private bucket**, `JOB_STORAGE_S3_BUCKET`, with Block Public Access on and default SSE-S3 encryption. The existing bucket has public-read on `public/*` and must not hold private data. Empty setting means the feature is off and the legacy local behaviour applies.
- **Access model: only the owner can reach a file.** Nobody gets direct bucket access, not even signed-in users.
  - The bucket only trusts the app's IAM identity. Block Public Access is on (all four settings), ACLs are disabled (Object Ownership "bucket owner enforced"), and the bucket policy denies any request without TLS.
  - A user reads a file only through the API, after the existing owner check (`job["user_id"] == current_user["id"]`, 404 otherwise). The API then either streams it or issues a presigned URL.
  - Presigned URLs are for one exact key, expire in 5 minutes, and are only created after the owner check. They are never stored or logged.
  - Keys include the user id (`jobs/{user_id}/{job_id}/...`), so the IAM policy and any later audit can be scoped per user. `storage_prefix` stores the full prefix, and `job_storage` builds every key from it and never from request input, so a path like `../` cannot reach another user's files.
  - The one deliberate exception is a Share link: the owner creates a token, and the API serves that job's files through the token routes. Showcase copies go to the public prefix only after explicit consent, as today.
- Keys are `jobs/{user_id}/{job_id}/document/...` (`document.md`, `.docx`, `.pdf`, `transcript.json`, `research.md`, `images/*`) and `jobs/{user_id}/{job_id}/source<ext>`. video_gen `final.mp4` is stored as `jobs/{user_id}/{job_id}/video/final.mp4`.
- Migration `0042` adds `jobs.storage_prefix` (null means legacy local job) and `jobs.storage_files` (JSON list of stored relative paths). `storage_files` replaces the `(doc_dir/"x").exists()` checks in `routes/status.py`.
- Parameterize the bucket in `public_jobs.upload_job_archive` and `delete_s3_archive` (a `bucket=` argument defaulting to the public one). `s3_client.py` gets small helpers: `put/get/stream`, `presign(key, filename=None)`, `copy`.
- New module `backend/app/job_storage.py`:
  - `enabled()`.
  - `store_finished_job(job_id)`: upload with retries, record `storage_prefix` and `storage_files`, then remove `OUTPUT_DIR/{id}` and `UPLOADS_DIR/{id}`. If the upload fails, keep the local files, log it, and leave `storage_prefix` null so the legacy path still covers the job.
  - `doc_dir_for(job, writable=False)`: a context manager that yields the real local doc dir for legacy jobs, or a temp dir downloaded from S3. With `writable=True` it re-uploads changed files on exit.
  - `read_bytes`, `stream`, `presigned_url`, `delete_job(job)`.
  - `fetch_source(job)`: downloads the source into `UPLOADS_DIR` for retry.

### Pipeline
- Uploads and processing happen on the VPS first. The pipeline does not touch S3. A daemon thread in `worker.py` (`job_storage.run_loop`, like `review_reminders.run_loop`) finds `done` jobs with no `storage_prefix` that have sat for `JOB_STORAGE_SETTLE_SECONDS`, pushes them with `store_finished_job`, and retries failures about every 15 minutes (`jobs.list_jobs_pending_storage`). Until then the job is served from local disk like a legacy job.
- `JOB_STORAGE_SYNC_FROM` (optional ISO date) leaves older jobs on disk with the 7-day sweep, so there is no backfill by default behaviour unless it is empty.
- Jobs in `awaiting_review` stay entirely local, because resume-after-review needs `frames_raw`, `review.json`, `scenes.json` and `audio.wav` on disk. They are uploaded when they finish.

### Serving (owner check is unchanged everywhere)
- `routes/documents.py`: `_owned_done_doc_dir` becomes a helper that returns either a local path or the S3 key set. The file route and `bundle.zip` branch on `storage_prefix`:
  - md/transcript/images/docx/pdf are streamed from S3 through the API, so relative image links, the Bearer-auth blob helpers and CORS keep working with no frontend changes.
  - bundle.zip is built from S3 in memory.
- Media is served with presigned URLs:
  - New `GET /api/jobs/{id}/media-url`, generalizing `chat/media-url` (owner check, 900s, Range works). The frontend's `MediaPreviewPlayer` is pointed at it.
  - `routes/video_output.py` returns a presigned redirect for `output.mp4`. The thumbnail is generated once at store time and kept in S3.
- Other readers use `doc_dir_for`:
  - `routes/transcript.py` (speaker rename and re-render, `writable=True`).
  - `routes/drive.py`, `routes/share.py` (public token routes, same S3 reads), `routes/agents.py` (attach snapshot), `routes/chat.py` and `routes/public_jobs.py`.
  - For chat enable and showcase submit, the private objects are copied server-side with `copy_object` into the existing `chat/` and `public/` prefixes. This avoids a second upload.
- `routes/jobs.py`: retry calls `fetch_source` when the local file is gone. Delete removes the S3 prefix as well as local dirs. `routes/status.py` builds links from `storage_files`.

### Retention
- `retention.py` no longer touches jobs with `storage_prefix`. It keeps four things:
  - legacy done jobs without `storage_prefix` (7 days);
  - abandoned `awaiting_review` jobs (7 days, refund as today);
  - failed and cancelled local scratch;
  - orphan folders.
- Update `jobs.list_jobs_eligible_for_retention` and `list_stale_failed_jobs` to filter on `storage_prefix IS NULL` where needed. `retention_expired` stays for legacy jobs only.

### Config, IAM, deploy
- `config.py` and `.env.example`: `JOB_STORAGE_S3_BUCKET`, with region reusing the existing S3 region setting.
- `deploy/aws/user-access.json`: add the new bucket (Put/Get/Delete on `jobs/*`, List on the bucket). Use a dedicated IAM user or role that has no access to anything else.
- New script `deploy/configure-job-bucket.sh`: private bucket, all Block Public Access settings, bucket owner enforced, default encryption, and a bucket policy that denies non-TLS and denies every principal except the app identity. CORS is limited to GET from the app origin, for presigned media only.
- `backend/README.md`: replace the Retention section with a storage section. Set the env var via `fab set-env`.

### Copy updates (remove "7 days")
- Frontend: `settings/billing/page.tsx:149`, `jobs/[id]/page.tsx:258`, `DocumentCard.tsx:50`, `ChatEnableControl.tsx:51-52`.
- Backend: `emails.py:274` and the error strings in `documents.py`, `share.py`, `video_output.py` and `agents.py`.
- Marketing: `privacy.astro:77-80` (stored until you delete them, encrypted at rest, add AWS as a processor), `terms.astro:88-91`, `FAQ.astro:17`, `docs/check-status-and-results.mdx:49-50`.
- Also needs a decision during build: whether account deletion exists and should purge `jobs/`. Check first.

## Verification
- Local: set `JOB_STORAGE_S3_BUCKET` to a test bucket (or a moto/MinIO container) and run `./restart-containers.sh --dev`.
- Run an audio job, a video job and a meeting job. Confirm the S3 objects exist, local `uploads/` and `output/` folders are gone, and the status page shows the right download links.
- Confirm preview and `bundle.zip` work. Check that images render in the document viewer and the video and audio players seek (Range).
- Confirm another user gets 404 on every endpoint, including media-url, bundle.zip and path-traversal attempts such as `../` and another user's job id.
- Confirm the bucket is closed: an anonymous GET on an object URL returns 403, a plain-HTTP request is denied, a presigned URL fails after 5 minutes, and a presigned URL for one key cannot be reused for another key. Run `aws s3api get-public-access-block` and `get-bucket-policy-status` to check.
- Rename a speaker on an S3 job and confirm the re-rendered files are re-uploaded. Confirm retry, delete (S3 prefix gone), Drive export, share link, chat enable and showcase submit all work.
- Force an upload failure and confirm the job stays done and local, and that legacy retention still covers it.
- Run `retention.py --dry-run` and confirm it skips S3 jobs.
- Frontend: `npx tsc --noEmit` and `npm run lint` in `frontend/`. Walk the job page in a browser.
- Backend has no test suite and the local env lacks packages, so run checks inside the compose containers.
- After approval, save this plan to `plan/private-job-storage-plan.md` per AGENTS.md.
