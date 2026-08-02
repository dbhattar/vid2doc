"""Anonymous "try it free" upload for the marketing site -- no login, no
wallet charge. In place of the billing gate, every submission requires a
verified Cloudflare Turnstile token and is capped by a per-IP daily quota, on
top of much tighter duration/size limits than the authenticated uploads in
routes/convert.py/routes/audio.py use. See plan/anonymous-trial-upload-plan.md.

Trial jobs are tagged by `user_id IS NULL` (see models.py) and never pass
through the interactive frame-review pause real users get (pipeline.py) --
they're hard-deleted entirely after a few hours (retention.py), not kept
around like real users' billing history.
"""

import io
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from .. import jobs
from ..config import settings
from ..media import save_upload, title_from_filename
from ..turnstile import verify_turnstile_token

router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_trial_allowed(turnstile_token: str, ip: str) -> None:
    if not verify_turnstile_token(turnstile_token, ip):
        raise HTTPException(status_code=403, detail="Verification failed -- please try again.")
    since = datetime.now(timezone.utc) - timedelta(days=1)
    if jobs.count_trial_jobs_from_ip_since(ip, since) >= settings.TRIAL_MAX_PER_IP_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Free trial limit reached ({settings.TRIAL_MAX_PER_IP_PER_DAY}/day) -- "
                "sign up at framewrite.cc to keep going."
            ),
        )


@router.post("/api/trial/convert_to_doc", status_code=202)
async def trial_convert_to_doc(
    request: Request,
    video: UploadFile = File(...),
    turnstile_token: str = Form(...),
):
    ip = _client_ip(request)
    _check_trial_allowed(turnstile_token, ip)

    ext = Path(video.filename or "").suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext or 'unknown'}'. Allowed: {sorted(settings.ALLOWED_EXTENSIONS)}",
        )

    job_id = str(uuid.uuid4())
    upload_dir = settings.UPLOADS_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / f"source{ext}"

    duration, size_bytes = await save_upload(
        video, upload_dir, dest_path, settings.TRIAL_MAX_UPLOAD_BYTES, settings.TRIAL_MAX_VIDEO_DURATION_SECONDS, kind="video"
    )

    jobs.create_job(
        job_id,
        str(dest_path),
        user_id=None,
        duration_seconds=duration,
        size_bytes=size_bytes,
        billed_cents=0,
        title=title_from_filename(video.filename or "", fallback="Untitled video"),
        job_type="video",
        client_ip=ip,
    )
    return {"job_id": job_id, "status": "queued"}


@router.post("/api/trial/transcribe_audio", status_code=202)
async def trial_transcribe_audio(
    request: Request,
    audio: UploadFile = File(...),
    turnstile_token: str = Form(...),
):
    ip = _client_ip(request)
    _check_trial_allowed(turnstile_token, ip)

    ext = Path(audio.filename or "").suffix.lower()
    if ext not in settings.AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext or 'unknown'}'. Allowed: {sorted(settings.AUDIO_EXTENSIONS)}",
        )

    job_id = str(uuid.uuid4())
    upload_dir = settings.UPLOADS_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / f"source{ext}"

    duration, size_bytes = await save_upload(
        audio, upload_dir, dest_path, settings.TRIAL_MAX_UPLOAD_BYTES, settings.TRIAL_MAX_AUDIO_DURATION_SECONDS, kind="audio"
    )

    jobs.create_job(
        job_id,
        str(dest_path),
        user_id=None,
        duration_seconds=duration,
        size_bytes=size_bytes,
        billed_cents=0,
        title=title_from_filename(audio.filename or "", fallback="Untitled audio"),
        job_type="audio",
        client_ip=ip,
    )
    return {"job_id": job_id, "status": "queued"}


def _owned_trial_job(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if not job or job["user_id"] is not None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _build_trial_job_response(job: dict, request: Request) -> dict:
    """Same shape as status.build_job_response, but document URLs point at
    the tokenless routes below instead of the authenticated /api/documents/
    ones. No retention_expired field -- trial jobs are hard-deleted (the row
    itself disappears), not soft-deleted, so an expired one just 404s."""
    response = {
        "job_id": job["id"],
        "status": job["status"],
        "progress_stage": job["progress_stage"],
        "job_type": job["job_type"],
        "title": job["title"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "duration_seconds": job["duration_seconds"],
        "billed_cents": job["billed_cents"],
    }
    if job["status"] == "done":
        base = f"{str(request.base_url).rstrip('/')}/api/trial/documents/{job['id']}"
        doc_dir = settings.OUTPUT_DIR / job["id"] / "document"
        response["document_url"] = f"{base}/document.md"
        response["document_bundle_url"] = f"{base}/bundle.zip"
        if (doc_dir / "document.docx").exists():
            response["document_docx_url"] = f"{base}/document.docx"
        if (doc_dir / "document.pdf").exists():
            response["document_pdf_url"] = f"{base}/document.pdf"
        if (doc_dir / "transcript.json").exists():
            response["document_transcript_json_url"] = f"{base}/transcript.json"
    if job["status"] == "failed":
        response["error"] = job["error_message"]
    return response


@router.get("/api/trial/status/{job_id}")
def trial_status(job_id: str, request: Request):
    job = _owned_trial_job(job_id)
    return _build_trial_job_response(job, request)


def _trial_done_doc_dir(job_id: str) -> Path:
    job = _owned_trial_job(job_id)
    if job["status"] != "done":
        raise HTTPException(status_code=404, detail="Document not found")
    return (settings.OUTPUT_DIR / job_id / "document").resolve()


# Registered before the {file_path:path} catch-all below, same reason as
# routes/documents.py's equivalent pair -- Starlette matches route
# registration order, so this specific path must come first.
@router.get("/api/trial/documents/{job_id}/bundle.zip")
def trial_document_bundle(job_id: str):
    doc_dir = _trial_done_doc_dir(job_id)
    md_path = doc_dir / "document.md"
    if not md_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(md_path, arcname="document.md")
        images_dir = doc_dir / "images"
        if images_dir.is_dir():
            for image_path in sorted(images_dir.iterdir()):
                if image_path.is_file():
                    zf.write(image_path, arcname=f"images/{image_path.name}")
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job_id}.zip"'},
    )


@router.get("/api/trial/documents/{job_id}/{file_path:path}")
def trial_document_file(job_id: str, file_path: str):
    doc_dir = _trial_done_doc_dir(job_id)
    full_path = (doc_dir / file_path).resolve()
    if not full_path.is_relative_to(doc_dir):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(full_path)
