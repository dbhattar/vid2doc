# Keep public (and chat) jobs on the dashboard after the 7-day sweep

## Context
A job made public is archived to S3 at opt-in (`public/<job_id>/...`: document.md, docx, pdf, transcript.json, images, source video), and the showcase reads that copy. The dashboard reads local disk instead. `backend/retention.py` deletes every done job's local files after 7 days and sets `deleted_at`, without checking for an archive. `routes/status.py` then returns `retention_expired` and the job page shows "deleted per the 7-day retention policy", even though the files still exist in S3.

Chat-enabled jobs have the same gap. `chat_jobs.py` already reads from the archive "because local files may be long gone", but `routes/chat.py:37` rejects jobs with `deleted_at` set, and the dashboard hides them the same way.

Fix: a job with an S3 archive is never marked deleted. The sweep still frees its local files, and the owner's routes fall back to the archive. Jobs already swept are recovered by clearing `deleted_at`.

## Design

### Which archive a job has
New helper `public_jobs.archive_prefix_for_owner(job)` (or in a small `archive_access` module) returning the prefix or None:
- `public_archive_prefix` when `public_status` is `pending` or `approved`. A rejected job's archive is deleted, so it is treated as having none.
- else `chat_archive_prefix` when set.

Both live in `PUBLIC_ARCHIVE_S3_BUCKET`. The API reads them with boto3 `get_object`, so the chat prefix being non-public doesn't matter. Keys are `prefix + name`, with names checked against the fixed set (document.md/.docx/.pdf, transcript.json, `images/<file>`) and no `..`.

### Retention (`backend/retention.py`, `jobs.list_jobs_eligible_for_retention`)
- For a done job with an archive: remove local dirs as now, but do NOT set `deleted_at` or null `document_path`. Print "freed, archived".
- `awaiting_review`, failed/cancelled, orphans and jobs without an archive are unchanged.
- Update the module docstring.

### Serving (owner check unchanged)
- `routes/documents.py`: `_owned_done_doc_dir` becomes a helper that returns either the local dir or the archive prefix.
  - The file route streams `get_object(prefix + file_path)` when the local file is missing. Relative image links keep working, and the Bearer-auth blob helpers need no frontend change.
  - `bundle.zip` is built from `list_objects_v2` on `images/` plus document.md.
- `routes/status.py`: when the local doc dir is gone but the job has an archive, advertise `document_url`, `document_bundle_url`, and the docx/pdf/transcript links. HEAD checks (`public_jobs.archive_file_exists`) run only in `get_status` (single job), not the `GET /api/jobs` list. The list omits the optional links for swept jobs. Check during build that nothing on the list page needs them.
- `routes/chat.py:37`, `share.py`, `agents.py`: leave `deleted_at` as the gate. They work for archived jobs now because `deleted_at` stays null, and they read through the same fallback where they use local files. Check each one's local-file reads, and make `share.py` and `agents.py` use the fallback where they open `document.md`.
- Dashboard media: the job page's source-video player uses a presigned URL for the archived source (reuse `chat_jobs.generate_media_url`'s pattern, with `public_video_key`, and a new `GET /api/jobs/{id}/media-url` that handles both prefixes). Check how the job page plays media today and wire it up.

### Recover already-swept jobs
One-off script `backend/scripts/restore_archived_jobs.py`, dry-run by default: for done jobs with `deleted_at` set and an archive prefix (public pending/approved or chat), set `deleted_at = NULL`. Only jobs whose archive objects still exist (HEAD `document.md`) are restored. Run it once on the VPS after deploy. Jobs with no archive stay deleted, as before.

### Frontend
No change expected. `retention_expired` is no longer sent for these jobs. After this fix the message only appears for jobs that really have nothing left.

### Interaction with the stashed "private S3 job storage" work
`stash@{0}` replaces 7-day retention entirely for new jobs. This fix is independent and small, and covers jobs created before that ships. When the stash is popped, `retention.py` and `routes/documents.py` will conflict. Resolve by keeping the archive fallback as the path for legacy jobs.

## Verification
- Backend has no test suite, so run checks in the compose `worker` container with a fake S3 (as in the earlier `test_storage.py` approach):
  1. Create a done job with local files, an approved public archive and a user. Run `retention.py` with the cutoff forced. Confirm local dirs are gone, `deleted_at` is still null, `build_job_response` has no `retention_expired`, and `document_url` is present.
  2. `GET /api/documents/{id}/document.md`, `images/x.png` and `bundle.zip` return the archive contents for the owner. Another user gets 404. `../` in the path gets 400/404.
  3. A job with no archive is still swept and still shows the retention message.
  4. A rejected job (archive deleted) is swept normally.
  5. Chat-enabled job: swept locally, `chat/messages` and enable-checks still work.
  6. Restore script: dry run lists only swept jobs with an existing archive. A real run clears `deleted_at` and the dashboard serves them.
- `retention.py --dry-run` output shows "archived" for these jobs.
- Frontend: `npx tsc --noEmit` and `npm run lint` if anything is touched. Check the job page in a browser against a restored public job.
- Not verifiable here: real AWS, and the VPS data. Run the restore dry-run on the VPS first.
- After approval, save this plan to `plan/public-job-dashboard-access-plan.md` per AGENTS.md.
