"""Google Drive integration: connect/disconnect a user's Drive account, and
upload a completed job's generated documents there ("Save to Drive"). See
plan/google-drive-integration-plan.md for the full design rationale.
"""

import google.auth.exceptions
import google.auth.transport.requests
import google.oauth2.credentials
import google.oauth2.id_token
import requests
from fastapi import APIRouter, Depends, HTTPException
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from pydantic import BaseModel

from .. import crypto, drive_connections, jobs
from ..config import settings
from ..deps import get_current_session_user, get_current_user
from .documents import _owned_done_doc_dir

router = APIRouter()

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def _require_drive_configured():
    if not settings.GOOGLE_CLIENT_SECRET or not settings.ENCRYPTION_KEY:
        raise HTTPException(status_code=500, detail="Google Drive integration is not configured")


@router.get("/api/drive/status")
def get_drive_status(current_user: dict = Depends(get_current_session_user)):
    conn = drive_connections.get_connection_for_user(current_user["id"])
    return {"connected": conn is not None, "google_email": conn["google_email"] if conn else None}


class ConnectRequest(BaseModel):
    code: str


@router.post("/api/drive/connect")
def connect_drive(body: ConnectRequest, current_user: dict = Depends(get_current_session_user)):
    _require_drive_configured()

    response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": body.code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": "postmessage",  # matches @react-oauth/google's auth-code popup flow
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    if not response.ok:
        raise HTTPException(status_code=400, detail=f"Google token exchange failed: {response.text}")
    tokens = response.json()

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Google didn't return a refresh token -- if you've connected before, "
            "disconnect and remove Framewrite's access at https://myaccount.google.com/permissions, then try again.",
        )

    try:
        payload = google.oauth2.id_token.verify_oauth2_token(
            tokens["id_token"], google.auth.transport.requests.Request(), settings.GOOGLE_CLIENT_ID
        )
    except (ValueError, KeyError):
        raise HTTPException(status_code=400, detail="Invalid Google response -- please try connecting again")

    conn = drive_connections.save_connection(
        current_user["id"], payload["email"], refresh_token, tokens.get("scope", DRIVE_SCOPE)
    )
    return {"connected": True, "google_email": conn["google_email"]}


@router.delete("/api/drive/connect", status_code=204)
def disconnect_drive(current_user: dict = Depends(get_current_session_user)):
    conn = drive_connections.get_connection_for_user(current_user["id"])
    if conn:
        try:
            refresh_token = crypto.decrypt(conn["refresh_token_encrypted"])
            requests.post(GOOGLE_REVOKE_URL, params={"token": refresh_token}, timeout=15)
        except Exception:
            # Best-effort -- a revoke failure shouldn't block the local
            # disconnect; the user can also revoke it themselves at
            # https://myaccount.google.com/permissions.
            pass
    drive_connections.delete_connection(current_user["id"])


def _load_drive_client(user_id: str):
    """Returns a ready-to-use Drive v3 client for user_id, or raises the
    appropriate HTTPException (400 not connected, 409 revoked/stale --
    deleting the dead connection either way so the frontend's next status
    check reflects reality)."""
    conn = drive_connections.get_connection_for_user(user_id)
    if not conn:
        raise HTTPException(status_code=400, detail="Connect Google Drive in Settings first")

    try:
        refresh_token = crypto.decrypt(conn["refresh_token_encrypted"])
    except crypto.InvalidToken:
        drive_connections.delete_connection(user_id)
        raise HTTPException(status_code=409, detail="Google Drive access was revoked -- please reconnect in Settings")

    credentials = google.oauth2.credentials.Credentials(
        None,
        refresh_token=refresh_token,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        token_uri=GOOGLE_TOKEN_URL,
    )
    try:
        credentials.refresh(google.auth.transport.requests.Request())
    except google.auth.exceptions.RefreshError:
        drive_connections.delete_connection(user_id)
        raise HTTPException(status_code=409, detail="Google Drive access was revoked -- please reconnect in Settings")

    return build("drive", "v3", credentials=credentials)


@router.post("/api/jobs/{job_id}/drive-upload")
def upload_job_to_drive(job_id: str, current_user: dict = Depends(get_current_user)):
    doc_dir = _owned_done_doc_dir(job_id, current_user)
    job = jobs.get_job(job_id)
    drive = _load_drive_client(current_user["id"])

    folder_name = (job["title"] or "").strip() or f"Framewrite job {job_id}"
    folder = (
        drive.files()
        .create(body={"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}, fields="id")
        .execute()
    )
    folder_id = folder["id"]

    # Same file set as bundle.zip, plus docx/pdf when present -- same
    # existence-check pattern as build_job_response in routes/status.py.
    to_upload = []
    if (doc_dir / "document.md").is_file():
        to_upload.append(doc_dir / "document.md")
    if (doc_dir / "document.docx").is_file():
        to_upload.append(doc_dir / "document.docx")
    if (doc_dir / "document.pdf").is_file():
        to_upload.append(doc_dir / "document.pdf")
    images_dir = doc_dir / "images"
    if images_dir.is_dir():
        to_upload.extend(sorted(p for p in images_dir.iterdir() if p.is_file()))

    warnings = []
    for path in to_upload:
        try:
            media = MediaFileUpload(str(path))
            drive.files().create(
                body={"name": path.name, "parents": [folder_id]}, media_body=media, fields="id"
            ).execute(num_retries=3)
        except HttpError as e:
            warnings.append(path.name)
            print(f"Drive upload failed for job {job_id}, file {path.name}: {e}", flush=True)

    folder_info = drive.files().get(fileId=folder_id, fields="webViewLink").execute()
    return {"folder_url": folder_info["webViewLink"], "warnings": warnings}
