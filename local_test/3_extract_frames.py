"""Stage 3: extract frames from a video at a fixed interval.

Fixed 1-frame-per-`interval`-seconds sampling for this local test. The
adaptive "reduce sampling during talking-head-only stretches" optimization
from the full pipeline design is deliberately skipped here to keep this
script simple; it doesn't affect what stage 4 is validating.
"""

import argparse
import subprocess
from pathlib import Path


def extract_frames(video_path: Path, output_dir: Path, interval_seconds: float = 2.0) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    fps = 1 / interval_seconds
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"fps={fps}",
            "-qscale:v", "2",
            str(output_dir / "frame_%06d.jpg"),
        ],
        check=True,
    )
    frames = sorted(output_dir.glob("frame_*.jpg"))

    # Rename to embed each frame's actual timestamp for downstream stages.
    renamed = []
    for i, frame in enumerate(frames):
        timestamp = i * interval_seconds
        new_path = output_dir / f"frame_t{timestamp:08.2f}.jpg"
        frame.rename(new_path)
        renamed.append(new_path)
    return renamed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video_path", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("output/frames_raw"))
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between sampled frames")
    args = parser.parse_args()

    frames = extract_frames(args.video_path, args.output_dir, args.interval)
    print(f"Extracted {len(frames)} raw frames to {args.output_dir}")
