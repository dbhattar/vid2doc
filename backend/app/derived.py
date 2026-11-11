"""Documents made from a finished video or audio job's transcript: notes, a
study guide or web research. The job first produces its own output (for video
the initial set of transcript, images and formatted document; for audio the
speaker-tagged transcript); each of these is then a child job (Job.parent_job_id)
that skips download, frames and transcription -- the worker reads the parent's
transcript from precomputed_segments.json, exactly like a live-recording
session's job does (see pipeline._transcribe_segments) -- and runs only the
text transformation (stages/transform.py).

Notes and a study guide are free for now; research makes paid web-search calls
so it is charged at its usual rate, with the usual refund if it fails.
"""

import json
import shutil
import uuid

from sqlalchemy.exc import IntegrityError

from . import archive_access, billing, jobs
from .config import settings
from .stages import transform

DERIVABLE = ("notes", "study_guide", "research")


class DerivedError(Exception):
    """Message is safe to show the user; `status` is the HTTP code to answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def cost_cents(transformation: str, duration_seconds: float | None) -> int:
    if transformation != "research" or not duration_seconds:
        return 0
    return billing.cost_for_duration_cents(duration_seconds, "research")


def check_parent(job: dict | None, user_id: str) -> dict:
    """The video document or audio transcript job a derived document can be made
    from. Raises DerivedError (404 for a job that isn't the caller's) otherwise."""
    if not job or job["user_id"] != user_id:
        raise DerivedError("Job not found", 404)
    is_audio = job["job_type"] == "audio"
    if (
        job["job_type"] not in ("video", "audio")
        or (not is_audio and (job.get("transformation") or "document") != "document")
        or job.get("parent_job_id")
    ):
        raise DerivedError("More documents can only be made from a video's full document or an audio transcript.")
    if job["status"] != "done" or job["deleted_at"] is not None:
        raise DerivedError("The recording has to finish processing first." if job["status"] != "done" else "This document has expired.")
    return job


def load_segments(parent: dict) -> list[dict]:
    """The parent's transcript segments, or raises DerivedError if its files
    are gone (retention sweeps them after a week; an archived job is rebuilt).
    An audio transcript's speaker names (set by the user or identified from the
    conversation) are applied, so the documents say "Jane Doe", not "Speaker 2"."""
    doc_dir = archive_access.ensure_local(parent)
    try:
        data = json.loads((doc_dir / "transcript.json").read_text())
        names = data.get("speaker_names") or {}
        segments = [{**s, "speaker": names.get(s.get("speaker"), s.get("speaker"))} for s in data["segments"]]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise DerivedError("This transcript is no longer available, so more documents can't be made from it.", 409)
    if not segments:
        raise DerivedError("This transcript is empty.", 409)
    return segments


def availability(parent: dict) -> tuple[bool, str | None]:
    """(can create more documents, why not)."""
    try:
        load_segments(parent)
    except DerivedError as e:
        return False, str(e)
    return True, None


def create(parent: dict, user_id: str, transformation: str, review_topics: bool = False) -> dict:
    """Creates and queues the child job; returns it. Raises DerivedError."""
    if transformation not in DERIVABLE:
        raise DerivedError(f"Unknown document type '{transformation}'. Allowed: {list(DERIVABLE)}")
    segments = load_segments(parent)
    if any(c["transformation"] == transformation and c["status"] not in ("failed", "cancelled") for c in jobs.list_child_jobs(parent["id"])):
        raise DerivedError("That document already exists for this recording.", 409)

    child_id = str(uuid.uuid4())
    duration = parent["duration_seconds"]
    cost = cost_cents(transformation, duration)
    try:
        billed_cents = billing.charge_for_job(user_id, child_id, duration, job_type="research") if cost else 0
    except billing.InsufficientBalanceError as e:
        raise DerivedError(
            f"Insufficient balance: this costs ${e.required_cents / 100:.2f}, you have ${e.balance_cents / 100:.2f}. "
            "Add funds at /settings/billing.",
            402,
        )

    # The transcript is in place before the job exists, so the worker can't
    # claim it without one.
    output_dir = settings.OUTPUT_DIR / child_id
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "precomputed_segments.json").write_text(json.dumps(segments))
        jobs.create_job(
            child_id,
            None,
            user_id=user_id,
            duration_seconds=duration,
            billed_cents=billed_cents,
            title=f"{transform.TITLE_PREFIX[transformation]}: {parent.get('title') or 'Untitled video'}"[:200],
            job_type="video",
            extract_frames=False,
            transformation=transformation,
            review_topics=review_topics and transformation == "research",
            parent_job_id=parent["id"],
        )
    except IntegrityError:
        # A concurrent request created the same document first.
        shutil.rmtree(output_dir, ignore_errors=True)
        billing.refund_job_charge(user_id, child_id, billed_cents)
        raise DerivedError("That document already exists for this recording.", 409)
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        billing.refund_job_charge(user_id, child_id, billed_cents)
        raise
    return jobs.get_job(child_id)
