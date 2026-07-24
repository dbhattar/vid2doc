# Save to Drive: connect Google Drive, upload generated documents

## Context

Today, once a video/audio job finishes, Framewrite serves the generated
document set (document.md, best-effort document.docx/document.pdf, and any
extracted images) purely as authenticated download links
(`GET /api/documents/{job_id}/...`, see `backend/app/routes/documents.py`).
Users who want these files in their own Google Drive have to download
everything locally and manually re-upload it there themselves.

This feature removes that manual step: a user connects their Google Drive
account once (Settings > Integrations), and afterwards clicking "Save to
Drive" on any completed job uploads the full generated document set --
mirroring exactly what `bundle.zip` already bundles (document.md +
document.docx/pdf if they exist + images/*) -- into a new Drive folder named
after the job, in one action.

## 1. Data model

New table `google_drive_connections`, one row per user (1:1, enforced by a
unique `user_id`). Stores the **refresh token** (long-lived, needed to mint
new access tokens on every upload), the connected Google account email (for
display in Settings -- "Connected as you@gmail.com"), and bookkeeping
timestamps.

File: `backend/app/models.py` -- add after `ApiKey`:

```python
class GoogleDriveConnection(Base):
    """One row per user -- the OAuth refresh token that lets us mint short-
    lived Drive access tokens on demand for 'Save to Drive' uploads. The
    refresh token is stored encrypted (see app/crypto.py); nothing here is
    usable without ENCRYPTION_KEY."""

    __tablename__ = "google_drive_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False, index=True
    )
    google_email: Mapped[str] = mapped_column(String, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False)  # granted scope string, for future auditing
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

No relationship back-populate needed on `User` (mirrors how `Feedback`
doesn't bother with one either).

Migration: `backend/alembic/versions/0006_google_drive_connections.py`,
`revision = "0006"`, `down_revision = "0005"` (confirmed `0005_feedback.py`
is the current head), following that file's exact style (`postgresql.UUID`,
explicit index, symmetric `downgrade()`):

```python
def upgrade() -> None:
    op.create_table(
        "google_drive_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("google_email", sa.String(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_google_drive_connections_user_id", "google_drive_connections", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_google_drive_connections_user_id", table_name="google_drive_connections")
    op.drop_table("google_drive_connections")
```

## 2. Encryption utility (new -- nothing reusable exists)

`backend/app/api_keys.py`'s approach (SHA256 hash) is one-way by design and
cannot be reused: Drive uploads need the actual refresh token back, not just
proof of possession. No Fernet/AES utility exists anywhere in this codebase
today, so this plan adds one.

New file: `backend/app/crypto.py`

```python
from cryptography.fernet import Fernet, InvalidToken

from .config import settings

_fernet = Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Raises cryptography.fernet.InvalidToken if ENCRYPTION_KEY was rotated
    or the value is corrupt -- callers should treat that the same as a
    revoked connection (surface as 'reconnect Drive')."""
    return _fernet.decrypt(ciphertext.encode()).decode()
```

`backend/app/config.py` -- add:

```python
    # Symmetric key for encrypting stored OAuth refresh tokens (Fernet,
    # base64-encoded 32-byte key -- generate with
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

    # OAuth2 web client secret -- needed for the server-side auth-code
    # exchange for Drive access (GOOGLE_CLIENT_ID above is used for both
    # Sign-In-with-Google ID token verification AND this new flow, since
    # it's the same Google Cloud OAuth client).
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
```

The connect endpoint should 500 with a clear "Drive integration not
configured" message if `ENCRYPTION_KEY`/`GOOGLE_CLIENT_SECRET` are unset,
rather than crash confusingly inside `Fernet(b"")`.

Add `GOOGLE_CLIENT_SECRET=` and `ENCRYPTION_KEY=` to `backend/.env.example`
(and real values to `backend/.env`), documented in `backend/README.md`'s env
var table alongside the existing `GOOGLE_CLIENT_ID` row.

## 3. New Python dependencies

`backend/requirements.txt` -- add:

```
google-api-python-client==2.154.0
google-auth-oauthlib==1.2.1
google-auth-httplib2==0.2.0
cryptography==43.0.3
```

(`google-auth==2.36.0` already present is reused for token verification and
credentials refresh; the three new packages give the Drive v3 client, the
OAuth helpers, and stable `google.auth.transport.requests` integration.
`cryptography` backs Fernet in step 2.)

## 4. Backend: OAuth connect/disconnect/status endpoints

New file: `backend/app/routes/drive.py`, registered in `backend/app/main.py`
next to the other routers (`app.include_router(drive.router)`).

New module: `backend/app/drive_connections.py` (mirrors the
`api_keys.py`/`jobs.py` shape -- session-per-call helpers around the
`GoogleDriveConnection` model), with:

- `get_connection_for_user(user_id) -> dict | None`
- `save_connection(user_id, google_email, refresh_token, scope) -> dict`
  (upsert -- a user reconnecting replaces the row rather than erroring,
  since a stale/revoked refresh token is exactly why they'd reconnect)
- `delete_connection(user_id) -> bool`

Endpoints (all under `/api/drive`, all require the session-cookie/JWT
`get_current_user` dependency the same way other user-facing settings
routes do -- Drive connection management shouldn't be reachable via a
programmatic API key):

```
GET  /api/drive/status
  -> { connected: bool, google_email: str | null }

POST /api/drive/connect
  body: { code: str }   # one-time auth-code from useGoogleLogin({flow:'auth-code'})
  - Exchanges `code` for tokens via POST https://oauth2.googleapis.com/token
    (grant_type=authorization_code, client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET, redirect_uri="postmessage"
    -- what @react-oauth/google's popup auth-code flow uses by default).
  - Request scope="https://www.googleapis.com/auth/drive.file"
    (least-privilege: only files this app creates, not full Drive read
    access) and force prompt=consent from the frontend so a refresh_token
    is reliably returned even on reconnect.
  - Look up the connected account's email via the token response's
    id_token (google.oauth2.id_token.verify_oauth2_token, same helper
    already used in auth.py) -- include 'openid email' in the requested
    scope so the token endpoint returns one.
  - encrypt() the refresh_token, upsert via save_connection.
  -> { connected: true, google_email: str }

DELETE /api/drive/connect
  - delete_connection(current_user["id"]) -- best-effort also calls
    https://oauth2.googleapis.com/revoke?token=... server-side so the grant
    is actually revoked on Google's side, not just forgotten locally
    (wrap in try/except -- a revoke failure shouldn't block local
    disconnect).
  -> 204
```

## 5. Backend: the upload endpoint

New endpoint in `backend/app/routes/drive.py` (reuses
`documents._owned_done_doc_dir` from `backend/app/routes/documents.py` --
confirmed present at that name, line ~14 -- import it directly rather than
duplicating the ownership/status/soft-delete guard):

```
POST /api/jobs/{job_id}/drive-upload
```

Flow:
1. `doc_dir = documents._owned_done_doc_dir(job_id, current_user)` -- same
   404s as today's download endpoints for not-found/not-owned/not-done/
   retention-expired.
2. Load the user's `GoogleDriveConnection`; if none, `400` with "Connect
   Google Drive in Settings first" (frontend should prevent this via
   disabled state, but the backend must enforce it independently).
3. `decrypt()` the refresh token; build
   `google.oauth2.credentials.Credentials(None, refresh_token=...,
   client_id=..., client_secret=..., token_uri="https://oauth2.googleapis.com/token")`;
   call `credentials.refresh(google.auth.transport.requests.Request())` to
   mint a fresh access token. On `google.auth.exceptions.RefreshError`
   (revoked/expired grant) -> delete the now-dead connection row and return
   `409` with "Google Drive access was revoked -- please reconnect in
   Settings."
4. Build the Drive v3 client: `build("drive", "v3", credentials=credentials)`.
5. Create a folder named from the job title (fallback to job id, same
   fallback logic `displayTitle()` in `frontend/lib/jobs.ts` already uses)
   via `files().create(body={"name": ..., "mimeType":
   "application/vnd.google-apps.folder"})`.
6. Upload exactly what `bundle.zip` bundles today, plus docx/pdf when
   present -- same existence-check pattern as `build_job_response` in
   `backend/app/routes/status.py`:
   - `document.md` (always, if it exists)
   - `document.docx` if `(doc_dir / "document.docx").exists()`
   - `document.pdf` if `(doc_dir / "document.pdf").exists()`
   - every file under `doc_dir / "images"` if that dir exists
   Each via `files().create(body={"name": ..., "parents": [folder_id]},
   media_body=MediaFileUpload(str(path)))`.
7. Fetch the folder's `webViewLink` (`files().get(fileId=folder_id,
   fields="webViewLink")`) and return it.

Response: `{ "folder_url": "https://drive.google.com/drive/folders/..." }`

Error handling for step 6: wrap each upload in a per-file try/except for
`googleapiclient.errors.HttpError` -- retry transient failures via the
library's built-in backoff (`execute(num_retries=3)`); if a hard failure
happens partway through, still return the folder link with whichever files
succeeded rather than silently losing the whole action, and include a
`warnings: [...]` list of filenames that failed so the frontend can surface
a partial-success message.

## 6. Frontend: Settings > Integrations page

New file: `frontend/app/(app)/settings/integrations/page.tsx`, following
the exact structural pattern of
`frontend/app/(app)/settings/api-keys/page.tsx` (loading state, `apiFetch`,
401 -> `clearSession` + redirect to `/login`, error banner style).

State: `connected: boolean | null`, `googleEmail: string | null`, `busy`.

```tsx
useEffect(() => {
  apiFetch<{ connected: boolean; google_email: string | null }>("/api/drive/status")
    .then((d) => { setConnected(d.connected); setGoogleEmail(d.google_email); })
    .catch(...); // same 401 handling pattern as api-keys page
}, []);
```

Connect button uses `useGoogleLogin` from `@react-oauth/google`
(auth-code flow), wrapped in its own `<GoogleOAuthProvider clientId={...}>`
the same way `frontend/app/login/page.tsx` does:

```tsx
const login = useGoogleLogin({
  flow: "auth-code",
  scope: "https://www.googleapis.com/auth/drive.file",
  prompt: "consent",       // force refresh_token every time, incl. reconnect
  onSuccess: async ({ code }) => {
    const data = await apiFetch<{ connected: boolean; google_email: string }>(
      "/api/drive/connect",
      { method: "POST", body: JSON.stringify({ code }) }
    );
    setConnected(true);
    setGoogleEmail(data.google_email);
  },
  onError: () => setError("Google Drive connection failed. Please try again."),
});
```

Disconnect button: `DELETE /api/drive/connect`, then reset local state --
same `confirm()` pattern as the api-keys page's revoke action ("Disconnect
Google Drive? You'll need to reconnect before using Save to Drive again.").

Copy: "Connected as {googleEmail}" / "Not connected -- connect your Google
Drive to save generated documents there with one click."

## 7. Sidebar nav entry + icon

`frontend/components/icons.tsx` was just migrated to thin wrapper
components around `lucide-react` -- follow that exact pattern:

```tsx
import { HardDrive } from "lucide-react";
// ...
export function DriveIcon({ className }: IconProps) {
  return <HardDrive className={className} aria-hidden />;
}
```

`frontend/components/Sidebar.tsx` -- add to `NAV_LINKS`, right after API
keys (grouping it with the other settings entries):

```tsx
{ href: "/settings/integrations", label: "Integrations", Icon: DriveIcon },
```

## 8. Frontend: "Save to Drive" button

Drive-connection status is a per-user fact, not a per-job one -- fetch
`/api/drive/status` once (a small shared hook, e.g.
`frontend/lib/useDriveStatus.ts`) rather than threading a connected flag
through every job/document object returned by `GET /api/jobs`.

`frontend/components/DocumentCard.tsx` -- add a "Save to Drive" icon button
alongside the existing download icons, guarded by `!job.retention_expired`
like the others:

```tsx
{driveConnected ? (
  <button
    onClick={() => handleSaveToDrive(job.job_id)}
    disabled={savingToDrive}
    title="Save to Google Drive"
    className="rounded-md p-2 transition-colors hover:bg-brand-navy-soft hover:text-brand-amber-dark"
  >
    <DriveIcon className="h-6 w-6" />
  </button>
) : (
  <Link
    href="/settings/integrations"
    title="Connect Google Drive in Settings to enable this"
    className="rounded-md p-2 text-muted/40"
  >
    <DriveIcon className="h-6 w-6" />
  </Link>
)}
```

`handleSaveToDrive`:
```tsx
async function handleSaveToDrive(jobId: string) {
  setSavingToDrive(true);
  try {
    const { folder_url, warnings } = await apiFetch<{ folder_url: string; warnings?: string[] }>(
      `/api/jobs/${jobId}/drive-upload`, { method: "POST" }
    );
    window.open(folder_url, "_blank");
    if (warnings?.length) setError(`Saved, but some files failed: ${warnings.join(", ")}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      setError("Google Drive access was revoked -- please reconnect in Settings.");
      return;
    }
    setError(err instanceof ApiError ? err.message : "Save to Drive failed.");
  } finally {
    setSavingToDrive(false);
  }
}
```

Same button + handler added to
`frontend/app/(app)/dashboard/jobs/[id]/page.tsx`'s download button row
(icon + label style, matching its existing "Download Word"/"Download PDF"
buttons), gated the same way behind `driveConnected`.

`frontend/lib/jobs.ts`'s `Job` type needs no new fields for this (Drive
connection status is per-user, fetched separately, not per-job).

## 9. Error handling summary

| Case | Handling |
|---|---|
| Job not found / not owned / not done / soft-deleted | Reuse `documents._owned_done_doc_dir` -> existing 404s, no new logic |
| User has no Drive connection | `400` from `drive-upload`, frontend prevents via disabled/redirect state but backend enforces independently |
| Refresh token revoked/expired (`RefreshError`) | `409`, delete the stale connection row server-side, frontend prompts reconnect via Settings link |
| Drive API quota/rate limit (`HttpError` 403/429/503) | Retry via `execute(num_retries=3)`; if still failing, skip that file, continue others, report in `warnings` |
| Partial upload failure | Still return the folder link + `warnings` list rather than an opaque total failure |
| `ENCRYPTION_KEY` unset/misconfigured | `Fernet` raises at import or on decrypt -- surface as a 500 with an actionable message, never silently no-op |
| Stale encrypted token undecryptable (key rotated) | Treat identically to revoked -- delete connection, ask user to reconnect |

## Implementation sequencing

1. `backend/requirements.txt` deps + `backend/app/config.py` new settings +
   `backend/app/crypto.py`.
2. `backend/app/models.py` model +
   `backend/alembic/versions/0006_google_drive_connections.py`, run
   migration.
3. `backend/app/drive_connections.py` + `backend/app/routes/drive.py`
   (status/connect/disconnect first, upload endpoint second), register in
   `backend/app/main.py`.
4. `frontend/components/icons.tsx` (DriveIcon) +
   `frontend/components/Sidebar.tsx` (nav entry) +
   `frontend/app/(app)/settings/integrations/page.tsx`.
5. `frontend/lib/useDriveStatus.ts` (or equivalent shared fetch) + wire
   "Save to Drive" into `frontend/components/DocumentCard.tsx` and
   `frontend/app/(app)/dashboard/jobs/[id]/page.tsx`.
6. Env/docs: `backend/.env.example`, `backend/.env`, `backend/README.md`
   (new `GOOGLE_CLIENT_SECRET`/`ENCRYPTION_KEY` rows), plus Google Cloud
   Console config (enable Drive API, verify OAuth consent screen scopes
   include `drive.file`).

## Verification (manual end-to-end)

1. Set `GOOGLE_CLIENT_SECRET` and a generated `ENCRYPTION_KEY` in
   `backend/.env`; restart backend; run the new Alembic migration
   (`alembic upgrade head`).
2. Log into the app with a real Google account (existing Sign-In-with-Google
   flow, unaffected by this change).
3. Go to Settings > Integrations, click Connect, complete the Google
   consent screen (should show the Drive `drive.file` scope requested).
   Confirm the page flips to "Connected as <email>" and
   `GET /api/drive/status` reflects it.
4. Pick (or create) an already-`done` job. Click "Save to Drive" from both
   `DocumentCard` (dashboard/documents grid) and the job detail page.
   Confirm:
   - A new folder appears in the connected account's My Drive, named after
     the job title (or job id if untitled).
   - It contains `document.md`, `document.docx`/`document.pdf` (whichever
     exist on disk for that job), and an `images/` set matching what
     `bundle.zip` for the same job contains.
   - The returned `folder_url` opens directly to that folder.
5. Test disconnect: Settings > Integrations > Disconnect, confirm
   `GET /api/drive/status` flips back to not-connected, and access under
   the Google account's https://myaccount.google.com/permissions is
   actually revoked (not just forgotten locally).
6. Test the revoked/expired path: after manually revoking access from the
   Google account permissions page while still "connected" in the app's DB
   (to simulate a token going stale asynchronously), click "Save to Drive"
   again and confirm a `409` with a clear "reconnect" message, and that the
   stale local connection row was removed server-side.
7. Test the not-connected guard: as a user who never connected, confirm the
   Save to Drive button is disabled/redirects rather than crashing.

### Critical files
- `backend/app/models.py` -- new `GoogleDriveConnection` model
- `backend/alembic/versions/0006_google_drive_connections.py` -- new migration
- `backend/app/crypto.py` -- new Fernet encrypt/decrypt helper
- `backend/app/config.py` -- `ENCRYPTION_KEY`, `GOOGLE_CLIENT_SECRET`
- `backend/app/drive_connections.py`, `backend/app/routes/drive.py` -- new
- `backend/app/routes/documents.py` -- reuse `_owned_done_doc_dir`
- `backend/app/routes/status.py` -- existence-check pattern to mirror
- `backend/requirements.txt` -- new deps
- `frontend/components/icons.tsx`, `frontend/components/Sidebar.tsx`
- `frontend/app/(app)/settings/integrations/page.tsx` -- new
- `frontend/lib/useDriveStatus.ts` -- new shared hook
- `frontend/components/DocumentCard.tsx`,
  `frontend/app/(app)/dashboard/jobs/[id]/page.tsx` -- Save to Drive button
