"""YouTube URL -> local video file. Split into two halves, called from two
different places for one reason: `fetch_metadata` is a fast, bounded network
call (a couple seconds, regardless of video length), so routes/youtube.py
calls it directly in the API request to validate the URL and duration cap
up front. `download_youtube_video` is slow and proportional to video length
(same as frame extraction/transcription elsewhere in the pipeline), so it's
only ever called from pipeline.py's _download_if_needed, in the worker --
never from an API request handler, which would otherwise block a web server
process for however long the download takes.
"""

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .config import settings
from .media import probe_duration_seconds

logger = logging.getLogger(__name__)

_ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com"}
_METADATA_TIMEOUT_SECONDS = 30
_DOWNLOAD_TIMEOUT_SECONDS = 20 * 60

# YouTube increasingly bot-checks requests from datacenter/VPS IPs ("Sign in
# to confirm you're not a bot") even for public videos -- cookies from a
# real logged-in session are yt-dlp's own recommended fix. No env var for
# this: just a conventional path under DATA_DIR (like backend/data/ itself,
# gitignored -- see .gitignore), placed there by hand since it has to come
# from a real Google account, never generated or fetched by this code. Only
# used if actually present, so dev/CI (no cookies file) is unaffected.
_COOKIES_FILE = settings.DATA_DIR / "youtube_cookies.txt"

# English only for now -- a hardcoded default rather than a new setting, same
# as WHISPER_MODEL etc. are kept simple (see config.py).
_CAPTION_LANG = "en"
_SRT_TIMESTAMP_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


class YoutubeDownloadError(Exception):
    """Message is written to be safe to show the user directly."""


def is_youtube_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _ALLOWED_HOSTS


def _run_yt_dlp(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    if shutil.which("yt-dlp") is None:
        raise YoutubeDownloadError("YouTube import isn't available right now -- try uploading the file directly.")
    if _COOKIES_FILE.is_file():
        # An authenticated (cookie-bearing) request makes yt-dlp prefer the
        # "web" client's format list, which YouTube increasingly gates behind
        # a PO token yt-dlp doesn't generate on its own -- every format gets
        # filtered out server-side, failing even a plain --dump-json with
        # "Requested format is not available." Falling back to the "tv"
        # client (still cookie-aware, not PO-token-gated as of this yt-dlp
        # version) works around it with no extra dependency. If YouTube
        # closes this gap too, the real fix is a PO token provider plugin
        # (e.g. bgutil-ytdlp-pot-provider, which needs a small companion
        # server) -- see https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide.
        args = ["--cookies", str(_COOKIES_FILE), "--extractor-args", "youtube:player_client=default,tv", *args]
    try:
        result = subprocess.run(["yt-dlp", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise YoutubeDownloadError("Timed out talking to YouTube -- please try again.")
    # yt-dlp's stderr (why it failed -- bot-check, geo-block, rate limit,
    # extractor breakage, etc.) is otherwise swallowed entirely, leaving only
    # the generic user-facing message in prod logs. Logged here rather than
    # at each call site since both fetch_metadata and download_youtube_video
    # go through this one function.
    if result.returncode != 0:
        logger.warning("yt-dlp exited %d for args %s: %s", result.returncode, args, result.stderr.strip())
    return result


def fetch_metadata(url: str) -> dict:
    """Fast (no download) -- just enough to validate the URL and enforce the
    duration cap before a job (and its charge) is even created."""
    result = _run_yt_dlp(["--dump-json", "--no-warnings", "--no-playlist", url], _METADATA_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise YoutubeDownloadError("Couldn't read that YouTube video -- check the link and try again.")
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise YoutubeDownloadError("Couldn't read that YouTube video -- check the link and try again.")


def list_feed_entries(feed_url: str, limit: int) -> list[dict]:
    """The newest `limit` videos of a channel or playlist, newest first, as
    {"id", "title", "url"}. Flat listing: no per-video detail (upload date,
    duration, live status) -- fetch_metadata gets that for the few the
    caller doesn't already know."""
    result = _run_yt_dlp(
        ["--flat-playlist", "--dump-json", "--no-warnings", "--playlist-end", str(limit), feed_url],
        _METADATA_TIMEOUT_SECONDS * 2,
    )
    if result.returncode != 0:
        raise YoutubeDownloadError("Couldn't read that channel or playlist.")
    entries = []
    for line in result.stdout.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        video_id = entry.get("id")
        if video_id:
            entries.append(
                {
                    "id": video_id,
                    "title": entry.get("title") or "",
                    "url": entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
                }
            )
    return entries


def download_youtube_video(
    url: str,
    upload_dir: Path,
    dest_path: Path,
    max_duration_seconds: int | None,
    max_upload_bytes: int,
    audio_only: bool = False,
) -> tuple[float, int]:
    """Downloads `url` to `dest_path` (capped at 720p, merged to mp4). Called
    from the worker only (see module docstring) -- the caller has already
    validated the reported duration via fetch_metadata before the job (and
    its charge) was created; this re-validates the actual downloaded file as
    defense-in-depth (metadata can lie, or disagree with what actually gets
    merged), same as media.save_upload does for direct uploads. On any
    validation failure, removes `upload_dir` entirely and raises
    YoutubeDownloadError. Returns (duration_seconds, size_bytes) on success.
    `max_duration_seconds=None` skips the duration cap entirely (admin
    bypass -- see pipeline.py's _download_if_needed). `audio_only` fetches
    just the audio track (falling back to the smallest combined format) --
    for a job that never looks at the picture, where a multi-hour 720p video
    would otherwise blow the size cap. ffmpeg reads it by content, so the
    ".mp4" name is only a name."""
    video_format = "bestaudio/worst" if audio_only else "bestvideo[height<=720]+bestaudio/best[height<=720]"
    base_args = ["-f", video_format, "--merge-output-format", "mp4", "--no-playlist"]
    # Best-effort caption fetch, piggybacked on this same download -- no extra
    # network round-trip. yt-dlp already prefers a manually-uploaded track over
    # an auto-generated one when both exist (confirmed directly, not assumed --
    # passing both flags together writes exactly one file, the better of the
    # two), and exits 0 with no file written if neither exists in this
    # language (also confirmed). But if YouTube rate-limits the caption
    # request itself (HTTP 429, seen on a VPS IP) yt-dlp fetches captions
    # before the media, exits 1 and downloads nothing -- so a failed attempt
    # is retried once without captions rather than failing a video that would
    # otherwise download fine. See get_downloaded_captions() below and
    # plan/youtube-captions-plan.md.
    caption_args = ["--write-subs", "--write-auto-subs", "--sub-langs", _CAPTION_LANG, "--sub-format", "srt"]
    result = _run_yt_dlp([*base_args, *caption_args, "-o", str(dest_path), url], _DOWNLOAD_TIMEOUT_SECONDS)
    if result.returncode != 0 and not dest_path.is_file():
        logger.warning("yt-dlp failed with captions requested, retrying without them")
        result = _run_yt_dlp([*base_args, "-o", str(dest_path), url], _DOWNLOAD_TIMEOUT_SECONDS)
    if result.returncode != 0 or not dest_path.is_file():
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise YoutubeDownloadError("Couldn't download that video -- it may be private, age-restricted, or removed.")

    size_bytes = dest_path.stat().st_size
    if size_bytes == 0:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise YoutubeDownloadError("Downloaded file was empty -- please try a different video.")
    if size_bytes > max_upload_bytes:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise YoutubeDownloadError(f"Video exceeds max upload size of {max_upload_bytes} bytes.")

    try:
        duration = probe_duration_seconds(dest_path)
    except (ValueError, OSError):
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise YoutubeDownloadError("Downloaded file looks corrupt -- please try again.")

    if max_duration_seconds is not None and duration > max_duration_seconds:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise YoutubeDownloadError(f"Video duration {duration:.0f}s exceeds max of {max_duration_seconds}s")

    return duration, size_bytes


def _parse_srt_timestamp(raw: str) -> float:
    match = _SRT_TIMESTAMP_RE.match(raw.strip())
    if not match:
        raise ValueError(f"Unrecognized SRT timestamp: {raw!r}")
    hours, minutes, seconds, millis = (int(g) for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def _parse_srt_segments(path: Path) -> list[dict]:
    """Parses an SRT file into the same {speaker, text, start_ts, end_ts}
    shape transcribe_diarize() produces -- speaker is always the literal
    string "Speaker" since captions carry no diarization info.

    Cues are read in file order, not sorted by timestamp: YouTube's
    auto-generated captions interleave two overlapping "rolling caption"
    timing lanes, so consecutive cues can legitimately overlap in time (cue
    3 can start before cue 1 ends) -- but the *text*, read sequentially in
    file order, comes out as clean prose with no duplication. Confirmed
    against real YouTube auto-captions before writing this (not assumed),
    see plan/youtube-captions-plan.md."""
    segments = []
    blocks = path.read_text(encoding="utf-8", errors="replace").strip().split("\n\n")
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        timestamp_idx = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timestamp_idx is None:
            continue
        start_raw, end_raw = (part.strip() for part in lines[timestamp_idx].split("-->"))
        text = " ".join(lines[timestamp_idx + 1 :]).strip()
        if not text:
            continue
        try:
            start_ts = _parse_srt_timestamp(start_raw)
            end_ts = _parse_srt_timestamp(end_raw)
        except ValueError:
            continue
        segments.append({"speaker": "Speaker", "text": text, "start_ts": start_ts, "end_ts": end_ts})
    return segments


def get_downloaded_captions(dest_path: Path) -> list[dict] | None:
    """Checks whether download_youtube_video's yt-dlp invocation also wrote
    a caption file alongside the video (it always requests one, best-effort
    -- see that function) and parses it if so. Returns None if no caption
    track was available for this video in _CAPTION_LANG, which is the
    normal case for many videos, not an error -- callers should fall back
    to full transcription in that case."""
    caption_path = dest_path.parent / f"{dest_path.stem}.{_CAPTION_LANG}.srt"
    if not caption_path.is_file():
        return None
    segments = _parse_srt_segments(caption_path)
    return segments or None
