# Admin all-jobs list page

## Context

The admin dashboard (`/admin`) only shows aggregates (revenue, user count, top spenders) and a per-user drill-down — there's no way to see the actual jobs people are submitting: what they're converting, from where, how big, how long it took, or whether/how it failed. This adds a dedicated admin page listing every job across every user with full metadata.

Per user decision: **no new instrumentation for now**. Research confirmed there's no per-step timing anywhere in the system today — `progress_stage` is overwritten on every transition (`jobs.update_job`, `backend/app/jobs.py:179-190`), so once a job finishes there's no way to reconstruct how long each stage took, only total wall-clock time (`created_at` → `updated_at`). Real per-step timing would need a new `stage_timings` JSON column written at each of pipeline.py's ~15 stage transitions — deferred as a separate follow-up. This pass ships the list page with everything already available: status, current/last-known stage, user, title, source (YouTube link or uploaded file + size), duration, total elapsed time, and billing — the metadata the user explicitly said they care about most.

## Backend changes

**`backend/app/jobs.py`** — two new functions, modeled directly on `list_users_with_stats`'s use of a plain query (no new abstraction) and `feedback.list_feedback_with_users`'s outerjoin-with-User pattern (a job's `user_id` can be null for legacy pre-auth rows, same reasoning):

```python
def list_all_jobs(limit: int = 20, offset: int = 0) -> list[dict]:
    """Every job, newest first, joined with the submitting user's identity --
    outerjoin since legacy jobs (pre-auth) have user_id=None. Admin-only
    (see routes/admin.py)."""
    session = get_session()
    try:
        rows = (
            session.query(Job, User)
            .outerjoin(User, Job.user_id == User.id)
            .order_by(Job.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [{**_job_to_dict(j), "email": u.email if u else None, "display_name": u.display_name if u else None} for j, u in rows]
    finally:
        session.close()


def count_all_jobs() -> int:
    session = get_session()
    try:
        return session.query(Job).count()
    finally:
        session.close()
```

(No `status`/`job_type` filter params in this first pass -- keeps the page simple; easy to add later without a frontend contract change since they'd just be additional optional query params.)

**`backend/app/routes/admin.py`** — one new endpoint, same shape as the existing `GET /api/admin/users`, behind the existing `Depends(get_current_admin_user)`:

```python
@router.get("/api/admin/jobs")
def list_admin_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_admin_user),
):
    return {"jobs": jobs.list_all_jobs(limit=limit, offset=offset), "total": jobs.count_all_jobs()}
```

`_job_to_dict` (already used everywhere in `jobs.py`) already carries everything needed: `source_url` (YouTube link when present), `source_size_bytes`, `duration_seconds`, `billed_cents`, `error_message`, `progress_stage`, `status`, `job_type`, `extract_frames`, `aspect_ratio`/`video_template`/`stock_media_provider` (video_gen), `created_at`/`updated_at`. No migration, no changes to `_job_to_dict` itself.

## Frontend changes

**New file `frontend/app/(app)/admin/jobs/page.tsx`** — modeled on the per-user drill-down page's structure (`admin/users/[id]/page.tsx`: `"use client"`, `apiFetch`/`ApiError` 401/403 handling, `Pagination` component, `PAGE_SIZE = 20`, `offset = (page - 1) * PAGE_SIZE`):

- `AdminJob` type matching the actual dict shape from `list_all_jobs` (note: key is `id`, not `job_id` -- this is a different shape than the owner-facing `Job` type in `lib/jobs.ts`, not a reuse of it).
- Fetches `GET /api/admin/jobs?limit=20&offset=...` on mount and on page change, plus a `total` for `Pagination`.
- One table, horizontally scrollable (`overflow-x-auto`, same as the existing "All users" table), columns: **User** (links to `/admin/users/{user_id}`, or "—" for legacy null-user jobs) · **Title** (+ error message inline below in `text-status-error` for failed jobs, same as `JobRow.tsx`'s pattern) · **Type** (icon via `VideoCameraIcon`/`MicrophoneIcon`/`ClapperboardIcon`, "(transcript only)" suffix when `job_type === "video" && !extract_frames`, and a small `aspect_ratio · video_template · stock_media_provider` subtext line for `video_gen`) · **Status** (reusing `STATUS_STYLES`/`STATUS_LABELS` exported from `components/StatusBadge.tsx`, plus the human stage label looked up via `getStagesForJobType(job_type)` from `lib/jobStages.ts`, falling back to the raw `progress_stage` string) · **Source** (a link to `source_url` when set, else `Uploaded · {formatBytes(source_size_bytes)}`) · **Duration** (`formatDuration(duration_seconds)`) · **Total time** (reuse `formatElapsed` from `lib/jobs.ts` -- it only touches `created_at`/`updated_at`, both present) · **Billed** (`formatCents(billed_cents)`) · **Created** (date).
- "← Back to Admin" link at the top, same convention as `admin/users/[id]/page.tsx`.

**`frontend/app/(app)/admin/page.tsx`** — add a small link near the page header, e.g. next to the "Admin" title: `<Link href="/admin/jobs">View all jobs →</Link>`. No Sidebar/nav changes (same reasoning as the per-user drill-down page: reachable via a link, not a top-level nav item).

## Files touched

- `backend/app/jobs.py` — add `list_all_jobs`, `count_all_jobs`.
- `backend/app/routes/admin.py` — add `GET /api/admin/jobs`.
- `frontend/app/(app)/admin/jobs/page.tsx` (new) — the jobs list page.
- `frontend/app/(app)/admin/page.tsx` — one added link to the new page.

## Explicitly deferred (follow-up, not this pass)

Real per-step timing (e.g. "transcribing took 3m20s"). Requires: a `stage_timings` JSONB column on `jobs` (per user's preference over a separate events table), a migration, and wrapping each of pipeline.py's ~15 `jobs.update_job(..., progress_stage=...)` call sites to append `{stage: {started_at, ended_at}}` as stages transition. Only benefits jobs created after that ships -- nothing retroactive.

## Verification

1. Backend: `GET /api/admin/jobs?limit=5` as an admin session -- confirm newest-first ordering, `email`/`display_name` populated for real users and `null` for any legacy null-user job, `total` matches `SELECT count(*) FROM jobs`. As a non-admin session -- expect `403`.
2. Frontend: visit `/admin`, click "View all jobs", confirm the table renders with real data -- spot-check a YouTube-imported job shows its link, an uploaded job shows its size, a failed job shows its error inline, a video_gen job shows its aspect ratio/template/provider subtext, and Previous/Next pagination works.
3. Screenshot both states (a page with jobs, and pagination on page 2) the same way the previous admin-dashboard work was verified (local Docker stack + Playwright with an injected admin session token).
