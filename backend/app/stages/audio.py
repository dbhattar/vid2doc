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
        capture_output=True,
    )
    return output_path
