"""Private, long-term S3 storage for finished jobs (replaces the 7-day local
retention for them -- see plan/private-job-storage-plan.md).

Only the app's own IAM identity can read the bucket. A user reaches their
files solely through the API, after the usual owner check, which either
streams a file or hands out a short-lived presigned URL for one exact key.
Every key is built from the job's recorded `storage_prefix` plus a relative
path that must appear in the job's `storage_files` list -- never from raw
request input -- so a crafted path can't reach another user's objects.

Layout under `jobs/<user_id>/<job_id>/` (`jobs/_meetings/<job_id>/` for a public
agency meeting's job, which has no owner but is kept the same way):
  document/...        document.md/.docx/.pdf, transcript.json, images/...
  source<ext>         the original upload
  video/final.mp4     video_gen deliverable (+ video/thumbnail.jpg)

A job without `storage_prefix` is a legacy local-only job and keeps working
off local disk until retention.py sweeps it."""

import contextlib
import hashlib
import mimetypes
import re
import shutil
import subprocess
import tempfile
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import archive_access, jobs
from .config import settings
from .s3_client import get_client, get_job_client

_UUID_RE = re.compile(r"^[0-9a-fA-F-]{32,36}$")
_UPLOAD_ATTEMPTS = 3

logger = logging.getLogger(__name__)


class JobStorageError(Exception):
    pass


def enabled() -> bool:
    return bool(settings.JOB_STORAGE_S3_BUCKET)


def prefix_for(user_id: str | None, job_id: str) -> str:
    """`jobs/<user_id>/<job_id>/`, or `jobs/_meetings/<job_id>/` for a job with
    no owner (a public agency meeting, see agency_ingest.py)."""
    if not _UUID_RE.match(str(job_id)) or (user_id is not None and not _UUID_RE.match(str(user_id))):
        raise JobStorageError("Refusing to build a storage prefix from a non-uuid id")
    return f"jobs/{user_id or '_meetings'}/{job_id}/"


def is_stored(job: dict) -> bool:
    return bool(job.get("storage_prefix"))


def has_file(job: dict, rel: str) -> bool:
    return rel in (job.get("storage_files") or [])


def has_doc_file(job: dict, name: str, check_archive: bool = True) -> bool:
    """Whether the job has document/<name>, wherever it lives: private S3, local
    disk, or (for a job retention swept) its showcase/chat archive. Only the
    last costs a network call, and `check_archive=False` skips it (list views)."""
    if is_stored(job):
        return has_file(job, f"document/{name}")
    doc_dir = settings.OUTPUT_DIR / job["id"] / "document"
    swept = check_archive and not (doc_dir / "document.md").exists() and archive_access.archive_prefix(job)
    return archive_access.archive_file_exists(job, name) if swept else (doc_dir / name).exists()


def read_doc_text(job: dict, name: str) -> str:
    """The text of document/<name>, wherever the job lives. Raises OSError if
    the file isn't there."""
    if is_stored(job):
        if not has_file(job, f"document/{name}"):
            raise FileNotFoundError(name)
        return read_bytes(job, f"document/{name}").decode()
    with doc_dir_for(job) as doc_dir:
        return (doc_dir / name).read_text()


def _key(job: dict, rel: str) -> str:
    """The object key for `rel`, only if the job actually stored that file."""
    if not is_stored(job) or not has_file(job, rel):
        raise FileNotFoundError(rel)
    return f"{job['storage_prefix']}{rel}"


def _collect_files(job: dict) -> dict[str, Path]:
    """Relative-path -> local file, for everything worth keeping."""
    job_id = job["id"]
    out_dir = settings.OUTPUT_DIR / job_id
    found: dict[str, Path] = {}
    doc_dir = out_dir / "document"
    if doc_dir.is_dir():
        for path in sorted(doc_dir.rglob("*")):
            if path.is_file():
                found[f"document/{path.relative_to(doc_dir).as_posix()}"] = path
    if job.get("job_type") == "video_gen":
        video_dir = out_dir / "video"
        for name in ("final.mp4", "thumbnail.jpg"):
            if (video_dir / name).is_file():
                found[f"video/{name}"] = video_dir / name
    source = job.get("source_path")
    if source and Path(source).is_file():
        found[f"source{Path(source).suffix or '.bin'}"] = Path(source)
    return found


def store_finished_job(job_id: str) -> bool:
    """Upload a finished job's files, record where they went, then free the
    local disk. Called by run_loop, never inline from the pipeline: the job
    completes and is served from the VPS first, S3 follows. All-or-nothing: on failure the partial objects are removed and
    the local files stay (so the job is still served, and retention.py still
    covers it). Never raises -- the job itself already succeeded."""
    if not enabled():
        return False
    try:
        job = jobs.get_job(job_id)
        if not job or is_stored(job) or job["status"] != "done":
            return False
        if job["job_type"] == "video_gen":
            video_dir = settings.OUTPUT_DIR / job_id / "video"
            if (video_dir / "final.mp4").is_file() and not (video_dir / "thumbnail.jpg").exists():
                make_thumbnail(video_dir / "final.mp4", video_dir / "thumbnail.jpg")
        files = _collect_files(job)
        if not files:
            return False
        prefix = prefix_for(job["user_id"], job_id)
        _upload_all(prefix, files)
        jobs.update_job(job_id, storage_prefix=prefix, storage_files=sorted(files))
        shutil.rmtree(settings.OUTPUT_DIR / job_id, ignore_errors=True)
        shutil.rmtree(settings.UPLOADS_DIR / job_id, ignore_errors=True)
        return True
    except Exception as e:
        print(f"Storing job {job_id} in S3 failed; keeping it on local disk: {e}", flush=True)
        return False


def _upload_all(prefix: str, files: dict[str, Path]) -> None:
    client = get_job_client()
    bucket = settings.JOB_STORAGE_S3_BUCKET
    uploaded: list[str] = []
    try:
        for rel, path in files.items():
            for attempt in range(_UPLOAD_ATTEMPTS):
                try:
                    client.upload_file(str(path), bucket, f"{prefix}{rel}")
                    break
                except Exception:
                    if attempt == _UPLOAD_ATTEMPTS - 1:
                        raise
                    time.sleep(2**attempt)
            uploaded.append(f"{prefix}{rel}")
    except Exception:
        for key in uploaded:
            with contextlib.suppress(Exception):
                client.delete_object(Bucket=bucket, Key=key)
        raise


# --- Reading -----------------------------------------------------------------


def read_bytes(job: dict, rel: str) -> bytes:
    obj = get_job_client().get_object(Bucket=settings.JOB_STORAGE_S3_BUCKET, Key=_key(job, rel))
    return obj["Body"].read()


def open_stream(job: dict, rel: str):
    """(chunk iterator, size, content type) for a stored file."""
    obj = get_job_client().get_object(Bucket=settings.JOB_STORAGE_S3_BUCKET, Key=_key(job, rel))
    content_type = mimetypes.guess_type(rel)[0] or "application/octet-stream"
    return obj["Body"].iter_chunks(chunk_size=64 * 1024), obj["ContentLength"], content_type


def presigned_url(job: dict, rel: str, filename: str | None = None) -> str:
    params = {"Bucket": settings.JOB_STORAGE_S3_BUCKET, "Key": _key(job, rel)}
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    return get_job_client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=settings.JOB_STORAGE_URL_EXPIRES_SECONDS
    )


def source_rel(job: dict) -> str | None:
    return next((r for r in job.get("storage_files") or [] if r.startswith("source.")), None)


def _download(job: dict, rel: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    get_job_client().download_file(settings.JOB_STORAGE_S3_BUCKET, _key(job, rel), str(dest))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextlib.contextmanager
def doc_dir_for(job: dict, writable: bool = False):
    """A local directory holding the job's document files: the real one for a
    legacy job, or a temp copy pulled from S3. With writable=True, files that
    were added or changed inside the block are uploaded again on exit."""
    if not is_stored(job):
        # A job still on local disk -- or one retention swept that has a
        # showcase/chat archive, which archive_access rebuilds on demand.
        yield archive_access.ensure_local(job)
        return
    tmp = Path(tempfile.mkdtemp(prefix=f"job-{job['id']}-"))
    doc_dir = tmp / "document"
    doc_dir.mkdir()
    try:
        before: dict[str, str] = {}
        for rel in job["storage_files"]:
            if rel.startswith("document/"):
                _download(job, rel, tmp / rel)
                before[rel] = _digest(tmp / rel)
        yield doc_dir
        if writable:
            client = get_job_client()
            files = set(job["storage_files"])
            for path in doc_dir.rglob("*"):
                if not path.is_file():
                    continue
                rel = f"document/{path.relative_to(doc_dir).as_posix()}"
                if before.get(rel) != _digest(path):
                    client.upload_file(str(path), settings.JOB_STORAGE_S3_BUCKET, f"{job['storage_prefix']}{rel}")
                    files.add(rel)
            if files != set(job["storage_files"]):
                jobs.update_job(job["id"], storage_files=sorted(files))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def fetch_source(job: dict) -> Path | None:
    """Put the original upload back on local disk (for retry). None if the job
    never stored one."""
    rel = source_rel(job)
    if not rel:
        return None
    dest = settings.UPLOADS_DIR / job["id"] / Path(rel).name
    if not dest.is_file():
        _download(job, rel, dest)
    return dest


def copy_to(job: dict, dest_bucket: str, dest_prefix: str, rels: list[str], rename: dict[str, str] | None = None) -> None:
    """Copies stored files into another bucket/prefix (chat and showcase
    archives). The two buckets belong to different IAM users, and a single S3
    copy request would need one identity with access to both, so each file is
    read with the job user and written with the showcase user, streamed through
    this process in chunks (nothing is held in memory or on disk). The content
    type is carried over. Raises on failure."""
    source = get_job_client()
    dest = get_client()
    for rel in rels:
        obj = source.get_object(Bucket=settings.JOB_STORAGE_S3_BUCKET, Key=_key(job, rel))
        body = obj["Body"]
        try:
            dest.upload_fileobj(
                body,
                dest_bucket,
                f"{dest_prefix}{(rename or {}).get(rel, rel)}",
                ExtraArgs={"ContentType": obj.get("ContentType") or mimetypes.guess_type(rel)[0] or "application/octet-stream"},
            )
        finally:
            body.close()


_ARCHIVE_DOC_FILES = ("document/document.md", "document/document.docx", "document/document.pdf", "document/transcript.json")


def copy_job_archive(job: dict, dest_bucket: str, dest_prefix: str) -> str:
    """Copy of the same file set public_jobs.upload_job_archive uploads
    (document files, images, source media), laid out the same way under
    `dest_prefix` (see copy_to for how). All-or-nothing; returns the source's
    filename relative to the prefix."""
    source = source_rel(job)
    if not source:
        raise JobStorageError(f"Job {job['id']} has no stored source media")
    rels = [r for r in job["storage_files"] if r in _ARCHIVE_DOC_FILES or r.startswith("document/images/")]
    rename = {r: r[len("document/"):] for r in rels}
    rels.append(source)
    copied: list[str] = []
    client = get_client()  # the destination bucket's identity, for cleaning up a partial copy
    try:
        for rel in rels:
            copy_to(job, dest_bucket, dest_prefix, [rel], rename)
            copied.append(f"{dest_prefix}{rename.get(rel, rel)}")
    except Exception:
        for key in copied:
            with contextlib.suppress(Exception):
                client.delete_object(Bucket=dest_bucket, Key=key)
        raise
    return source


def delete_job(job: dict) -> None:
    """Remove everything stored for a job. Best-effort, like the other S3
    cleanups: a failure leaves orphaned objects, never a broken job."""
    prefix = job.get("storage_prefix")
    if not prefix or not prefix.startswith("jobs/"):
        return
    try:
        client = get_job_client()
        bucket = settings.JOB_STORAGE_S3_BUCKET
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                client.delete_objects(Bucket=bucket, Delete={"Objects": objs})
    except Exception as e:
        print(f"Deleting S3 objects for job {job['id']} failed: {e}", flush=True)


def make_thumbnail(video: Path, dest: Path) -> None:
    """First frame of a video_gen result, generated before upload so no read
    path ever needs the video locally."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(Exception):
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video), "-ss", "0", "-vframes", "1", str(dest)],
            check=True,
            capture_output=True,
        )


# --- Background sync -----------------------------------------------------------


_RETRY_BACKOFF_SECONDS = 15 * 60
_retry_after: dict[str, float] = {}


def store_pending_jobs(batch: int = 10) -> int:
    """One sweep: push finished, local-only jobs to S3. Returns how many moved."""
    if not enabled():
        return 0
    created_from = None
    if settings.JOB_STORAGE_SYNC_FROM:
        created_from = datetime.fromisoformat(settings.JOB_STORAGE_SYNC_FROM)
        if created_from.tzinfo is None:
            created_from = created_from.replace(tzinfo=timezone.utc)
    settled_before = datetime.now(timezone.utc) - timedelta(seconds=settings.JOB_STORAGE_SETTLE_SECONDS)
    now = time.monotonic()
    for job_id in [j for j, until in _retry_after.items() if until <= now]:
        del _retry_after[job_id]
    moved = 0
    # Oldest first, and a job that just failed (or has nothing to upload) sits
    # out for a while, so a few bad jobs can't starve the rest of the queue.
    for job in jobs.list_jobs_pending_storage(settled_before, created_from, batch + len(_retry_after)):
        if job["id"] in _retry_after:
            continue
        if store_finished_job(job["id"]):
            moved += 1
        else:
            _retry_after[job["id"]] = now + _RETRY_BACKOFF_SECONDS
    return moved


def run_loop() -> None:
    """Blocking loop for a daemon thread in worker.py (its own thread because
    the main worker loop blocks for a job's full processing time)."""
    while True:
        try:
            moved = store_pending_jobs()
            if moved:
                logger.info("Moved %d finished job(s) to S3", moved)
        except Exception:
            logger.exception("Job storage sweep failed")
        time.sleep(settings.JOB_STORAGE_SYNC_SECONDS)
