"""Runs all pipeline stages in sequence against a local video file.

Usage:
    python run_pipeline.py /path/to/video.mp4

Stages requiring ASSEMBLYAI_API_KEY / ANTHROPIC_API_KEY are skipped with a
warning if the corresponding key isn't set in the environment (.env), so you
can still exercise the audio/frame extraction and heuristic filtering stages
without any API keys.
"""

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

import importlib

extract_audio = importlib.import_module("1_extract_audio").extract_audio
transcribe_diarize = importlib.import_module("2_transcribe").transcribe_diarize
extract_frames = importlib.import_module("3_extract_frames").extract_frames
filter_frames = importlib.import_module("4_filter_frames").filter_frames
judge_frames = importlib.import_module("5_vision_judge").judge_frames
segment_transcript = importlib.import_module("6_topic_segments").segment_transcript
match_frames_to_segments = importlib.import_module("7_assemble").match_frames_to_segments
assemble_document = importlib.import_module("7_assemble").assemble_document

load_dotenv()


def main(video_path: Path, output_dir: Path, transcription_engine: str, whisper_model: str):
    output_dir.mkdir(parents=True, exist_ok=True)

    print("== Stage 1: extract audio ==")
    audio_path = extract_audio(video_path, output_dir / "audio.wav")

    print("\n== Stage 2: transcribe + diarize ==")
    segments = []
    engine = transcription_engine
    if engine == "auto":
        if os.environ.get("ASSEMBLYAI_API_KEY"):
            engine = "assemblyai"
        elif os.environ.get("HF_TOKEN"):
            engine = "whisper-diarized"
        else:
            engine = "whisper"

    if engine == "assemblyai" and not os.environ.get("ASSEMBLYAI_API_KEY"):
        print("SKIPPED (no ASSEMBLYAI_API_KEY; pass --transcription-engine whisper to use local Whisper instead)")
    else:
        transcript = transcribe_diarize(audio_path, engine=engine, whisper_model=whisper_model)
        (output_dir / "transcript.json").write_text(json.dumps(transcript, indent=2))
        segments = transcript["segments"]
        print(f"{len(segments)} segments (engine: {engine})")

    print("\n== Stage 3: extract frames ==")
    frame_paths = extract_frames(video_path, output_dir / "frames_raw")
    print(f"{len(frame_paths)} raw frames")

    print("\n== Stage 4: filter frames ==")
    candidates = filter_frames(frame_paths)
    (output_dir / "candidate_frames.json").write_text(json.dumps(candidates, indent=2))
    print(f"{len(candidates)} candidates ({len(candidates) / max(len(frame_paths), 1):.1%} of raw)")

    print("\n== Stage 5: vision judge ==")
    accepted_frames = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        accepted_frames = judge_frames(candidates, segments)
        (output_dir / "accepted_frames.json").write_text(json.dumps(accepted_frames, indent=2))
    else:
        print("SKIPPED (no ANTHROPIC_API_KEY)")

    print("\n== Stage 6: topic segmentation ==")
    sections = []
    if segments and os.environ.get("ANTHROPIC_API_KEY"):
        sections = segment_transcript(segments)
        (output_dir / "sections.json").write_text(json.dumps(sections, indent=2))
    else:
        print("SKIPPED (no transcript and/or no ANTHROPIC_API_KEY)")

    print("\n== Stage 7: assemble document ==")
    if segments:
        matched_frames = match_frames_to_segments(accepted_frames, segments)
        doc_path = assemble_document(sections, segments, matched_frames, output_dir / "document")
        print(f"Document: {doc_path}")
    else:
        print("SKIPPED (no transcript)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video_path", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument(
        "--transcription-engine", choices=["auto", "assemblyai", "whisper", "whisper-diarized"], default="auto",
        help=(
            "auto (default): assemblyai if ASSEMBLYAI_API_KEY is set, else whisper-diarized "
            "if HF_TOKEN is set, else plain local whisper (no diarization)."
        ),
    )
    parser.add_argument(
        "--whisper-model", default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Used with the whisper or whisper-diarized engines.",
    )
    args = parser.parse_args()
    main(args.video_path, args.output_dir, args.transcription_engine, args.whisper_model)
