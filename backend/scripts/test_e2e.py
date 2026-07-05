#!/usr/bin/env python3
"""End-to-end test against a running vid2doc API: download a YouTube video,
submit it, poll until done, and save the resulting document locally.

Usage:
    python scripts/test_e2e.py "https://youtu.be/XXXX"
    python scripts/test_e2e.py "https://youtu.be/XXXX" --api-url http://my-vps:8000

Exercises the real HTTP API (auth, upload validation, job polling, document
fetch) against whatever LLM_PROVIDER/TRANSCRIPTION_ENGINE the running
containers are configured with -- this does not call any pipeline code
directly. Requires `yt-dlp` and `curl` on PATH.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def load_env_api_key() -> str | None:
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.strip().startswith("API_KEY="):
            return line.split("=", 1)[1].strip()
    return None


def download_video(url: str, dest: Path, max_height: int) -> Path:
    print(f"Downloading {url} ...")
    subprocess.run(
        [
            "yt-dlp",
            "-f", f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]",
            "--merge-output-format", "mp4",
            "-o", str(dest),
            url,
        ],
        check=True,
    )
    return dest


def submit_video(api_url: str, api_key: str, video_path: Path) -> str:
    print(f"Uploading {video_path.name} to {api_url}/api/convert_to_doc ...")
    result = subprocess.run(
        [
            "curl", "-s", "-w", "\n%{http_code}",
            "-X", "POST", f"{api_url}/api/convert_to_doc",
            "-H", f"X-API-Key: {api_key}",
            "-F", f"video=@{video_path}",
        ],
        capture_output=True, text=True, check=True,
    )
    body, status_code = result.stdout.rsplit("\n", 1)
    if status_code != "202":
        sys.exit(f"Upload failed ({status_code}): {body}")
    return json.loads(body)["job_id"]


def poll_status(api_url: str, api_key: str, job_id: str, interval: float, timeout: float) -> dict:
    deadline = time.time() + timeout
    last_stage = object()
    while time.time() < deadline:
        result = subprocess.run(
            ["curl", "-s", f"{api_url}/api/get_status?job_id={job_id}", "-H", f"X-API-Key: {api_key}"],
            capture_output=True, text=True, check=True,
        )
        status = json.loads(result.stdout)
        if status.get("progress_stage") != last_stage:
            last_stage = status.get("progress_stage")
            print(f"  status={status['status']} stage={last_stage}")
        if status["status"] in ("done", "failed"):
            return status
        time.sleep(interval)
    sys.exit(f"Job {job_id} did not finish within {timeout}s")


def _download(api_key: str, url: str, dest: Path) -> None:
    subprocess.run(["curl", "-s", "-o", str(dest), url, "-H", f"X-API-Key: {api_key}"], check=True)


def download_document(api_key: str, status: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    doc_path = output_dir / "document.md"
    _download(api_key, status["document_url"], doc_path)

    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)
    doc_base_url = status["document_url"].rsplit("/", 1)[0]
    for image_name in re.findall(r"\]\(images/([^)]+)\)", doc_path.read_text()):
        _download(api_key, f"{doc_base_url}/images/{image_name}", images_dir / image_name)

    for key, filename in (("document_docx_url", "document.docx"), ("document_pdf_url", "document.pdf")):
        if key in status:
            _download(api_key, status[key], output_dir / filename)
            print(f"  {filename} saved")

    return doc_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("youtube_url")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default=None, help="Defaults to API_KEY from backend/.env")
    parser.add_argument("--output-dir", type=Path, default=Path("e2e_output"))
    parser.add_argument("--max-height", type=int, default=480)
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=1800.0, help="Max seconds to wait for the job to finish")
    args = parser.parse_args()

    api_key = args.api_key or load_env_api_key()
    if not api_key:
        sys.exit("No API key found -- pass --api-key or set API_KEY in backend/.env")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    video_path = download_video(args.youtube_url, args.output_dir / "source.mp4", args.max_height)

    job_id = submit_video(args.api_url, api_key, video_path)
    print(f"Job submitted: {job_id}")

    status = poll_status(args.api_url, api_key, job_id, args.poll_interval, args.timeout)
    if status["status"] == "failed":
        sys.exit(f"Job failed: {status.get('error')}")

    doc_path = download_document(api_key, status, args.output_dir)
    print(f"\nDocument saved to {doc_path}")


if __name__ == "__main__":
    main()
