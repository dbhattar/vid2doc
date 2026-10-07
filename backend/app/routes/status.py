from fastapi import APIRouter, Depends, HTTPException, Request

from .. import jobs, public_jobs
from ..config import settings
from ..deps import get_current_user

router = APIRouter()


def build_job_response(job: dict, request: Request) -> dict:
    """Shared by GET /api/get_status and GET /api/jobs -- a job list item has
    exactly the same shape as a single-job status response."""
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
        "share_url": f"{settings.FRONTEND_URL}/share/{job['share_token']}" if job.get("share_token") else None,
    }
    if job["job_type"] == "video":
        response["extract_frames"] = job["extract_frames"]
        # public_consent_refund_cents is the *live preview* amount before opt-in
        # (so the confirmation UI can show a real dollar figure, not a vague
        # percentage) -- once public_refund_cents is set (opt-in has happened),
        # that locked-in value takes over instead, per public_jobs.py's own
        # comment on why it's locked at opt-in rather than always recomputed.
        response["public_status"] = job["public_status"]
        response["public_consent_refund_cents"] = (
            job["public_refund_cents"]
            if job["public_refund_cents"] is not None
            else public_jobs.compute_refund_cents(job["billed_cents"])
        )
        if job["public_status"] == "approved":
            response["public_showcase_url"] = f"{settings.FRONTEND_URL}/showcase/{job['id']}"
    if job["job_type"] in ("video", "audio"):
        # Chat-with-document (see app/chat_jobs.py, routes/chat.py) --
        # unlike public_status above, this is a plain boolean: there's no
        # pending/rejected state (no admin review), and no un-enable path
        # once true. chat_enable_fee_cents is always the current flat fee
        # (not locked in anywhere, since there's nothing to lock -- unlike
        # the showcase refund, this doesn't vary per job), surfaced so the
        # opt-in confirm UI can show a real dollar figure.
        response["chat_enabled"] = job["chat_enabled_at"] is not None
        response["chat_enable_fee_cents"] = settings.CHAT_ENABLE_FEE_CENTS
    if job["status"] == "done" and job["deleted_at"] is not None:
        # Retention swept the files (see retention.py) -- still "done" in
        # the sense that conversion succeeded, but nothing left to serve.
        response["retention_expired"] = True
    elif job["status"] == "done" and job["job_type"] == "video_gen":
        base = str(request.base_url).rstrip("/")
        response["video_url"] = f"{base}/api/videos/{job['id']}/output.mp4"
        response["thumbnail_url"] = f"{base}/api/videos/{job['id']}/thumbnail.jpg"
    elif job["status"] == "done":
        base = f"{str(request.base_url).rstrip('/')}/api/documents/{job['id']}"
        doc_dir = settings.OUTPUT_DIR / job["id"] / "document"
        response["document_url"] = f"{base}/document.md"
        response["document_bundle_url"] = f"{base}/bundle.zip"
        # docx/pdf are best-effort exports -- only advertised if they actually rendered.
        if (doc_dir / "document.docx").exists():
            response["document_docx_url"] = f"{base}/document.docx"
        if (doc_dir / "document.pdf").exists():
            response["document_pdf_url"] = f"{base}/document.pdf"
        if (doc_dir / "transcript.json").exists():
            response["document_transcript_json_url"] = f"{base}/transcript.json"
    if job["status"] == "failed":
        response["error"] = job["error_message"]
    return response


@router.get("/api/get_status")
def get_status(job_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    return build_job_response(job, request)
