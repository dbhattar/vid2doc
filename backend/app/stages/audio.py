import subprocess
from pathlib import Path

from ..exceptions import PipelineError


def extract_audio(video_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
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
    except subprocess.CalledProcessError as e:
        # check=True's own str(e) is just "exit status N" -- the useful part
        # (why ffmpeg actually failed) is in stderr, captured but otherwise
        # discarded. Surface it so it lands in the job's error_message
        # instead of a dead end.
        raise PipelineError(f"ffmpeg audio extraction failed: {e.stderr.decode(errors='replace')}") from e
    return output_path
