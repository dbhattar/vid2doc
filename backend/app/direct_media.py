"""A direct link to a video or audio file (an agency's own .mp4, a file on a
CDN) -> local file, so a recording can be imported without downloading and
re-uploading it. Same two-halves split as youtube.py: `fetch_metadata` is a
quick bounded call made in the API request (validates the link and reads the
length), `download_direct_media` does the slow transfer and is only called
from the worker (pipeline.py's _download_if_needed).

The server fetches whatever address it's given, so every request here is
guarded against being aimed at the internal network (SSRF): http(s) only, the
host must resolve to public addresses only, and redirects are followed by
hand so each hop is checked again. A link that opens a web page (a Zoom or
Teams share link, a YouTube-like player) is told apart by its content type and
refused with an explanation rather than saved as a broken "video".
"""

import ipaddress
import logging
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

from .media import probe_duration_seconds

logger = logging.getLogger(__name__)

_MAX_REDIRECTS = 5
_CONNECT_TIMEOUT_SECONDS = 10
_READ_TIMEOUT_SECONDS = 30
_PROBE_TIMEOUT_SECONDS = 45
# A whole recording can be gigabytes over a slow link; this bounds the transfer.
_DOWNLOAD_DEADLINE_SECONDS = 90 * 60
_CHUNK_BYTES = 1024 * 1024
_USER_AGENT = "Mozilla/5.0 (compatible; FramewriteImporter/1.0)"

_MEDIA_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".mpg", ".mpeg", ".ts", ".m4a", ".mp3", ".wav", ".aac", ".ogg", ".oga", ".flac", ".wma"}
# Some servers label every file as a generic binary stream.
_GENERIC_TYPES = {"application/octet-stream", "binary/octet-stream", "application/force-download", "application/x-download"}
_HTML_HINT = (
    "That link opens a web page, not a video file. Use the file's own download link "
    "(one that ends in .mp4 or similar), or download the recording and upload it."
)


class DirectMediaError(Exception):
    """Message is written to be safe to show the user directly."""


def is_direct_url(url: str) -> bool:
    """A plain http(s) URL with a host. Whether it really is media is only
    known once it's fetched -- see fetch_metadata."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def _check_public(url: str) -> None:
    """Raises unless the URL's host resolves only to public internet addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise DirectMediaError("That doesn't look like a link to a video file.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise DirectMediaError("Couldn't reach that address.")
    if not infos:
        raise DirectMediaError("Couldn't reach that address.")
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            raise DirectMediaError("Couldn't reach that address.")
        if not address.is_global:
            raise DirectMediaError("That address isn't allowed.")


def _open(url: str, method: str = "GET", extra_headers: dict | None = None) -> tuple[requests.Response, str]:
    """Issues the request, following redirects by hand with every hop checked.
    Returns the (streaming, unread) final response and its URL. Caller closes."""
    headers = {"User-Agent": _USER_AGENT, **(extra_headers or {})}
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        _check_public(current)
        try:
            response = requests.request(
                method, current, headers=headers, stream=True, allow_redirects=False,
                timeout=(_CONNECT_TIMEOUT_SECONDS, _READ_TIMEOUT_SECONDS),
            )
        except requests.RequestException:
            raise DirectMediaError("Couldn't reach that link -- check it and try again.")
        if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("Location"):
            current = urljoin(current, response.headers["Location"])
            response.close()
            continue
        return response, current
    raise DirectMediaError("That link redirects too many times.")


def _size(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def _filename(url: str) -> str:
    return unquote(Path(urlparse(url).path).name)


def _check_response(response: requests.Response, final_url: str) -> None:
    """Raises unless the response looks like a media file."""
    if response.status_code in (401, 403):
        raise DirectMediaError("That link needs a login or has expired -- it has to be publicly reachable.")
    if response.status_code == 404:
        raise DirectMediaError("That link doesn't exist (404).")
    if not response.ok:
        raise DirectMediaError(f"That link returned an error ({response.status_code}).")
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    has_media_extension = Path(urlparse(final_url).path).suffix.lower() in _MEDIA_EXTENSIONS
    if content_type.startswith(("video/", "audio/")) or content_type in _GENERIC_TYPES or (has_media_extension and not content_type.startswith("text/")):
        return
    if content_type in ("text/html", "application/xhtml+xml") or not content_type:
        raise DirectMediaError(_HTML_HINT)
    raise DirectMediaError("That link doesn't point to a video or audio file.")


def _probe_remote_duration(url: str) -> float | None:
    """The file's length read straight from its URL, or None if it can't be
    (a server without range support, a container with its index at the end)."""
    if shutil.which("ffprobe") is None:
        return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-protocol_whitelist", "http,https,tcp,tls,crypto", "-show_entries", "format=duration", "-of", "csv=p=0", url],
            capture_output=True, text=True, timeout=_PROBE_TIMEOUT_SECONDS,
        )
        value = float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None
    return value if value > 0 else None


def fetch_metadata(url: str, max_bytes: int | None = None) -> dict:
    """{"id", "title", "duration" (seconds or None), "size" (bytes or None),
    "url" (after redirects)}. Raises DirectMediaError for anything that isn't
    a reachable, public media file (or is over `max_bytes`)."""
    response, final_url = _open(url)
    try:
        _check_response(response, final_url)
        size = response.headers.get("Content-Length")
        size = int(size) if size and size.isdigit() else None
    finally:
        response.close()
    if max_bytes is not None and size is not None and size > max_bytes:
        raise DirectMediaError(f"That file is {_size(size)} -- over the {_size(max_bytes)} limit.")
    name = _filename(final_url)
    stem = Path(name).stem.replace("_", " ").replace("-", " ").strip()
    return {
        "id": final_url,
        "title": stem[:200] or None,
        "duration": _probe_remote_duration(final_url),
        "size": size,
        "url": final_url,
    }


def download_direct_media(
    url: str, upload_dir: Path, dest_path: Path, max_duration_seconds: float | None, max_bytes: int
) -> tuple[float, int]:
    """Downloads `url` to `dest_path` (the container is whatever it is; ffmpeg
    reads by content, so the name is only a name). Same validation and the same
    cleanup-on-failure contract as youtube.download_youtube_video: on any
    failure `upload_dir` is removed and DirectMediaError raised. Returns
    (duration_seconds, size_bytes). `max_duration_seconds=None` skips the cap."""
    try:
        response, final_url = _open(url)
        try:
            _check_response(response, final_url)
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise DirectMediaError(f"That file is over the {_size(max_bytes)} limit.")
            deadline = time.monotonic() + _DOWNLOAD_DEADLINE_SECONDS
            written = 0
            try:
                with open(dest_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=_CHUNK_BYTES):
                        written += len(chunk)
                        if written > max_bytes:
                            raise DirectMediaError(f"That file is over the {_size(max_bytes)} limit.")
                        if time.monotonic() > deadline:
                            raise DirectMediaError("The download took too long.")
                        f.write(chunk)
            except requests.RequestException:
                raise DirectMediaError("The download was interrupted -- please try again.")
        finally:
            response.close()

        if written == 0:
            raise DirectMediaError("The downloaded file was empty.")
        try:
            duration = probe_duration_seconds(dest_path)
        except (ValueError, OSError):
            raise DirectMediaError("That doesn't look like a playable video or audio file.")
        if max_duration_seconds is not None and duration > max_duration_seconds:
            raise DirectMediaError(f"Video duration {duration:.0f}s exceeds max of {max_duration_seconds}s")
        return duration, written
    except DirectMediaError:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(upload_dir, ignore_errors=True)
        logger.exception("Direct download failed for %s", url)
        raise DirectMediaError("Couldn't download that file.")
