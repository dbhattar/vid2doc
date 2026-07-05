"""Transcribe (+ diarize) audio. Three engines -- see transcribe_diarize()."""

import os
from pathlib import Path

from ..exceptions import PipelineError

PYANNOTE_MODEL = "pyannote/speaker-diarization-3.1"

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


def transcribe_diarize(audio_path: Path, engine: str = "assemblyai", whisper_model: str = "base") -> dict:
    if engine == "whisper":
        result = transcribe_whisper_local(audio_path, whisper_model)
    elif engine == "whisper-diarized":
        result = transcribe_whisper_diarized(audio_path, whisper_model)
    else:
        result = transcribe_assemblyai(audio_path)

    result["segments"] = _merge_fragments(result["segments"])
    return result
