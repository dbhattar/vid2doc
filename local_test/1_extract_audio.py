"""Stage 1: extract mono 16kHz audio from a video, for transcription."""

import argparse
import subprocess
from pathlib import Path


def extract_audio(video_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ar", "16000",
            "-ac", "1",
            "-vn",
            str(output_path),
        ],
        check=True,
    )
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video_path", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/audio.wav"))
    args = parser.parse_args()

    result = extract_audio(args.video_path, args.output)
    print(f"Audio extracted to {result}")
