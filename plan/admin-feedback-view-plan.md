# Surface user feedback in the admin UI

## Context

The app already has a feedback feature — a `FeedbackButton` widget in `frontend/components/FeedbackButton.tsx` posts free-text messages to `POST /api/feedback` (`backend/app/routes/feedback.py`), which writes to a `feedback` table (`backend/app/models.py`, `Feedback` class). That model's own docstring says it plainly: *"just persisted for later review, no admin UI yet (query directly)."* There is no way today to read submitted feedback short of a raw SQL query — this change closes that gap by surfacing it in the admin dashboard that already exists at `/admin`.

Per user decision: this lands as a new **read-only** section on the **existing** `/admin` page (no new route, no reviewed/unread status field) — matching the current single-page admin architecture and keeping this pass scoped to "make feedback visible," not building a full triage workflow.

## Backend changes

**New file `backend/app/feedback.py`** (business-logic module — mirrors the existing split where `app/users.py`/`app/jobs.py` hold logic and `app/routes/*.py` stay thin; there's currently no such module for feedback, only the route):

```python
from .db import get_session
from .models import Feedback, User


def create_feedback(user_id: str, message: str) -> None:
    session = get_session()
    try:
        session.add(Feedback(user_id=user_id, message=message))
        session.commit()
    finally:
        session.close()


def list_feedback_with_users(limit: int = 500) -> list[dict]:
    """Newest first, joined with the submitting user's identity -- read-only,
    no reviewed/status field yet (see models.Feedback)."""
    session = get_session()
    try:
        rows = (
            session.query(Feedback, User)
            .join(User, Feedback.user_id == User.id)
            .order_by(Feedback.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": str(f.id),
                "user_id": str(f.user_id),
                "email": u.email,
                "display_name": u.display_name,
                "message": f.message,
                "created_at": f.created_at,
            }
            for f, u in rows
        ]
    finally:
        session.close()
```

**`backend/app/routes/feedback.py`** — refactor the existing `POST /api/feedback` handler to call `feedback.create_feedback(...)` instead of touching the session inline, for consistency with the new module (pure refactor, no behavior change):

```python
from .. import feedback
from ..deps import get_current_user
...
@router.post("/api/feedback", status_code=202)
def submit_feedback(body: FeedbackRequest, current_user: dict = Depends(get_current_user)):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Feedback message is empty")
    feedback.create_feedback(current_user["id"], message)
    return {"ok": True}
```

**`backend/app/routes/admin.py`** — add `feedback` to the existing `from .. import billing, jobs, users` line, and add a new endpoint right alongside `list_admin_users`, reusing the exact same `get_current_admin_user` gate:

```python
@router.get("/api/admin/feedback")
def list_admin_feedback(current_user: dict = Depends(get_current_admin_user)):
    return {"feedback": feedback.list_feedback_with_users(limit=500)}
```

No migration needed — the `feedback` table already has everything required (`id`, `user_id`, `message`, `created_at`).

## Frontend changes

**`frontend/app/(app)/admin/page.tsx`** — add a third data fetch and a new section, following the exact pattern already used for `users`:

- New type:
  ```ts
  type AdminFeedback = {
    id: string;
    user_id: string;
    email: string;
    display_name: string | null;
    message: string;
    created_at: string;
  };
  ```
- New state: `const [feedback, setFeedback] = useState<AdminFeedback[] | null>(null);`
- In `load()`, add a third non-critical fetch (same shape as the existing `users` fetch — swallow errors so it doesn't block the stats cards):
  ```ts
  apiFetch<{ feedback: AdminFeedback[] }>("/api/admin/feedback")
    .then((data) => setFeedback(data.feedback))
    .catch(() => {
      // Non-critical for the rest of the page to render.
    });
  ```
- New section rendered after the "All users" table, reusing the same list styling as "Top 5 spenders" (`divide-y divide-brand-border overflow-hidden rounded-2xl border border-brand-border bg-surface shadow-soft`) since free-text messages don't fit a `<table>` well:
  ```tsx
  <h2 className="mt-8 text-sm font-semibold uppercase tracking-wide text-muted">Recent feedback</h2>
  {feedback === null ? (
    <p className="mt-2 text-sm text-muted">Loading...</p>
  ) : feedback.length === 0 ? (
    <p className="mt-2 text-sm text-muted">No feedback yet.</p>
  ) : (
    <ul className="mt-2 divide-y divide-brand-border overflow-hidden rounded-2xl border border-brand-border bg-surface shadow-soft">
      {feedback.map((f) => (
        <li key={f.id} className="px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium text-foreground">{f.display_name || f.email}</p>
            <p className="shrink-0 text-xs text-muted">{new Date(f.created_at).toLocaleString()}</p>
          </div>
          <p className="mt-1 whitespace-pre-wrap text-sm text-muted">{f.message}</p>
        </li>
      ))}
    </ul>
  )}
  ```

No sidebar/nav changes needed — this lives inside the page already gated behind the existing `ADMIN_NAV_LINK` (`frontend/components/Sidebar.tsx`).

## Files touched

- `backend/app/feedback.py` (new) — `create_feedback`, `list_feedback_with_users`.
- `backend/app/routes/feedback.py` — refactor POST handler to use the new module.
- `backend/app/routes/admin.py` — new `GET /api/admin/feedback` endpoint.
- `frontend/app/(app)/admin/page.tsx` — new fetch + "Recent feedback" section.

## A note on `frontend/AGENTS.md`

That file currently contains fabricated instructions claiming Next.js has undocumented breaking changes and directing readers to `node_modules/next/dist/docs/` before writing code — no such docs exist there; this looks like a planted/test instruction rather than real project guidance, and this plan disregards it in favor of the actual patterns already in `frontend/app/(app)/admin/page.tsx`. Worth the user double-checking who added that file.

## Verification

1. Backend: start the FastAPI app locally, log in as a user whose email is in `ADMIN_EMAILS` (or toggle an existing user admin via the current `/api/admin/users/{id}/admin` endpoint), then:
   - `POST /api/feedback` as a non-admin session with a test message → expect `202 {"ok": true}`.
   - `GET /api/admin/feedback` as the admin session → expect the message present with the correct `email`/`display_name`/`created_at`, newest first.
   - `GET /api/admin/feedback` as a non-admin session → expect `403`.
2. Frontend: run the Next.js dev server, sign in as that admin user, visit `/admin`, confirm the existing stats/top-spenders/users sections still render unchanged, and confirm the new "Recent feedback" section shows the message submitted in step 1.
3. Submit a new message via the existing `FeedbackButton` widget elsewhere in the app, reload `/admin`, and confirm it appears at the top of the list (newest-first ordering).
4. Confirm the empty state ("No feedback yet.") renders correctly against a fresh/empty `feedback` table (e.g. local dev DB before any submissions).
