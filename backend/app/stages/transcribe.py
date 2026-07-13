"""Transcribe (+ diarize) audio. Four engines -- see transcribe_diarize()."""

import base64
import os
from pathlib import Path

from ..exceptions import PipelineError

PYANNOTE_MODEL = "pyannote/speaker-diarization-3.1"

# Baseten's ingress proxy rejects any request body over 100MB with a 413
# before it ever reaches the model (https://docs.baseten.co/reference/inference-api/overview#request-size).
# Checked against the base64-encoded payload specifically, since that's what
# actually goes over the wire. Left with ~5% headroom below the documented
# 100MB for the JSON envelope around it and any MB-vs-MiB ambiguity.
BASETEN_MAX_REQUEST_BYTES = 95_000_000

# Merge consecutive same-speaker fragments into readable paragraphs. Raw ASR
# output (especially local Whisper) segments every few words, which reads as
# a wall of one-line "speaker" attributions rather than flowing prose. A gap
# cap keeps real pauses as paragraph breaks; a length cap keeps a single
# uninterrupted speaker turn (e.g. plain "whisper" engine, one speaker for
# the whole video) from collapsing into one giant undifferentiated blob.
MERGE_MAX_GAP_SECONDS = 2.0
MERGE_MAX_PARAGRAPH_CHARS = 400


def _merge_fragments(segments: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for seg in segments:
        if merged:
            prev = merged[-1]
            gap = seg["start_ts"] - prev["end_ts"]
            same_speaker = prev["speaker"] == seg["speaker"]
            fits = len(prev["text"]) < MERGE_MAX_PARAGRAPH_CHARS
            if same_speaker and gap <= MERGE_MAX_GAP_SECONDS and fits:
                prev["text"] = f"{prev['text']} {seg['text']}".strip()
                prev["end_ts"] = seg["end_ts"]
                continue
        merged.append(dict(seg))
    return merged


def transcribe_assemblyai(audio_path: Path) -> dict:
    import assemblyai as aai

    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        raise PipelineError("ASSEMBLYAI_API_KEY is not set")

    aai.settings.api_key = api_key
    config = aai.TranscriptionConfig(speaker_labels=True)
    transcript = aai.Transcriber().transcribe(str(audio_path), config)

    if transcript.status == aai.TranscriptStatus.error:
        raise PipelineError(f"AssemblyAI transcription failed: {transcript.error}")

    segments = [
        {
            "speaker": utt.speaker,
            "text": utt.text.strip(),
            "start_ts": utt.start / 1000,
            "end_ts": utt.end / 1000,
        }
        for utt in transcript.utterances
    ]
    return {"segments": segments}


def _load_whisper(model_size: str):
    try:
        import whisper
    except ImportError as e:
        raise PipelineError("openai-whisper is not installed") from e
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
    except ImportError as e:
        raise PipelineError("pyannote.audio is not installed") from e

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        raise PipelineError("HF_TOKEN is not set")

    model = _load_whisper(model_size)
    result = model.transcribe(str(audio_path), fp16=False, word_timestamps=True, verbose=False)

    diarization_pipeline = Pipeline.from_pretrained(PYANNOTE_MODEL, token=hf_token)
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

    # One "segment" per word here -- _merge_fragments (applied uniformly for
    # all engines below) does the actual paragraph-building, so this stays a
    # plain word-level list rather than pre-merging without a length cap.
    segments = [
        {"speaker": speaker_for(w["start"], w["end"]), "text": w["word"].strip(), "start_ts": w["start"], "end_ts": w["end"]}
        for seg in result["segments"]
        for w in seg.get("words", [])
    ]
    return {"segments": segments}


def transcribe_baseten(audio_path: Path, model_size: str = "base") -> dict:
    """GPU-hosted whisper+pyannote, via a custom Truss deployment (see
    baseten/transcribe-diarize/) -- same diarization approach as
    transcribe_whisper_diarized above, just running remotely on a GPU
    instead of locally on CPU. Audio goes up as base64 in the request body,
    matching the same pattern classify.py already uses for images sent to
    Claude/OpenAI."""
    import subprocess
    import tempfile

    import requests

    api_key = os.environ.get("BASETEN_API_KEY")
    model_url = os.environ.get("BASETEN_MODEL_URL")
    if not api_key:
        raise PipelineError("BASETEN_API_KEY is not set")
    if not model_url:
        raise PipelineError("BASETEN_MODEL_URL is not set")

    # audio_path here is always the 16kHz/16-bit mono WAV that
    # audio.extract_audio() produces upstream in pipeline.py -- uncompressed,
    # so it's ~3.7x the size of a compressed format for the same duration
    # (a 55-minute file is ~106MB raw, well past Baseten's 100MB request-body
    # limit once base64'd). Re-compress before sending -- FLAC, not a lossy
    # codec: pyannote's chunked audio reader asks for exact sample counts per
    # time window (e.g. exactly 160000 samples for a 10s window at 16kHz),
    # and lossy frame-based codecs like MP3 have encoder delay/padding that
    # throws that off by a small number of samples, which pyannote treats as
    # a hard error. FLAC is lossless (sample-accurate, no timing drift) and
    # still meaningfully smaller than raw PCM for speech audio.
    with tempfile.NamedTemporaryFile(suffix=".flac") as compressed:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path), "-ac", "1", "-c:a", "flac", compressed.name],
            check=True,
            capture_output=True,
        )
        audio_b64 = base64.standard_b64encode(Path(compressed.name).read_bytes()).decode()

    if len(audio_b64) > BASETEN_MAX_REQUEST_BYTES:
        raise PipelineError(
            f"Audio is too large to send to Baseten even after compression "
            f"({len(audio_b64) / 1e6:.0f}MB base64-encoded, Baseten's limit is 100MB) -- "
            f"try a shorter clip, or use a different TRANSCRIPTION_ENGINE for this file."
        )

    try:
        response = requests.post(
            model_url,
            headers={"Authorization": f"Api-Key {api_key}"},
            json={"audio_b64": audio_b64, "model_size": model_size, "format": "flac"},
            # Generous enough to absorb a cold start plus a long file --
            # revisit once real cold/warm timings are observed in practice.
            timeout=900,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout as e:
        raise PipelineError("Baseten transcription request timed out") from e
    except requests.exceptions.RequestException as e:
        raise PipelineError(f"Baseten transcription failed: {e}") from e

    data = response.json()
    if "segments" not in data:
        raise PipelineError(f"Baseten response missing 'segments': {data}")
    return {"segments": data["segments"]}


def transcribe_diarize(audio_path: Path, engine: str = "assemblyai", whisper_model: str = "base") -> dict:
    if engine == "whisper":
        result = transcribe_whisper_local(audio_path, whisper_model)
    elif engine == "whisper-diarized":
        result = transcribe_whisper_diarized(audio_path, whisper_model)
    elif engine == "baseten":
        result = transcribe_baseten(audio_path, whisper_model)
    else:
        result = transcribe_assemblyai(audio_path)

    result["segments"] = _merge_fragments(result["segments"])
    return result
