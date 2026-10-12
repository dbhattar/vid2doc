# Admin control over which showcases appear on the homepage

## Context

The public showcase feature (`backend/app/public_jobs.py`) today has a
closed, one-way state machine: `null → pending → approved` (or `rejected`),
with the model's own comment confirming this is deliberate — *"Once
'approved' it's permanent -- there is no un-publish/revoke path."*
Confirmed via direct code reading: there is no visibility/hidden/featured
flag anywhere in the codebase today, and the two query functions the public
showcase endpoint calls (`jobs.list_jobs_by_public_status`,
`jobs.count_jobs_by_public_status`) have no secondary filter at all.

The user wants admin to be able to curate the homepage carousel — exclude
specific already-approved items from it — without touching `public_status`
(preserving the existing approve/refund decision and the "permanent" design
intent), without deleting the S3 archive, and with everything visible by
default. Per direct confirmation: **hiding affects only the homepage
carousel** (`GET /api/public/showcase`'s list) — the direct permalink page
(`/showcase/{job_id}`) keeps working for anyone who already has the link.

## Design

Add one new, orthogonal boolean column rather than touching the existing
closed enum — mirrors the exact pattern already used for
`cancel_requested`/`extract_frames` on the same `Job` model (plain
non-nullable `Boolean`, Python-level `default=False`, DB-level
`server_default=sa.false()` so every existing approved row stays visible
the moment this ships).

### 1. Migration — `backend/alembic/versions/0019_public_hidden.py`

Follows `0014_job_cancellation.py`'s exact shape (the most recent precedent
for adding a single non-nullable boolean column):
```python
def upgrade() -> None:
    op.add_column("jobs", sa.Column("public_hidden", sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade() -> None:
    op.drop_column("jobs", "public_hidden")
```

### 2. `backend/app/models.py`

Add next to the other `public_*` columns (around line 149-ish, keeping
them grouped):
```python
# Admin-only: excludes an already-"approved" item from the homepage
# carousel (GET /api/public/showcase) without touching public_status,
# the refund, or the S3 archive -- public_status's own "approved is
# permanent, no un-publish path" design (see that column's comment) stays
# true; this is a separate, reversible display toggle layered on top.
# Direct permalink access (/showcase/{job_id}) is unaffected by this flag.
public_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

### 3. `backend/app/jobs.py`

- `_job_to_dict`: add `"public_hidden": job.public_hidden` so it flows
  through every existing dict consumer (admin list/detail already spread
  the full job dict, so no extra route-level wiring needed there).
- `list_jobs_by_public_status`/`count_jobs_by_public_status`: add an
  optional `exclude_hidden: bool = False` parameter to each, adding
  `.filter(Job.public_hidden.is_(False))` when true. Defaulting to `False`
  preserves the admin moderation queue's existing behavior exactly (admin
  must see hidden items too, to be able to un-hide them) — only the public
  showcase call site opts in.

### 4. `backend/app/routes/public_jobs.py`

`list_showcase` (the only call site that needs the new behavior): pass
`exclude_hidden=True` to both calls:
```python
approved = jobs.list_jobs_by_public_status("approved", limit=limit, offset=offset, exclude_hidden=True)
...
"total": jobs.count_jobs_by_public_status("approved", exclude_hidden=True),
```
`get_showcase_job` (the direct permalink, `/showcase/{job_id}`) is left
completely untouched, per the confirmed scope decision above.

### 5. `backend/app/routes/admin.py` — two new actions

Mirrors the existing `approve`/`reject` endpoints' shape exactly (thin
route, admin-only via `get_current_admin_user`, 404/409 on bad state) but
simpler — this is a display toggle, not a money-moving transition, so it
uses the plain `jobs.update_job(job_id, public_hidden=...)` helper (no
row-locking needed, unlike `approve_public_job`/`reject_public_job` which
lock because they touch the wallet ledger):
```python
@router.post("/api/admin/public-jobs/{job_id}/hide")
def hide_admin_public_job(job_id: str, current_user: dict = Depends(get_current_admin_user)):
    job = jobs.get_job(job_id)
    if not job or job["public_status"] != "approved":
        raise HTTPException(status_code=404, detail="Job not found")
    jobs.update_job(job_id, public_hidden=True)
    return jobs.get_job(job_id)

@router.post("/api/admin/public-jobs/{job_id}/unhide")
def unhide_admin_public_job(job_id: str, current_user: dict = Depends(get_current_admin_user)):
    job = jobs.get_job(job_id)
    if not job or job["public_status"] != "approved":
        raise HTTPException(status_code=404, detail="Job not found")
    jobs.update_job(job_id, public_hidden=False)
    return jobs.get_job(job_id)
```
(Only meaningful for `"approved"` items — pending/rejected never appear on
the showcase regardless, so hiding them is a no-op the UI shouldn't even
offer.)

### 6. Frontend admin UI

Two gaps to close, both in the existing public-jobs admin area:

**`frontend/app/(app)/admin/public-jobs/page.tsx`** currently hardcodes
`status=pending` — there is today no way for admin to even *see* approved
items in this list (confirmed: once approved, an item is optimistically
spliced out of the pending view and never resurfaces here). Add a simple
status selector (Pending / Approved / Rejected tabs or a `<select>`,
defaulting to Pending to preserve today's landing behavior) that re-fetches
`GET /api/admin/public-jobs?status=...` with the chosen value — the
endpoint already supports all three, only the frontend never used anything
but the default. Add `public_hidden: boolean` to the local
`AdminPublicJobSubmission` type. When viewing the Approved tab, replace the
Approve/Reject row actions with a single Hide/Show toggle button (same
busy-disable-this-row-only UX already used for approve/reject), calling the
new `/hide`/`unhide` endpoints and updating that row's `public_hidden`
in local state on success (no need to splice it out — it should stay
visible in the admin's own approved list either way, just marked).

**`frontend/app/(app)/admin/public-jobs/[job_id]/page.tsx`**: this page
already has the one spot that renders per-item state for a non-pending job
(today just inert text: `Already approved.`) — add `public_hidden` to
`AdminPublicJobDetail` and, when `public_status === "approved"`, replace
that inert text with the current state (*"Visible on the homepage
showcase."* / *"Hidden from the homepage showcase."*) plus a Hide/Show
button, same confirm-then-call-then-update-local-state pattern already
used for Approve/Reject on this same page.

No marketing-site changes needed — `marketing/src/components/Showcase/showcase.ts`
already just fetches `GET /api/public/showcase` and renders whatever comes
back; the filtering happens entirely server-side.

## Explicitly out of scope

- A rejection-reason-style "why hidden" note — this is a simple on/off
  toggle, not a moderation decision needing justification.
- Any change to `/showcase/{job_id}`'s own availability — confirmed
  out of scope per the scope decision above.
- Touching the S3 archive in any way — hiding is a DB-only flag flip,
  explicitly separate from `delete_s3_archive` (which only ever runs on
  reject).
- Any change to `public_status`'s own semantics or the "approved is
  permanent" guarantee — unaffected by this feature.

## Verification

- `alembic upgrade head` inside the backend container; confirm existing
  approved rows read back `public_hidden = false` with no backfill needed
  (server_default handles it).
- `curl -X POST /api/admin/public-jobs/{id}/hide` (admin session token) on
  a real approved job, then `curl /api/public/showcase` and confirm that
  job no longer appears in the list, while `curl /api/public/showcase/{id}`
  still 200s with full content — then `/unhide` and confirm it reappears
  in the list.
- Confirm a non-admin session token gets 403 on both new endpoints, and a
  pending/rejected job's id gets 404 (hide is only valid for approved).
- Frontend: `npx tsc --noEmit`, `npm run build`; manually exercise the
  admin UI — switch the list's status tab to Approved, hide one item,
  confirm it's reflected in local state without a full refetch, visit its
  detail page and confirm the same state/toggle shows there, then unhide
  from the detail page and confirm the list reflects that too on next
  visit.
