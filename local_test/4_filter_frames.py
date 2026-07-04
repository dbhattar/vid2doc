"""Stage 4: cheap heuristic filtering of raw frames down to LLM candidates.

No API calls. Two gates, applied in temporal order:
  1. Dedup: perceptual hash vs the last *kept* frame (Hamming distance < 5 => drop).
  2. Content gate (OR of three signals) vs the last *accepted* frame:
     - OCR text density: >40 confident characters (catches slides/whiteboards/code)
     - Edge density: Canny edge-pixel ratio > 0.08 (catches diagrams/photos with no text)
     - Layout change: SSIM < 0.85 (catches progressive whiteboard fills, new visuals in general)
A frame becomes a candidate if it passes dedup AND at least one content signal fires.
"""

import argparse
import json
import re
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


def parse_timestamp(frame_path: Path) -> float:
    match = FRAME_TS_RE.search(frame_path.name)
    return float(match.group(1)) if match else 0.0


def ocr_char_count(gray_small: np.ndarray) -> int:
    data = pytesseract.image_to_data(gray_small, output_type=pytesseract.Output.DICT)
    return sum(
        len(text)
        for text, conf in zip(data["text"], data["conf"])
        if text.strip() and int(conf) > OCR_CONFIDENCE_THRESHOLD
    )


def edge_density(gray_small: np.ndarray) -> float:
    small = cv2.resize(gray_small, (320, 180))
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

        ocr_chars = ocr_char_count(gray_full)
        edges = edge_density(gray_full)

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
                    "timestamp": parse_timestamp(frame_path),
                    "ocr_chars": ocr_chars,
                    "edge_density": round(edges, 4),
                    "ssim_vs_prev_accepted": round(ssim_score, 4),
                    "gate_fired": {
                        "text": text_gate,
                        "edge": edge_gate,
                        "layout": layout_changed,
                    },
                }
            )

    return candidates


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/candidate_frames.json"))
    args = parser.parse_args()

    frame_paths = sorted(args.frames_dir.glob("frame_*.jpg"))
    if not frame_paths:
        raise SystemExit(f"No frames found in {args.frames_dir}")

    candidates = filter_frames(frame_paths)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(candidates, indent=2))

    print(f"Raw frames: {len(frame_paths)}")
    print(f"Candidates: {len(candidates)} ({len(candidates) / len(frame_paths):.1%} of raw)")
    print(f"Written to {args.output}")
