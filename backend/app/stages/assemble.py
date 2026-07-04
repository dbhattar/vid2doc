"""Match frames to transcript timestamps and assemble the final Markdown document.

Pure logic, no API calls.
"""

import shutil
import uuid
from pathlib import Path


def _find_containing_segment(segments: list[dict], timestamp: float) -> int:
    for i, seg in enumerate(segments):
        if seg["start_ts"] <= timestamp <= seg["end_ts"]:
            return i
    distances = [
        (min(abs(seg["start_ts"] - timestamp), abs(seg["end_ts"] - timestamp)), i)
        for i, seg in enumerate(segments)
    ]
    distances.sort()
    return distances[0][1] if distances else 0


def _apply_anchor_override(segments: list[dict], default_idx: int, anchor_text: str, timestamp: float) -> int:
    if not anchor_text.strip():
        return default_idx
    anchor_lower = anchor_text.strip().lower()
    for i, seg in enumerate(segments):
        if abs(seg["start_ts"] - timestamp) > 60:
            continue
        if anchor_lower in seg["text"].lower():
            return i
    return default_idx


def match_frames_to_segments(accepted_frames: list[dict], segments: list[dict]) -> list[dict]:
    matched = []
    for frame in accepted_frames:
        default_idx = _find_containing_segment(segments, frame["timestamp"])
        anchor_idx = _apply_anchor_override(segments, default_idx, frame.get("placement_anchor", ""), frame["timestamp"])
        matched.append({**frame, "anchor_segment_idx": anchor_idx})
    matched.sort(key=lambda f: f["timestamp"])
    return matched


def _format_timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def assemble_document(sections: list[dict], segments: list[dict], matched_frames: list[dict], output_dir: Path) -> Path:
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    frames_by_segment: dict[int, list[dict]] = {}
    for frame in matched_frames:
        frames_by_segment.setdefault(frame["anchor_segment_idx"], []).append(frame)

    lines = []
    if not sections:
        sections = [{
            "start_timestamp": segments[0]["start_ts"] if segments else 0,
            "end_timestamp": segments[-1]["end_ts"] if segments else 0,
            "heading": "Transcript", "summary": "",
        }]

    for section in sections:
        lines.append(f"## {section['heading']} `[{_format_timestamp(section['start_timestamp'])}]`")
        if section.get("summary"):
            lines.append(f"*{section['summary']}*")
        lines.append("")

        for idx, seg in enumerate(segments):
            if not (section["start_timestamp"] <= seg["start_ts"] < section["end_timestamp"]):
                continue
            lines.append(f"**{seg['speaker']}** ({_format_timestamp(seg['start_ts'])}): {seg['text']}")
            lines.append("")

            for frame in frames_by_segment.get(idx, []):
                image_id = f"{uuid.uuid4().hex[:8]}.jpg"
                shutil.copy(frame["path"], images_dir / image_id)
                lines.append(f"![{frame['caption']}](images/{image_id})")
                lines.append(f"*{frame['caption']}*")
                lines.append("")

    output_path = output_dir / "document.md"
    output_path.write_text("\n".join(lines))
    return output_path
