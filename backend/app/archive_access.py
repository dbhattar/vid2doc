"""Lets the owner's routes keep serving a job after retention.py has swept its
local files, when the job has an S3 archive (a showcase submission, see
public_jobs.py, or chat-with-document, see chat_jobs.py). The archive holds
the same document files the local output dir did, so a swept job's
`<OUTPUT_DIR>/<id>/document/` is rebuilt from it on first access and every
existing reader (documents, share, Drive, agents) works unchanged. The
rebuilt copy is just a cache: the next retention sweep removes it again.
"""

import logging
import os
from pathlib import Path

from .config import settings
from .s3_client import get_client as get_s3_client

logger = logging.getLogger(__name__)

_FLAT_FILES = ("document.md", "document.docx", "document.pdf", "transcript.json")


def archive_prefix(job: dict) -> str | None:
    """The job's S3 archive prefix, or None if it has none. A rejected
    showcase submission's archive is deleted (public_jobs.reject_public_job),
    so only pending/approved count."""
    if job.get("public_archive_prefix") and job.get("public_status") in ("pending", "approved"):
        return job["public_archive_prefix"]
    if job.get("chat_archive_prefix"):
        return job["chat_archive_prefix"]
    return None


def _doc_dir(job_id: str) -> Path:
    return (settings.OUTPUT_DIR / job_id / "document").resolve()


def archive_file_exists(job: dict, filename: str) -> bool:
    prefix = archive_prefix(job)
    if not prefix or not settings.PUBLIC_ARCHIVE_S3_BUCKET:
        return False
    try:
        get_s3_client().head_object(Bucket=settings.PUBLIC_ARCHIVE_S3_BUCKET, Key=f"{prefix}{filename}")
        return True
    except Exception:
        return False


def ensure_local(job: dict) -> Path:
    """Returns the job's local document dir, first rebuilding it from the
    archive if retention has removed it. A no-op for a job whose local files
    are intact or that has no archive. Never raises: on an S3 failure the
    caller just finds the files missing, as before."""
    doc_dir = _doc_dir(job["id"])
    prefix = archive_prefix(job)
    if (doc_dir / "document.md").is_file() or not prefix or not settings.PUBLIC_ARCHIVE_S3_BUCKET:
        return doc_dir
    try:
        _download(prefix, doc_dir)
    except Exception:
        logger.exception("Couldn't restore job %s from its archive", job["id"])
    return doc_dir


def _download(prefix: str, doc_dir: Path) -> None:
    client = get_s3_client()
    bucket = settings.PUBLIC_ARCHIVE_S3_BUCKET
    keys = [f"{prefix}{name}" for name in _FLAT_FILES if name != "document.md"]
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}images/"):
        keys.extend(obj["Key"] for obj in page.get("Contents", []))
    keys.append(f"{prefix}document.md")
    for key in keys:
        relative = key[len(prefix) :]
        target = (doc_dir / relative).resolve()
        if not relative or not target.is_relative_to(doc_dir):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + f".{os.getpid()}.part")
        try:
            client.download_file(bucket, key, str(partial))
        except Exception:
            partial.unlink(missing_ok=True)
            if relative == "document.md":
                raise  # without it there's nothing worth serving
            continue  # docx/pdf/transcript.json are optional
        # document.md lands last so a concurrent reader never sees it
        # without the files that were fetched before it.
        os.replace(partial, target)
