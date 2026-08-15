"""Render one silent video clip per scene (job_type == "video_gen") -- ffmpeg
subprocess calls only, no moviepy, matching frames.py/audio.py's existing raw
-ffmpeg pattern (smaller image, no ImageMagick dependency, and more precise
control over the zoompan/drawtext filter graphs than moviepy would give).

Every clip is produced with identical codec/fps/resolution/pixel format so
assemble_video.py's concat step needs no re-encode. Landscape/16:9 only in
v1 (see config.py's aspect_ratio note -- WIDTH/HEIGHT aren't yet
parameterized off the job's aspect_ratio column).

The zoompan Ken Burns effect below is a first-pass recipe, not a tuned one --
real footage/photos should be spot-checked for jitter before this ships;
see plan/audio-to-video-generation-plan.md's risks section.
"""

import subprocess
from pathlib import Path

from ..exceptions import PipelineError

WIDTH = 1920
HEIGHT = 1080
FPS = 30
# zoompan needs the source scaled well beyond target resolution first --
# zooming directly on a target-resolution image causes visible
# integer-rounding jitter as zoompan's per-frame crop window shifts by
# fractional pixels it has to round to whole pixels.
KEN_BURNS_UPSCALE_FACTOR = 2
KEN_BURNS_ZOOM_END = 1.15  # slow, subtle zoom-in over the scene's duration

VIDEO_CODEC_ARGS = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def _drawtext_filter(headline: str) -> str:
    # ffmpeg drawtext requires escaping literal backslashes, colons, and
    # single quotes in the text argument itself.
    escaped = headline.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return (
        f"drawtext=text='{escaped}':fontsize=64:fontcolor=white:"
        f"borderw=3:bordercolor=black@0.7:x=(w-text_w)/2:y=h-th-80"
    )


def _run_ffmpeg(args: list[str], description: str) -> None:
    try:
        subprocess.run(["ffmpeg", "-y", *args], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise PipelineError(f"ffmpeg {description} failed: {e.stderr.decode(errors='replace')}") from e


def _render_photo_clip(image_path: Path, duration: float, headline: str, output_path: Path) -> None:
    frames = max(1, int(duration * FPS))
    zoompan = (
        f"scale={WIDTH * KEN_BURNS_UPSCALE_FACTOR}:{HEIGHT * KEN_BURNS_UPSCALE_FACTOR},"
        f"zoompan=z='min(zoom+{(KEN_BURNS_ZOOM_END - 1) / frames:.6f},{KEN_BURNS_ZOOM_END})':"
        f"d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    )
    _run_ffmpeg(
        [
            "-loop", "1", "-i", str(image_path),
            "-t", f"{duration:.3f}",
            "-vf", f"{zoompan},{_drawtext_filter(headline)}",
            *VIDEO_CODEC_ARGS,
            "-an",
            str(output_path),
        ],
        "photo scene render",
    )


def _render_video_clip(video_path: Path, duration: float, headline: str, output_path: Path) -> None:
    filter_graph = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},{_drawtext_filter(headline)}"
    )
    _run_ffmpeg(
        [
            # Loops the stock clip if it's shorter than the scene; harmless
            # no-op if it's already longer (the -t below trims either way).
            "-stream_loop", "-1", "-i", str(video_path),
            "-t", f"{duration:.3f}",
            "-vf", filter_graph,
            *VIDEO_CODEC_ARGS,
            "-an",
            str(output_path),
        ],
        "video scene render",
    )


def _render_gradient_clip(duration: float, headline: str, output_path: Path) -> None:
    _run_ffmpeg(
        [
            "-f", "lavfi",
            "-i", f"color=c=0x2b2d42:s={WIDTH}x{HEIGHT}:d={duration:.3f}:r={FPS}",
            "-vf", _drawtext_filter(headline),
            *VIDEO_CODEC_ARGS,
            "-an",
            str(output_path),
        ],
        "gradient scene render",
    )


def render_scene_clip(scene: dict, media_path: str | None, output_path: Path) -> Path:
    """Renders one silent clip covering exactly scene["end_ts"] -
    scene["start_ts"] seconds, using whichever media_kind/candidate the user
    settled on at review time (media_path=None, or media_kind="none", means a
    plain gradient card)."""
    duration = scene["end_ts"] - scene["start_ts"]
    headline = scene.get("headline") or scene.get("title") or ""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    media_kind = scene.get("media_kind")
    if media_kind == "video" and media_path:
        _render_video_clip(Path(media_path), duration, headline, output_path)
    elif media_kind == "photo" and media_path:
        _render_photo_clip(Path(media_path), duration, headline, output_path)
    else:
        _render_gradient_clip(duration, headline, output_path)
    return output_path
