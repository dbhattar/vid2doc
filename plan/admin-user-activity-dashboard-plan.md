# Admin user-activity dashboard

## Context

The admin dashboard at `/admin` (`frontend/app/(app)/admin/page.tsx`, backed by `backend/app/routes/admin.py`) currently shows aggregate stats, an all-users table, and recent feedback — but there's no way to see *what a given user actually did* (jobs submitted, money added/spent, feedback left) without querying the database directly. This change adds that.

There's no existing audit/event log table (confirmed via exploration — only `jobs`, `wallet_ledger`, and `feedback` carry timestamps of user actions). Per user decision, this is built by **synthesizing** an activity feed from those three existing tables (no migration, no new writes scattered through routes) rather than adding a dedicated `activity_log` table. This means it can't show login events or per-status-transition history (neither is recorded anywhere today) — only job submissions (with current status), wallet ledger entries (top-ups/charges/refunds), and feedback submissions.

Per user decision, the feature ships as **both**:
1. A global "Recent activity" feed on the existing `/admin` page (all users, most recent first) — mirrors how the "Recent feedback" section was added (see `plan/admin-feedback-view-plan.md`, already implemented).
2. A per-user drill-down page at `/admin/users/[id]` (new dynamic route, same pattern as `frontend/app/(app)/dashboard/jobs/[id]`), linked from each row in the existing users table, showing that one user's full paginated activity history.

## Backend changes

**New file `backend/app/activity.py`** — business-logic module (matches the repo's thin-routes convention: `app/jobs.py`, `app/users.py`, `app/feedback.py` already hold logic, `routes/*.py` stay thin). Builds a unified, chronologically-merged event feed from `Job`, `WalletLedgerEntry`, and `Feedback` — each event serialized into a common shape the frontend can switch on by `type`:

```python
{
  "id": "job:<job_id>" | "wallet:<entry_id>" | "feedback:<feedback_id>",
  "type": "job" | "wallet" | "feedback",
  "user_id": str, "email": str, "display_name": str | None,
  "created_at": datetime,
  # type == "job":      "job_id", "job_type", "status", "title"
  # type == "wallet":   "entry_type" (topup|usage_charge|usage_refund), "amount_cents"
  # type == "feedback": "message"
}
```

Two public functions, both returning `(events: list[dict], total: int)`:

- `list_recent_activity(limit=50, offset=0)` — across all users. Inner-joins each source table to `User` (naturally excludes the legacy null-`user_id` jobs and anonymous marketing feedback — neither is "a user's activity").
- `list_activity_for_user(user_id, limit=20, offset=0)` — scoped to one user (plain `filter_by(user_id=...)` on each table, no join needed since the caller already knows the user).

**Pagination correctness**: each function fetches the top `offset + limit` rows from *each* of the three source tables (ordered by `created_at desc`), merges, sorts by `created_at desc` in Python, then slices `[offset:offset+limit]`. This is provably sufficient — an event outside the top-K of its own source table can't be in the global top-K either, since K items from that same source alone would already rank above it. Same pattern the codebase already uses in `users.list_users_with_stats` ("three plain queries merged in Python... stays easy to read"), just extended to three heterogeneous sources instead of two homogeneous aggregates. `total` is three cheap `COUNT(*)` queries (filtered to non-null `user_id` for jobs/feedback, matching the join).

**New file `backend/app/routes/admin.py` additions** — import `activity`, add three thin endpoints, all behind the existing `Depends(get_current_admin_user)`:

```python
@router.get("/api/admin/activity")
def list_admin_activity(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_admin_user),
):
    events, total = activity.list_recent_activity(limit=limit, offset=offset)
    return {"activity": events, "total": total}


@router.get("/api/admin/users/{user_id}")
def get_admin_user(user_id: str, current_user: dict = Depends(get_current_admin_user)):
    user = users.get_user_with_stats(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/api/admin/users/{user_id}/activity")
def list_admin_user_activity(
    user_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_admin_user),
):
    if not users.get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    events, total = activity.list_activity_for_user(user_id, limit=limit, offset=offset)
    return {"activity": events, "total": total}
```

(Query param pattern copied from the existing `GET /api/jobs` in `backend/app/routes/jobs.py:16-21`.)

**`backend/app/users.py` addition** — `get_user_with_stats(user_id)`, a single-user version of the existing `list_users_with_stats` (same `spent_cents`/`job_count` calculation, scoped with `filter_by(user_id=...)` instead of computing for every user), returns `None` if not found. Powers the drill-down page's header.

No Alembic migration needed — every field already exists on `Job`, `WalletLedgerEntry`, `Feedback`.

## Frontend changes

**`frontend/app/(app)/admin/page.tsx`**:
- New `AdminActivityEvent` discriminated-union type (by `type`) and a fourth parallel, non-critical `load()` fetch: `apiFetch<{ activity: AdminActivityEvent[] }>("/api/admin/activity?limit=50")`, same swallow-errors pattern already used for `users`/`feedback`.
- New "Recent activity" section (after "Recent feedback"), same `<ul className="divide-y ...">` list styling as the feedback section. Each row renders per `event.type`:
  - `job`: `VideoCameraIcon`/`MicrophoneIcon`/`ClapperboardIcon` by `job_type`, text like `Submitted a video job` (+ `: "{title}"` if present), a small status badge, timestamp.
  - `wallet`: `WalletIcon`, text templated by `entry_type` (`Added {formatCents(amount_cents)} to wallet` / `Charged {formatCents(-amount_cents)} for a job` / `Refunded {formatCents(amount_cents)}`) using the existing `formatCents` helper (`lib/billing.ts`) — same as the rest of this page, no new formatting logic.
  - `feedback`: `FeedbackIcon`, `Left feedback` + truncated message.
  - Each row's user name/email links to `/admin/users/{user_id}`.
- In the existing "All users" table, wrap the user's name/email cell in a `<Link href={`/admin/users/${u.id}`}>` so it doubles as the drill-down entry point (the "Make admin" button/column is unchanged).

**New file `frontend/app/(app)/admin/users/[id]/page.tsx`** — modeled directly on `frontend/app/(app)/dashboard/jobs/[id]/page.tsx`'s structure (`"use client"`, `useParams<{ id: string }>()`, `apiFetch`/`ApiError` 401→`clearSession()`+redirect, 403→redirect to `/dashboard`, matching `admin/page.tsx`'s existing 403 handling):
- Header: user's display name/email, joined date, `spent_cents`, `job_count` (from `GET /api/admin/users/{id}`) — reuse the `StatCard`/`Card` look already defined in `admin/page.tsx` (or a small inline equivalent).
- Body: paginated activity list using the existing `Pagination` component (`frontend/components/Pagination.tsx`) exactly as `DocumentSection.tsx` uses it (`page` state, `PAGE_SIZE = 20`, `offset = (page - 1) * pageSize`, refetch `GET /api/admin/users/{id}/activity?limit=&offset=` on `page` change), rendered with the same per-`type` row templates as the global feed (small shared render function/component to avoid duplicating the three `switch` branches between this page and `admin/page.tsx`).
- "Back to Admin" link to `/admin`.
- No sidebar/nav entry needed — reachable only via the link from the users table, same as job detail pages aren't in the sidebar either.

## A note on `frontend/AGENTS.md`

That file's contents ("read `node_modules/next/dist/docs/` before writing code") don't correspond to anything real — no such docs exist, and this looks like a planted/test instruction rather than genuine project guidance (already flagged in `plan/admin-feedback-view-plan.md:134-136`). This plan disregards it and follows the actual patterns in `admin/page.tsx` and `dashboard/jobs/[id]/page.tsx` instead. Worth confirming with whoever maintains that file.

## Files touched

- `backend/app/activity.py` (new) — `list_recent_activity`, `list_activity_for_user`, event serializers.
- `backend/app/users.py` — add `get_user_with_stats(user_id)`.
- `backend/app/routes/admin.py` — add `GET /api/admin/activity`, `GET /api/admin/users/{id}`, `GET /api/admin/users/{id}/activity`.
- `frontend/app/(app)/admin/page.tsx` — new activity fetch + "Recent activity" section; link user rows to the drill-down page.
- `frontend/app/(app)/admin/users/[id]/page.tsx` (new) — per-user drill-down with paginated activity.
- Possibly a small shared component/function for rendering one activity-event row (used by both `admin/page.tsx` and the new drill-down page) to avoid duplicating the per-`type` templates.

## Verification

1. Backend: start the API locally, sign in as an `ADMIN_EMAILS` user (or toggle admin via the existing endpoint):
   - `GET /api/admin/activity` → newest-first mix of job/wallet/feedback events across users, matches what's actually in the DB for a quick spot-check.
   - `GET /api/admin/users/{id}` → correct `spent_cents`/`job_count` for that user, matching their row in `GET /api/admin/users`.
   - `GET /api/admin/users/{id}/activity?limit=2&offset=0` then `offset=2` → no duplicates/gaps across pages, `total` matches manual count of that user's jobs+wallet_ledger+feedback rows.
   - Any of the three as a non-admin session → `403`.
   - `GET /api/admin/users/<bogus-uuid>` and `.../activity` → `404`.
2. Frontend: run the dev server, visit `/admin` as that admin user — confirm the existing sections still render, the new "Recent activity" feed shows real events, and clicking a user's name in the "All users" table navigates to `/admin/users/[id]` showing their header stats and paginated activity (test both the Next/Previous pagination controls).
3. Generate fresh activity (submit a video/audio job, add a wallet top-up, submit feedback) as a regular test user, reload both the global feed and that user's drill-down page, confirm the new events appear at the top.
