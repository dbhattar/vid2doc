"""Stage 0: download a YouTube video as a local test input via yt-dlp.

Capped at 720p and merged to mp4 to keep the file small and fast for local
pipeline testing -- audio quality (for transcription) and frame legibility
(for slides/on-screen text) are unaffected by capping resolution here.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def download_video(url: str, output_path: Path, max_height: int = 720) -> Path:
    if shutil.which("yt-dlp") is None:
        print("yt-dlp is not installed. Install it with: brew install yt-dlp", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "yt-dlp",
            "-f", f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]",
            "--merge-output-format", "mp4",
            "-o", str(output_path),
            url,
        ],
        check=True,
    )
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--output", type=Path, default=Path("test_video.mp4"))
    parser.add_argument("--max-height", type=int, default=720, help="Max video resolution to download")
    args = parser.parse_args()

    result = download_video(args.url, args.output, args.max_height)
    print(f"Downloaded to {result}")
