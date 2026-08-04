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
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .media import probe_duration_seconds

_ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com"}
_METADATA_TIMEOUT_SECONDS = 30
_DOWNLOAD_TIMEOUT_SECONDS = 20 * 60


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
    try:
        return subprocess.run(["yt-dlp", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise YoutubeDownloadError("Timed out talking to YouTube -- please try again.")


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


def download_youtube_video(
    url: str,
    upload_dir: Path,
    dest_path: Path,
    max_duration_seconds: int | None,
    max_upload_bytes: int,
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
    bypass -- see pipeline.py's _download_if_needed)."""
    result = _run_yt_dlp(
        [
            "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "--merge-output-format", "mp4",
            "--no-playlist",
            "-o", str(dest_path),
            url,
        ],
        _DOWNLOAD_TIMEOUT_SECONDS,
    )
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
