"""Baseten Truss model: GPU-hosted whisper + pyannote diarization, bundled
into one deployment so a job only needs one network round-trip.

Mirrors backend/app/stages/transcribe.py's transcribe_whisper_diarized()
almost exactly -- same speaker-overlap assignment logic, copied verbatim --
except this runs on GPU (fp16, device="cuda") and keeps both models warm
across requests via load(), instead of reloading them fresh on every job
the way the local CPU path does.

Request shape:  {"audio_b64": "<base64-encoded audio file>", "model_size": "base", "format": "mp3"}
("format" is the audio container/codec extension, e.g. "mp3" or "wav" --
used only to pick the right suffix for the temp file below; whisper/pyannote
both decode via ffmpeg under the hood and don't care about the extension
itself, but a real extension avoids ever relying on content-sniffing.)
Response shape: {"segments": [{"speaker": str, "text": str, "start_ts": float, "end_ts": float}, ...]}
(word-level granularity -- the backend's _merge_fragments() coalesces these
into paragraphs, same as it does for the local whisper-diarized path.)
"""

import base64
import tempfile

import torch
import whisper
from pyannote.audio import Pipeline

PYANNOTE_MODEL = "pyannote/speaker-diarization-3.1"


class Model:
    def __init__(self, **kwargs):
        # Baseten injects secrets declared in config.yaml's `secrets:` block
        # here -- confirm this exact access pattern against current Truss
        # docs before first deploy (see README.md's "Verify before deploying" section).
        self._secrets = kwargs.get("secrets")
        self._whisper_models = {}  # cache by model_size ("base", "small", ...)
        self._diarization_pipeline = None

    def load(self):
        """Runs once per replica at container start (and again on scale-out
        to a new replica) -- this is what fixes the CPU path's "reload every
        job" cost. Pre-warms the default whisper size; other sizes lazy-load
        into the cache on first request for that size, then stay warm too."""
        hf_token = self._secrets["hf_token"] if self._secrets else None
        self._diarization_pipeline = Pipeline.from_pretrained(PYANNOTE_MODEL, token=hf_token)
        # This pinned pyannote.audio version's Pipeline.to() requires an
        # actual torch.device, not a bare string -- passing "cuda" directly
        # raises TypeError.
        self._diarization_pipeline.to(torch.device("cuda"))
        self._whisper_models["base"] = whisper.load_model("base", device="cuda")

    def _get_whisper(self, model_size: str):
        if model_size not in self._whisper_models:
            self._whisper_models[model_size] = whisper.load_model(model_size, device="cuda")
        return self._whisper_models[model_size]

    def predict(self, request: dict) -> dict:
        audio_b64 = request["audio_b64"]
        model_size = request.get("model_size", "base")
        audio_format = request.get("format", "wav")
        audio_bytes = base64.b64decode(audio_b64)

        with tempfile.NamedTemporaryFile(suffix=f".{audio_format}") as f:
            f.write(audio_bytes)
            f.flush()
            audio_path = f.name

            model = self._get_whisper(model_size)
            # fp16=True (vs the CPU path's fp16=False) -- GPU supports half
            # precision and it's meaningfully faster. Intentional divergence
            # from the CPU reference, not a port bug.
            result = model.transcribe(audio_path, fp16=True, word_timestamps=True, verbose=False)

            diarization_output = self._diarization_pipeline(audio_path)
            # exclusive_speaker_diarization has no overlapping speech turns,
            # which is what we want when assigning a single speaker to each
            # whisper word -- same as the local CPU path.
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

        segments = [
            {
                "speaker": speaker_for(w["start"], w["end"]),
                "text": w["word"].strip(),
                "start_ts": w["start"],
                "end_ts": w["end"],
            }
            for seg in result["segments"]
            for w in seg.get("words", [])
        ]
        return {"segments": segments}
