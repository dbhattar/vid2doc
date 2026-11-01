"""Thin wrapper around the meeting-bot vendor (Recall.ai) -- everything
vendor-specific lives here so it can be swapped. Called from
routes/meetings.py only.

Written against Recall.ai's documented Bot API (POST /api/v1/bot/, status
webhooks delivered via Svix, recordings via the bot's media_shortcuts) but
not yet exercised against a live account -- verify the payload shapes marked
below with a real sandbox bot before relying on them.

The bot only *records* (mixed audio). We deliberately don't buy the vendor's
transcription: our own pipeline transcribes and diarizes the audio like any
other upload, which keeps the per-meeting cost down. The trade-off is that
speakers come out as "Speaker N" rather than the vendor's participant names.
"""

import base64
import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from .config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 20
# Svix rejects (and so do we) webhooks whose timestamp is further from now
# than this, which blocks replays of a captured request.
_WEBHOOK_TOLERANCE_SECONDS = 5 * 60


class MeetingBotError(Exception):
    """Message is written to be safe to show the user directly."""


def detect_platform(url: str) -> str | None:
    """"zoom" | "meet" | "teams", or None if this isn't a supported meeting
    link. https only -- this is also what keeps the bot (and our server)
    from being pointed at an arbitrary URL."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return None
    if host in ("zoom.us", "zoomgov.com") or host.endswith((".zoom.us", ".zoomgov.com")):
        return "zoom"
    if host == "meet.google.com":
        return "meet"
    if host in ("teams.microsoft.com", "teams.live.com"):
        return "teams"
    return None


def _api(path: str) -> str:
    return f"{settings.RECALL_API_BASE}/api/v1{path}"


def _headers() -> dict:
    return {"Authorization": f"Token {settings.RECALL_API_KEY}", "Content-Type": "application/json"}


def _require_configured() -> None:
    if not settings.RECALL_API_KEY:
        raise MeetingBotError("Meeting notetaker isn't available right now.")


def create_bot(meeting_url: str, join_at: datetime | None = None, bot_name: str | None = None) -> str:
    """Sends the bot into the meeting -- now, or at `join_at` (timezone-aware)
    for a scheduled meeting. Recall reserves a machine in advance for bots
    scheduled more than ~10 minutes out, which is why a scheduled bot is
    created up front rather than when its time arrives. Returns the vendor's
    bot id. `bot_name` is what attendees see; it defaults to MEETING_BOT_NAME."""
    _require_configured()
    body = {
        "meeting_url": meeting_url,
        "bot_name": bot_name or settings.MEETING_BOT_NAME,
        # No "transcript" provider on purpose -- see the module docstring.
        "recording_config": {"audio_mixed_mp3": {}},
        "automatic_leave": {"in_call_recording_timeout": settings.MEETING_MAX_SECONDS},
    }
    if join_at is not None:
        body["join_at"] = join_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        response = requests.post(_api("/bot/"), json=body, headers=_headers(), timeout=_TIMEOUT_SECONDS)
    except requests.RequestException:
        logger.exception("Recall create_bot request failed")
        raise MeetingBotError("Couldn't reach the notetaker service -- please try again.")
    if response.status_code == 507:
        raise MeetingBotError("No notetaker is free right now -- please try again in a minute.")
    if not response.ok:
        logger.warning("Recall create_bot returned %d: %s", response.status_code, response.text)
        raise MeetingBotError("Couldn't send the notetaker to that meeting -- check the link and try again.")
    return response.json()["id"]


def leave_meeting(bot_id: str) -> bool:
    """Asks the bot to leave an active call, falling back to deleting it if it
    hasn't joined yet (which is also how a scheduled bot is cancelled).
    Returns whether either call succeeded; never raises."""
    try:
        response = requests.post(_api(f"/bot/{bot_id}/leave_call/"), headers=_headers(), timeout=_TIMEOUT_SECONDS)
        if response.ok:
            return True
        return requests.delete(_api(f"/bot/{bot_id}/"), headers=_headers(), timeout=_TIMEOUT_SECONDS).ok
    except requests.RequestException:
        logger.exception("Recall leave_meeting failed for bot %s", bot_id)
        return False


def fetch_audio(bot_id: str, dest_path: Path, max_bytes: int) -> None:
    """Downloads the finished meeting's mixed audio to `dest_path`. Retrieves
    the bot, then follows the download URL its first recording's mixed-audio
    shortcut points at -- unverified path, see module docstring. Raises
    MeetingBotError (and leaves no partial file) if there's nothing to
    download or it's over `max_bytes`."""
    _require_configured()
    try:
        bot = requests.get(_api(f"/bot/{bot_id}/"), headers=_headers(), timeout=_TIMEOUT_SECONDS)
        bot.raise_for_status()
        download_url = None
        for recording in bot.json().get("recordings") or []:
            shortcut = (recording.get("media_shortcuts") or {}).get("audio_mixed") or {}
            download_url = (shortcut.get("data") or {}).get("download_url")
            if download_url:
                break
        if not download_url:
            raise MeetingBotError("No recording was captured for this meeting.")

        # The download URL is pre-signed -- no Authorization header. Streamed
        # to disk so a long meeting isn't held in memory.
        written = 0
        with requests.get(download_url, stream=True, timeout=60) as audio:
            audio.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in audio.iter_content(chunk_size=1024 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise MeetingBotError("The meeting recording is too large to process.")
                    f.write(chunk)
    except (requests.RequestException, ValueError):
        dest_path.unlink(missing_ok=True)
        logger.exception("Fetching audio failed for bot %s", bot_id)
        raise MeetingBotError("Couldn't download the meeting recording.")
    except MeetingBotError:
        dest_path.unlink(missing_ok=True)
        raise


def verify_webhook(body: bytes, headers) -> bool:
    """Svix signature check: HMAC-SHA256 over "{svix-id}.{svix-timestamp}.{body}"
    keyed with the base64 part of the "whsec_..." secret, compared against
    each space-separated "v1,<base64>" entry in svix-signature."""
    secret = settings.RECALL_WEBHOOK_SECRET
    msg_id = headers.get("svix-id")
    timestamp = headers.get("svix-timestamp")
    signatures = headers.get("svix-signature")
    if not (secret and msg_id and timestamp and signatures):
        return False
    try:
        if abs(time.time() - int(timestamp)) > _WEBHOOK_TOLERANCE_SECONDS:
            return False
        key = base64.b64decode(secret.removeprefix("whsec_"))
    except ValueError:
        return False
    signed = f"{msg_id}.{timestamp}.".encode() + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for candidate in signatures.split():
        version, _, sig = candidate.partition(",")
        if version == "v1" and hmac.compare_digest(sig, expected):
            return True
    return False
