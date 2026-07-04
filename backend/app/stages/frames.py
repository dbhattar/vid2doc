"""Frame extraction (ffmpeg) and cheap heuristic filtering down to LLM candidates.

No API calls in this module. Two gates, applied in temporal order:
  1. Dedup: perceptual hash vs the last *kept* frame (Hamming distance < 5 => drop).
  2. Content gate (OR of three signals) vs the last *accepted* frame:
     - OCR text density: >40 confident characters (catches slides/whiteboards/code)
     - Edge density: Canny edge-pixel ratio > 0.08 (catches diagrams/photos with no text)
     - Layout change: SSIM < 0.85 (catches progressive whiteboard fills, new visuals in general)
A frame becomes a candidate if it passes dedup AND at least one content signal fires.
"""

import re
import subprocess
from pathlib import Path

import cv2
import imagehash
import numpy as np
import pytesseract
from PIL import Image
from skimage.metrics import structural_similarity as ssim

FRAME_TS_RE = re.compile(r"frame_t([\d.]+)\.jpg")

DEDUP_HAMMING_THRESHOLD = 5
OCR_CHAR_THRESHOLD = 40
OCR_CONFIDENCE_THRESHOLD = 60
EDGE_DENSITY_THRESHOLD = 0.08
SSIM_THRESHOLD = 0.85
COMPARE_SIZE = (320, 180)


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
        capture_output=True,
    )
    frames = sorted(output_dir.glob("frame_*.jpg"))

    renamed = []
    for i, frame in enumerate(frames):
        timestamp = i * interval_seconds
        new_path = output_dir / f"frame_t{timestamp:08.2f}.jpg"
        frame.rename(new_path)
        renamed.append(new_path)
    return renamed


def _parse_timestamp(frame_path: Path) -> float:
    match = FRAME_TS_RE.search(frame_path.name)
    return float(match.group(1)) if match else 0.0


def _ocr_char_count(gray_full: np.ndarray) -> int:
    data = pytesseract.image_to_data(gray_full, output_type=pytesseract.Output.DICT)
    return sum(
        len(text)
        for text, conf in zip(data["text"], data["conf"])
        if text.strip() and int(conf) > OCR_CONFIDENCE_THRESHOLD
    )


def _edge_density(gray_full: np.ndarray) -> float:
    small = cv2.resize(gray_full, (320, 180))
    edges = cv2.Canny(small, 100, 200)
    return float(np.count_nonzero(edges)) / edges.size


def filter_frames(frame_paths: list[Path]) -> list[dict]:
    last_kept_hash = None
    last_accepted_gray = None
    candidates = []

    for frame_path in frame_paths:
        img = Image.open(frame_path)
        phash = imagehash.phash(img)

        if last_kept_hash is not None and (phash - last_kept_hash) < DEDUP_HAMMING_THRESHOLD:
            continue
        last_kept_hash = phash

        gray_full = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
        gray_small = cv2.resize(gray_full, COMPARE_SIZE)

        ocr_chars = _ocr_char_count(gray_full)
        edges = _edge_density(gray_full)

        if last_accepted_gray is None:
            layout_changed = True
            ssim_score = 0.0
        else:
            ssim_score = float(ssim(gray_small, last_accepted_gray))
            layout_changed = ssim_score < SSIM_THRESHOLD

        text_gate = ocr_chars > OCR_CHAR_THRESHOLD
        edge_gate = edges > EDGE_DENSITY_THRESHOLD

        if text_gate or edge_gate or layout_changed:
            last_accepted_gray = gray_small
            candidates.append(
                {
                    "path": str(frame_path),
                    "timestamp": _parse_timestamp(frame_path),
                    "ocr_chars": ocr_chars,
                    "edge_density": round(edges, 4),
                    "ssim_vs_prev_accepted": round(ssim_score, 4),
                }
            )

    return candidates
