"""Stage 2: transcribe (+ diarize) audio.

Three engines:
  - assemblyai (default): hosted API, transcription + real speaker diarization.
    Requires ASSEMBLYAI_API_KEY in the environment (see .env.example).
  - whisper: local openai-whisper model, no API key needed. Does NOT diarize
    -- every segment is labeled with a single placeholder speaker.
  - whisper-diarized: local openai-whisper for transcription + pyannote.audio
    for speaker diarization, merged by timestamp overlap. Real speaker labels
    with no hosted API, but needs a Hugging Face token (see .env.example) and
    is slower (two full passes over the audio).
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PYANNOTE_MODEL = "pyannote/speaker-diarization-3.1"


def transcribe_assemblyai(audio_path: Path) -> dict:
    import assemblyai as aai

    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        print(
            "ASSEMBLYAI_API_KEY is not set. Get one at https://www.assemblyai.com/, "
            "add it to local_test/.env, then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    aai.settings.api_key = api_key
    config = aai.TranscriptionConfig(speaker_labels=True)
    transcript = aai.Transcriber().transcribe(str(audio_path), config)

    if transcript.status == aai.TranscriptStatus.error:
        print(f"Transcription failed: {transcript.error}", file=sys.stderr)
        sys.exit(1)

    segments = [
        {
            "speaker": utt.speaker,
            "text": utt.text,
            "start_ts": utt.start / 1000,
            "end_ts": utt.end / 1000,
        }
        for utt in transcript.utterances
    ]
    return {"segments": segments}


def _load_whisper(model_size: str):
    try:
        import whisper
    except ImportError:
        print(
            "openai-whisper is not installed. Install it with: pip install openai-whisper",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Loading local Whisper model '{model_size}' (first run downloads the weights)...")
    return whisper.load_model(model_size)


def transcribe_whisper_local(audio_path: Path, model_size: str = "base") -> dict:
    model = _load_whisper(model_size)
    result = model.transcribe(str(audio_path), fp16=False, verbose=False)

    segments = [
        {
            "speaker": "Speaker",  # no diarization available locally
            "text": seg["text"].strip(),
            "start_ts": seg["start"],
            "end_ts": seg["end"],
        }
        for seg in result["segments"]
    ]
    return {"segments": segments}


def transcribe_whisper_diarized(audio_path: Path, model_size: str = "base") -> dict:
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        print(
            "pyannote.audio is not installed. Install it with: pip install pyannote.audio",
            file=sys.stderr,
        )
        sys.exit(1)

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print(
            "HF_TOKEN is not set. Accept the model terms at "
            "https://huggingface.co/pyannote/speaker-diarization-3.1 and "
            "https://huggingface.co/pyannote/segmentation-3.0, generate a token at "
            "https://huggingface.co/settings/tokens, then add it to local_test/.env.",
            file=sys.stderr,
        )
        sys.exit(1)

    model = _load_whisper(model_size)
    result = model.transcribe(str(audio_path), fp16=False, word_timestamps=True, verbose=False)

    print(f"Loading pyannote pipeline '{PYANNOTE_MODEL}' (first run downloads the weights)...")
    diarization_pipeline = Pipeline.from_pretrained(PYANNOTE_MODEL, token=hf_token)

    print("Running diarization (this can take a while on CPU)...")
    diarization_output = diarization_pipeline(str(audio_path))
    # exclusive_speaker_diarization has no overlapping speech turns, which is what
    # we want when assigning a single speaker to each Whisper word.
    turns = [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in diarization_output.exclusive_speaker_diarization.itertracks(yield_label=True)
    ]

    def speaker_for(start: float, end: float) -> str:
        best_speaker, best_overlap = "Speaker", 0.0
        for turn_start, turn_end, speaker in turns:
            overlap = min(turn_end, end) - max(turn_start, start)
            if overlap > best_overlap:
                best_overlap, best_speaker = overlap, speaker
        return best_speaker

    words = [
        {"text": w["word"], "start": w["start"], "end": w["end"], "speaker": speaker_for(w["start"], w["end"])}
        for seg in result["segments"]
        for w in seg.get("words", [])
    ]

    segments = []
    for w in words:
        if segments and segments[-1]["speaker"] == w["speaker"]:
            segments[-1]["text"] += w["text"]
            segments[-1]["end_ts"] = w["end"]
        else:
            segments.append({"speaker": w["speaker"], "text": w["text"], "start_ts": w["start"], "end_ts": w["end"]})

    for s in segments:
        s["text"] = s["text"].strip()

    return {"segments": segments}


def transcribe_diarize(audio_path: Path, engine: str = "assemblyai", whisper_model: str = "base") -> dict:
    if engine == "whisper":
        return transcribe_whisper_local(audio_path, whisper_model)
    if engine == "whisper-diarized":
        return transcribe_whisper_diarized(audio_path, whisper_model)
    return transcribe_assemblyai(audio_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/transcript.json"))
    parser.add_argument(
        "--engine", choices=["assemblyai", "whisper", "whisper-diarized"], default="assemblyai",
        help=(
            "assemblyai: hosted, real diarization, needs API key. "
            "whisper: local, no diarization, no API key. "
            "whisper-diarized: local, real diarization via pyannote, needs HF_TOKEN."
        ),
    )
    parser.add_argument(
        "--whisper-model", default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Used with --engine whisper or whisper-diarized. Bigger = more accurate, slower.",
    )
    args = parser.parse_args()

    result = transcribe_diarize(args.audio_path, args.engine, args.whisper_model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(f"Transcript ({len(result['segments'])} segments) written to {args.output}")
