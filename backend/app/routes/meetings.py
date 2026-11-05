"""Meeting notetaker: a bot joins a pasted Zoom/Meet/Teams link, and when the
meeting ends its recording becomes a normal audio job, transcribed by our own
pipeline (summary, decisions and action items included -- see pipeline.py's
audio branch). The vendor-specific half lives in meeting_bots.py.

Flow: POST /api/meetings sends the bot -> the vendor calls
POST /api/meetings/webhook as the bot's status changes -> on bot.done we
download the audio, charge the wallet, and create the job.
"""

import json
import logging
import shutil
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import billing, emails, feature_flags, jobs, meeting_bots, meetings
from ..config import settings
from ..deps import get_current_user
from ..media import probe_duration_seconds

logger = logging.getLogger(__name__)
router = APIRouter()

# Wallet balance needed to send a bot at all: 30 minutes' worth. The real
# charge happens when the meeting ends and its true length is known.
MIN_BALANCE_SECONDS = 30 * 60

_PLATFORM_NAMES = {"zoom": "Zoom", "meet": "Google Meet", "teams": "Microsoft Teams"}


class CreateMeetingRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    title: str | None = Field(default=None, max_length=200)
    # What attendees see the bot called; blank means the default name.
    bot_name: str | None = Field(default=None, max_length=50)
    # When the bot should join; omit to send it now. Must carry a timezone
    # offset (the browser sends UTC).
    start_time: datetime | None = None
    # Email me when the notes are ready; omit to use the Settings default.
    notify_when_ready: bool | None = None
    # Planned length in minutes (5 minutes to 8 hours); the bot leaves after it.
    duration_minutes: int | None = Field(default=None, ge=5, le=480)


# How far ahead a meeting may be scheduled, and the slack that still counts as
# "now" (a start time a minute ago is just someone clicking Send slowly).
MAX_SCHEDULE_AHEAD = timedelta(days=30)
START_NOW_SLACK = timedelta(minutes=2)


def _clean_bot_name(raw: str | None) -> str | None:
    """Whitespace-collapsed, printable-only name, or None for the default. The
    name is shown to every attendee, so control/format characters (which can
    hide or reorder text) are refused rather than stripped."""
    name = " ".join((raw or "").split())
    if not name:
        return None
    if not name.isprintable():
        raise HTTPException(status_code=400, detail="That bot name has characters that can't be used.")
    return name


def _public(meeting: dict) -> dict:
    return {
        "id": meeting["id"],
        "platform": meeting["platform"],
        "title": meeting["title"],
        "scheduled_for": meeting["scheduled_for"],
        "status": meeting["status"],
        "duration_minutes": meeting["duration_minutes"],
        "notify_when_ready": meeting["notify_when_ready"],
        "job_id": meeting["job_id"],
        "error": meeting["error_message"],
        "created_at": meeting["created_at"],
    }


def _owned(meeting_id: str, current_user: dict) -> dict:
    try:
        uuid.UUID(meeting_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = meetings.get_meeting(meeting_id)
    if not meeting or meeting["user_id"] != str(current_user["id"]):
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


def get_meetings_user(current_user: dict = Depends(get_current_user)) -> dict:
    if not feature_flags.meetings_available_for(current_user):
        raise HTTPException(status_code=403, detail="Meeting notetaker isn't available on your account yet.")
    return current_user


@router.post("/api/meetings", status_code=201)
def create_meeting(body: CreateMeetingRequest, current_user: dict = Depends(get_meetings_user)):
    url = body.url.strip()
    platform = meeting_bots.detect_platform(url)
    if not platform:
        raise HTTPException(status_code=400, detail="That doesn't look like a Zoom, Google Meet or Teams link.")

    # Unspecified fields fall back to the user's Settings defaults; a blank
    # bot name is an explicit "use the app default".
    bot_name = _clean_bot_name(body.bot_name if body.bot_name is not None else current_user.get("default_bot_name"))
    notify_when_ready = (
        body.notify_when_ready if body.notify_when_ready is not None else current_user.get("notify_meeting_notes", True)
    )
    join_at = None
    if body.start_time is not None:
        if body.start_time.tzinfo is None:
            raise HTTPException(status_code=400, detail="The start time needs a timezone.")
        now = datetime.now(timezone.utc)
        if body.start_time > now + MAX_SCHEDULE_AHEAD:
            raise HTTPException(status_code=400, detail="You can schedule a meeting up to 30 days ahead.")
        if body.start_time >= now - START_NOW_SLACK:
            # Within the slack of "now" the bot is simply sent immediately.
            join_at = body.start_time if body.start_time > now + START_NOW_SLACK else None
        else:
            raise HTTPException(status_code=400, detail="That start time is in the past.")

    needed = billing.cost_for_duration_cents(MIN_BALANCE_SECONDS, "meeting")
    balance = billing.get_wallet_balance_cents(current_user["id"])
    if balance < needed:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Add at least ${needed / 100:.2f} to your wallet to send the notetaker "
                f"(you have ${balance / 100:.2f}). Add funds at /settings/billing."
            ),
        )

    title = (body.title or "").strip() or f"{_PLATFORM_NAMES[platform]} meeting"
    meeting = meetings.create_meeting(
        current_user["id"],
        platform,
        url,
        title,
        scheduled_for=join_at,
        bot_name=bot_name,
        notify_when_ready=notify_when_ready,
        duration_minutes=body.duration_minutes,
    )
    try:
        bot_id = meeting_bots.create_bot(
            url, join_at=join_at, bot_name=bot_name, duration_minutes=body.duration_minutes
        )
    except meeting_bots.MeetingBotError as e:
        meetings.update_meeting(meeting["id"], status="failed", error_message=str(e))
        raise HTTPException(status_code=502, detail=str(e))
    meetings.update_meeting(meeting["id"], vendor_bot_id=bot_id)
    return _public(meetings.get_meeting(meeting["id"]))


@router.get("/api/meetings")
def list_meetings(
    start: datetime | None = None,
    end: datetime | None = None,
    current_user: dict = Depends(get_meetings_user),
):
    """The 50 most recent meetings, or -- for the calendar -- every meeting
    dated within [start, end) (timezone-aware ISO times), up to 500."""
    if (start is not None and start.tzinfo is None) or (end is not None and end.tzinfo is None):
        raise HTTPException(status_code=400, detail="start and end need a timezone.")
    ranged = start is not None or end is not None
    rows = meetings.list_meetings_for_user(current_user["id"], limit=500 if ranged else 50, start=start, end=end)
    return {"meetings": [_public(m) for m in rows]}


class UpdateMeetingRequest(BaseModel):
    notify_when_ready: bool


@router.patch("/api/meetings/{meeting_id}")
def update_meeting(meeting_id: str, body: UpdateMeetingRequest, current_user: dict = Depends(get_meetings_user)):
    """Turn the "email me when the notes are ready" choice on or off, at any
    point up to the job finishing."""
    meeting = _owned(meeting_id, current_user)
    meetings.update_meeting(meeting["id"], notify_when_ready=body.notify_when_ready)
    return _public(meetings.get_meeting(meeting["id"]))


@router.delete("/api/meetings/{meeting_id}")
def leave_meeting(meeting_id: str, current_user: dict = Depends(get_meetings_user)):
    """Stops a meeting that's scheduled, still joining, or being recorded. A
    bot that was already recording leaves and the meeting is still processed
    (the vendor reports bot.done afterwards); one that never joined -- including
    a scheduled one, which is deleted at the vendor -- is just cancelled."""
    meeting = _owned(meeting_id, current_user)
    if meeting["status"] not in ("scheduled", "joining", "recording"):
        raise HTTPException(status_code=400, detail="This meeting has already ended.")
    if meeting["vendor_bot_id"] and not meeting_bots.leave_meeting(meeting["vendor_bot_id"]):
        # Marking it cancelled while the bot is still booked would let it join
        # (and bill) anyway, so surface the failure instead.
        raise HTTPException(status_code=502, detail="Couldn't reach the notetaker service -- please try again.")
    if meeting["status"] in ("scheduled", "joining"):
        meetings.update_meeting(meeting["id"], status="cancelled")
    return _public(meetings.get_meeting(meeting["id"]))


@router.post("/api/meetings/{meeting_id}/process")
def process_meeting(
    meeting_id: str, background_tasks: BackgroundTasks, current_user: dict = Depends(get_meetings_user)
):
    """Retries turning a captured meeting into a job -- for one stuck at
    awaiting_payment (after topping up) or whose recording download failed."""
    meeting = _owned(meeting_id, current_user)
    if meeting["job_id"] or meeting["status"] not in ("awaiting_payment", "failed") or not meeting["vendor_bot_id"]:
        raise HTTPException(status_code=400, detail="This meeting can't be processed.")
    meetings.update_meeting(meeting["id"], status="processing", error_message=None)
    background_tasks.add_task(finalize_meeting, meeting["id"])
    return _public(meetings.get_meeting(meeting["id"]))


# --- vendor webhook ---------------------------------------------------------

_STATUS_FOR_EVENT = {
    "bot.joining_call": "joining",
    "bot.in_waiting_room": "joining",
    "bot.in_call_not_recording": "joining",
    "bot.recording_permission_allowed": "joining",
    "bot.in_call_recording": "recording",
    "bot.call_ended": "processing",
}


@router.post("/api/meetings/webhook")
async def meetings_webhook(request: Request, background_tasks: BackgroundTasks):
    """Unauthenticated (the vendor calls it) -- trusted only via the Svix
    signature on the raw body. Replays of the same delivery are ignored with
    the same dedup table Stripe's webhook uses. Must answer fast (the vendor
    times out at 15s), so the audio download runs as a background task."""
    payload = await request.body()
    if not meeting_bots.verify_webhook(payload, request.headers):
        raise HTTPException(status_code=400, detail="Invalid webhook")
    try:
        event = json.loads(payload)
        name = event["event"]
        bot_id = event["data"]["bot"]["id"]
        sub_code = (event["data"].get("data") or {}).get("sub_code")
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid webhook")

    if not billing.claim_webhook_event(f"recall:{request.headers['svix-id']}"):
        return {"received": True}

    meeting = meetings.get_meeting_by_bot_id(bot_id)
    if not meeting or meeting["status"] in meetings.TERMINAL_STATUSES:
        return {"received": True}

    if name in _STATUS_FOR_EVENT:
        # "processing" must not be walked back to "joining"/"recording" by an
        # out-of-order delivery.
        if not (meeting["status"] == "processing" and _STATUS_FOR_EVENT[name] != "processing"):
            meetings.update_meeting(meeting["id"], status=_STATUS_FOR_EVENT[name])
    elif name == "bot.done":
        meetings.update_meeting(meeting["id"], status="processing")
        background_tasks.add_task(finalize_meeting, meeting["id"])
    elif name == "bot.fatal":
        reason = _fatal_message(sub_code)
        meetings.update_meeting(meeting["id"], status="failed", error_message=reason)
        _notify(meeting, "failed", reason)
    return {"received": True}


def _fatal_message(sub_code: str | None) -> str:
    if sub_code and "denied" in sub_code:
        return "The notetaker wasn't let into the meeting."
    return "The notetaker couldn't join or stay in the meeting."


def _notify(meeting: dict, kind: str, detail: str | None = None) -> None:
    emails.notify_meeting_issue(meeting["id"], kind, detail)


# A "meeting" shorter than this is a bot that joined an empty room.
MIN_MEETING_SECONDS = 10


def finalize_meeting(meeting_id: str) -> None:
    """Downloads a finished meeting's audio, charges the wallet for its real
    length, and queues a normal audio job -- the worker then transcribes,
    diarizes and writes the notes like for any upload. Runs as a background
    task, so it must record any failure on the meeting rather than raise."""
    meeting = meetings.get_meeting(meeting_id)
    if not meeting or meeting["job_id"] or not meeting["vendor_bot_id"]:
        return  # already handed to a job (webhook redelivery / double click)

    job_id = str(uuid.uuid4())
    upload_dir = settings.UPLOADS_DIR / job_id
    dest_path = upload_dir / "source.mp3"

    def fail(reason: str) -> None:
        shutil.rmtree(upload_dir, ignore_errors=True)
        meetings.update_meeting(meeting_id, status="failed", error_message=reason)
        _notify(meeting, "failed", reason)

    upload_dir.mkdir(parents=True, exist_ok=True)
    try:
        meeting_bots.fetch_audio(meeting["vendor_bot_id"], dest_path, settings.MAX_UPLOAD_BYTES)
        duration = probe_duration_seconds(dest_path)
    except meeting_bots.MeetingBotError as e:
        fail(str(e))
        return
    except (ValueError, OSError):
        fail("The meeting recording couldn't be read.")
        return
    if duration < MIN_MEETING_SECONDS:
        fail("The meeting was empty -- nobody spoke while the notetaker was there.")
        return

    try:
        billed_cents = billing.charge_for_job(meeting["user_id"], job_id, duration, job_type="meeting")
    except billing.InsufficientBalanceError as e:
        shutil.rmtree(upload_dir, ignore_errors=True)
        meetings.update_meeting(
            meeting_id,
            status="awaiting_payment",
            error_message=f"This meeting costs ${e.required_cents / 100:.2f}; add funds to get your notes.",
        )
        _notify(meeting, "payment", f"${e.required_cents / 100:.2f}")
        return

    jobs.create_job(
        job_id,
        str(dest_path),
        user_id=meeting["user_id"],
        duration_seconds=duration,
        size_bytes=dest_path.stat().st_size,
        billed_cents=billed_cents,
        title=meeting["title"],
        job_type="audio",
    )
    meetings.update_meeting(meeting_id, status="done", job_id=job_id, error_message=None)
