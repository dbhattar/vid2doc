"""Stage 0 (audio-only): download just the audio track from a YouTube video
as a local test input via yt-dlp -- for testing the audio-transcript
pipeline (POST /api/transcribe_audio) without needing a full video file.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def download_audio(url: str, output_path: Path, audio_format: str = "mp3") -> Path:
    if shutil.which("yt-dlp") is None:
        print("yt-dlp is not installed. Install it with: brew install yt-dlp", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "yt-dlp",
            "-x",
            "--audio-format", audio_format,
            # yt-dlp's postprocessor swaps in the final audio_format's
            # extension itself, so pass the template without one to avoid
            # ending up with a double extension like "test_audio.mp3.mp3".
            "-o", str(output_path.with_suffix("")),
            url,
        ],
        check=True,
    )
    return output_path.with_suffix(f".{audio_format}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--output", type=Path, default=Path("test_audio.mp3"))
    parser.add_argument(
        "--format", dest="audio_format", default="mp3",
        help="Output audio format (e.g. mp3, m4a, wav) -- must be one of the backend's AUDIO_EXTENSIONS",
    )
    args = parser.parse_args()

    result = download_audio(args.url, args.output, args.audio_format)
    print(f"Downloaded to {result}")
