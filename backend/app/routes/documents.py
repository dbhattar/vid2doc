import io
import json
import zipfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .. import archive_access, document_serving, job_storage, jobs
from ..deps import get_current_user

router = APIRouter()


def _owned_done_job(job_id: str, current_user: dict) -> dict:
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"] or job["status"] != "done":
        raise HTTPException(status_code=404, detail="Document not found")
    if archive_access.is_expired(job):
        raise HTTPException(status_code=404, detail="This document is no longer available")
    return job


# Registered before the {file_path:path} catch-all below -- Starlette matches
# routes in registration order, so this specific path must come first or the
# catch-all would swallow "bundle.zip" as a literal file_path lookup.
@router.get("/api/documents/{job_id}/bundle.zip")
def get_document_bundle(job_id: str, current_user: dict = Depends(get_current_user)):
    job = _owned_done_job(job_id, current_user)
    return document_serving.bundle_response(job, f"{job_id}.zip")


def _image_files(job: dict) -> list[tuple[str, bytes]]:
    """(name, bytes) of the images captured from the video, wherever the job lives."""
    if job_storage.is_stored(job):
        rels = sorted(r for r in job["storage_files"] if r.startswith("document/images/"))
        return [(r.rsplit("/", 1)[-1], job_storage.read_bytes(job, r)) for r in rels]
    with job_storage.doc_dir_for(job) as doc_dir:
        images_dir = doc_dir / "images"
        paths = sorted(p for p in images_dir.iterdir() if p.is_file()) if images_dir.is_dir() else []
        return [(p.name, p.read_bytes()) for p in paths]


@router.get("/api/documents/{job_id}/images.zip")
def get_images_zip(job_id: str, current_user: dict = Depends(get_current_user)):
    """Just the images captured from the video (the bundle has them plus the document)."""
    images = _image_files(_owned_done_job(job_id, current_user))
    if not images:
        raise HTTPException(status_code=404, detail="No images for this document")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in images:
            zf.writestr(name, data)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job_id}-images.zip"'},
    )


def _clock(seconds: float) -> str:
    seconds = int(max(0, seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


@router.get("/api/documents/{job_id}/transcript.txt")
def get_transcript_text(job_id: str, current_user: dict = Depends(get_current_user)):
    """The transcript as plain text: "[00:01:23] Speaker 1: ..." per turn,
    rendered from transcript.json (speaker names applied where it has them)."""
    job = _owned_done_job(job_id, current_user)
    try:
        data = json.loads(job_storage.read_doc_text(job, "transcript.json"))
        segments = data["segments"]
    except Exception:
        raise HTTPException(status_code=404, detail="Transcript not found")
    names = data.get("speaker_names") or {}
    lines = [
        f"[{_clock(float(s.get('start_ts') or 0))}] {names.get(s.get('speaker'), s.get('speaker') or 'Speaker')}: {s.get('text', '')}"
        for s in segments
    ]
    return StreamingResponse(
        io.BytesIO(("\n\n".join(lines) + "\n").encode()),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{job_id}-transcript.txt"'},
    )


@router.get("/api/documents/{job_id}/{file_path:path}")
def get_document_file(job_id: str, file_path: str, current_user: dict = Depends(get_current_user)):
    job = _owned_done_job(job_id, current_user)
    return document_serving.file_response(job, file_path)
