"""Owner-only chat-with-document: permanently enable chat on a completed
job for a flat one-time fee (archives document + transcript + source media
to a private S3 prefix), then ask questions grounded in that archive, with
answers citing back a timestamp in the original media when applicable. See
app/chat_jobs.py for the archive/LLM logic and app/billing.py's
charge_for_chat/refund_chat_charge for the one-time fee.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import billing, chat_jobs, jobs
from ..config import settings
from ..deps import get_current_user

router = APIRouter()


def _owned_job(job_id: str, current_user: dict) -> dict:
    job = jobs.get_job(job_id)
    if not job or job["user_id"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/api/jobs/{job_id}/chat/enable")
def enable_chat(job_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    """Irreversible -- there is no disable endpoint. Charges the flat fee
    BEFORE archiving (fails fast on insufficient balance before any S3
    work); if the archive then fails, the charge is refunded and nothing is
    persisted on the job."""
    job = _owned_job(job_id, current_user)
    if job["job_type"] not in ("video", "audio"):
        raise HTTPException(status_code=400, detail="Chat is only available for video and audio documents")
    if job["status"] != "done" or job["deleted_at"] is not None:
        raise HTTPException(status_code=400, detail="Only a completed, un-expired job can enable chat")
    if job["chat_enabled_at"] is not None:
        raise HTTPException(status_code=400, detail="Chat is already enabled for this job")

    try:
        charged_cents = billing.charge_for_chat(current_user["id"], job_id)
    except billing.InsufficientBalanceError as e:
        raise HTTPException(
            status_code=402, detail=f"Insufficient balance: need {e.required_cents}c, have {e.balance_cents}c"
        )

    doc_dir = (settings.OUTPUT_DIR / job_id / "document").resolve()
    try:
        archive = chat_jobs.enable_chat(job, doc_dir)
    except Exception:
        billing.refund_chat_charge(current_user["id"], job_id, charged_cents)
        raise HTTPException(status_code=502, detail="Could not enable chat for this job -- please try again")

    jobs.update_job(job_id, chat_enabled_at=datetime.now(timezone.utc), **archive)
    return {"chat_enabled": True}


@router.get("/api/jobs/{job_id}/chat/messages")
def list_chat_messages(job_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    _owned_job(job_id, current_user)
    return {"messages": chat_jobs.list_chat_messages(job_id)}


class ChatMessageRequest(BaseModel):
    message: str


@router.post("/api/jobs/{job_id}/chat/messages")
def post_chat_message(job_id: str, body: ChatMessageRequest, current_user: dict = Depends(get_current_user)) -> dict:
    job = _owned_job(job_id, current_user)
    if job["chat_enabled_at"] is None:
        raise HTTPException(status_code=400, detail="Chat is not enabled for this job")

    history = chat_jobs.list_chat_messages(job_id)
    chat_jobs.add_chat_message(job_id, "user", body.message)
    try:
        result = chat_jobs.answer_question(job, history, body.message)
    except chat_jobs.ChatUnavailableError:
        raise HTTPException(status_code=503, detail="Chat is temporarily unavailable -- no LLM provider configured")
    except Exception:
        raise HTTPException(status_code=502, detail="Could not get an answer -- please try again")

    return chat_jobs.add_chat_message(job_id, "assistant", result["answer"], result.get("citation_seconds"))


@router.get("/api/jobs/{job_id}/chat/media-url")
def get_chat_media_url(job_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    job = _owned_job(job_id, current_user)
    if job["chat_enabled_at"] is None:
        raise HTTPException(status_code=400, detail="Chat is not enabled for this job")
    return {"url": chat_jobs.generate_media_url(job), "expires_in": chat_jobs.MEDIA_URL_EXPIRES_SECONDS}
