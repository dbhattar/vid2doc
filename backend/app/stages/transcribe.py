"""Transcribe (+ diarize) audio. Two engines -- see transcribe_diarize().

The local-CPU engines this used to also support ("whisper" and
"whisper-diarized", via openai-whisper + pyannote.audio) were removed along
with the PyTorch dependency chain they needed -- both remaining engines are
cloud-hosted and fully cover diarized transcription without it. See
pipeline.py's _resolve_engine() for the auto-selection logic."""

import base64
import os
from pathlib import Path

from ..exceptions import PipelineError

# Baseten's ingress proxy rejects any request body over 100MB with a 413
# before it ever reaches the model (https://docs.baseten.co/reference/inference-api/overview#request-size).
# Checked against the base64-encoded payload specifically, since that's what
# actually goes over the wire. Left with ~5% headroom below the documented
# 100MB for the JSON envelope around it and any MB-vs-MiB ambiguity.
BASETEN_MAX_REQUEST_BYTES = 95_000_000

# Merge consecutive same-speaker fragments into readable paragraphs. Raw ASR
# output (Whisper especially, whether run locally or via Baseten) segments
# every few words, which reads as a wall of one-line "speaker" attributions
# rather than flowing prose. A gap cap keeps real pauses as paragraph breaks;
# a length cap keeps a single uninterrupted speaker turn from collapsing into
# one giant undifferentiated blob.
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


def transcribe_baseten(audio_path: Path, model_size: str = "base") -> dict:
    """GPU-hosted whisper+pyannote, via a custom Truss deployment (see
    baseten/transcribe-diarize/) -- word-level Whisper transcription aligned
    against pyannote speaker turns, same idea this codebase used to also run
    locally on CPU before that path was removed, just running remotely on a
    GPU instead. Audio goes up as base64 in the request body, matching the
    same pattern classify.py already uses for images sent to Claude/OpenAI."""
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
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(audio_path), "-ac", "1", "-c:a", "flac", compressed.name],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            # check=True's own str(e) is just "exit status N" -- the useful
            # part (why ffmpeg actually failed) is in stderr, captured but
            # otherwise discarded. Surface it so it lands in the job's
            # error_message instead of a dead end.
            raise PipelineError(f"ffmpeg FLAC compression failed: {e.stderr.decode(errors='replace')}") from e
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
    if engine in ("whisper", "whisper-diarized"):
        # Removed along with the PyTorch dependency chain -- fail clearly
        # rather than silently falling back to a different engine than the
        # one actually configured (see pipeline.py's _resolve_engine()).
        raise PipelineError(
            f"TRANSCRIPTION_ENGINE={engine!r} was removed (no local PyTorch engine anymore) -- "
            "use 'assemblyai' or 'baseten' instead."
        )
    elif engine == "baseten":
        result = transcribe_baseten(audio_path, whisper_model)
    else:
        result = transcribe_assemblyai(audio_path)

    result["segments"] = _merge_fragments(result["segments"])
    return result
