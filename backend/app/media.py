"""Shared upload-handling helpers for both the video (routes/convert.py) and
audio (routes/audio.py) upload endpoints: streaming to disk with a size cap,
duration probing via ffprobe, and a filename-derived placeholder title.
"""

import re
import shutil
import subprocess
from pathlib import Path

from fastapi import HTTPException, UploadFile


def probe_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def title_from_filename(filename: str, fallback: str) -> str:
    """Immediate placeholder title, shown until (and unless) pipeline.py
    overwrites it with an LLM-generated one (video jobs only -- see
    pipeline.py's is_audio_job branch). Preserves the filename's original
    casing (e.g. "AP_Chem" -> "AP Chem") rather than title-casing, which
    would mangle acronyms."""
    stem = Path(filename).stem
    cleaned = re.sub(r"[_\-]+", " ", stem)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:200] if cleaned else fallback


async def save_upload(
    upload: UploadFile,
    upload_dir: Path,
    dest_path: Path,
    max_upload_bytes: int,
    max_duration_seconds: int,
    kind: str,
) -> float:
    """Streams `upload` to `dest_path`, enforcing a byte cap while writing
    and a duration cap after probing. On any validation failure, removes
    `upload_dir` entirely and raises HTTPException. Returns the probed
    duration in seconds on success. `kind` ("video"/"audio") only affects
    error text."""
    size = 0
    try:
        with open(dest_path, "wb") as f:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"{kind.capitalize()} exceeds max upload size of {max_upload_bytes} bytes",
                    )
                f.write(chunk)
    except HTTPException:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise

    if size == 0:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Uploaded {kind} file is empty")

    try:
        duration = probe_duration_seconds(dest_path)
    except (ValueError, OSError):
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Could not read {kind} file -- is it valid?")

    if duration > max_duration_seconds:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(
            status_code=400,
            detail=f"{kind.capitalize()} duration {duration:.0f}s exceeds max of {max_duration_seconds}s",
        )

    return duration
