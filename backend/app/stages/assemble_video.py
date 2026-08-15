"""Assemble per-scene clips (render_scene.py) into the final video
(job_type == "video_gen"): concat, burn in global captions, mux the original
narration audio. ffmpeg subprocess calls throughout, matching frames.py's/
audio.py's existing pattern -- no moviepy.

Captions are global, not per-scene: one captions.srt built from the full
merged transcript's absolute timestamps (segments already tile the whole
timeline contiguously, same as scenes do) and burned in one pass over the
*concatenated* video, rather than re-timestamped and burned per scene --
simpler, and avoids drift between adjacent scenes' caption timing.
"""

import subprocess
from pathlib import Path

from ..exceptions import PipelineError
from .render_scene import VIDEO_CODEC_ARGS


def _run_ffmpeg(args: list[str], description: str) -> None:
    try:
        subprocess.run(["ffmpeg", "-y", *args], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise PipelineError(f"ffmpeg {description} failed: {e.stderr.decode(errors='replace')}") from e


def _probe_duration(path: Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        raise PipelineError(f"ffprobe duration check failed: {e.stderr.decode(errors='replace')}") from e
    return float(result.stdout.decode().strip())


def concat_scenes(scene_clip_paths: list[Path], output_path: Path) -> Path:
    """ffmpeg concat demuxer with -c copy (no re-encode) -- valid because
    render_scene.py produces every clip with identical codec/fps/resolution/
    pixel format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_path = output_path.parent / "concat_list.txt"
    list_path.write_text("".join(f"file '{p.resolve()}'\n" for p in scene_clip_paths))
    _run_ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(output_path)],
        "scene concat",
    )
    return output_path


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def generate_srt(segments: list[dict], output_path: Path) -> Path:
    """One caption cue per merged transcript segment (phrase/utterance-level,
    not word-by-word -- transcribe.py's engines don't uniformly produce
    word-level timestamps, see plan's risks section)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(f"{_format_srt_timestamp(seg['start_ts'])} --> {_format_srt_timestamp(seg['end_ts'])}")
        lines.append(seg["text"])
        lines.append("")
    output_path.write_text("\n".join(lines))
    return output_path


def _escape_filter_path(path: Path) -> str:
    # ffmpeg filtergraph argument syntax requires escaping colons and single
    # quotes in a filename passed as a filter option.
    return str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def burn_captions(video_path: Path, srt_path: Path, output_path: Path) -> Path:
    """One re-encode pass -- the `subtitles` ffmpeg filter (via libass) burns
    the SRT directly into the video frames."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            "-i", str(video_path),
            "-vf", f"subtitles='{_escape_filter_path(srt_path)}'",
            *VIDEO_CODEC_ARGS,
            "-an",
            str(output_path),
        ],
        "caption burn-in",
    )
    return output_path


def mux_audio(video_path: Path, audio_path: Path, output_path: Path) -> Path:
    """Combines the captioned (silent) video with the original narration
    audio. Scenes tile the audio's own segment boundaries exactly, so the
    two tracks should already match almost exactly in length -- but pads
    whichever track is shorter (tpad for video, apad for audio) rather than
    relying on ffmpeg's coarser -shortest truncation alone, so a small
    rounding mismatch never clips the last fraction of a second of narration."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    video_duration = _probe_duration(video_path)
    audio_duration = _probe_duration(audio_path)
    video_filter = "null"
    if video_duration < audio_duration:
        video_filter = f"tpad=stop_mode=clone:stop_duration={audio_duration - video_duration:.3f}"

    _run_ffmpeg(
        [
            "-i", str(video_path),
            "-i", str(audio_path),
            "-filter_complex", f"[0:v]{video_filter}[v]",
            "-map", "[v]",
            "-map", "1:a",
            "-af", "apad",
            *VIDEO_CODEC_ARGS,
            "-c:a", "aac",
            "-shortest",
            str(output_path),
        ],
        "audio mux",
    )
    return output_path


def render_final_video(scene_clip_paths: list[Path], segments: list[dict], audio_path: Path, output_dir: Path) -> Path:
    """Orchestrates concat -> caption burn-in -> audio mux, returning the
    final .mp4 path."""
    concatenated = concat_scenes(scene_clip_paths, output_dir / "concatenated.mp4")
    srt_path = generate_srt(segments, output_dir / "captions.srt")
    captioned = burn_captions(concatenated, srt_path, output_dir / "captioned.mp4")
    final_path = mux_audio(captioned, audio_path, output_dir / "final.mp4")
    return final_path
