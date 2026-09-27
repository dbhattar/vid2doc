"""Baseten Truss model: GPU-hosted whisper + pyannote diarization, bundled
into one deployment so a job only needs one network round-trip.

This is now the only place this speaker-overlap assignment logic lives --
backend/app/stages/transcribe.py used to run the identical thing locally on
CPU (transcribe_whisper_diarized()), but that path has since been removed
entirely (see backend/app/pipeline.py's _resolve_engine()); this Truss
deployment is the sole diarized-transcription engine backed by
Whisper+pyannote today (the other engine, AssemblyAI, does its own hosted
diarization instead). Keeps both models warm across requests via load(),
rather than reloading them fresh on every job the way the old local CPU
path did.

Request shape:  {"audio_b64": "<base64-encoded audio file>", "model_size": "base", "format": "mp3"}
("format" is the audio container/codec extension, e.g. "mp3" or "wav" --
used only to pick the right suffix for the temp file below; whisper/pyannote
both decode via ffmpeg under the hood and don't care about the extension
itself, but a real extension avoids ever relying on content-sniffing.)
Response shape: {"segments": [{"speaker": str, "text": str, "start_ts": float, "end_ts": float}, ...]}
(word-level granularity -- the backend's _merge_fragments() coalesces these
into paragraphs.)
"""

import base64
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import torch
import whisper
import yaml
from huggingface_hub import snapshot_download
from pyannote.audio import Pipeline

PYANNOTE_MODEL = "pyannote/speaker-diarization-3.1"

# pyannote.audio 4.x's SpeakerDiarization pipeline defaults its new `plda` parameter to
# files inside THIS repo -- regardless of which top-level pipeline checkpoint you
# actually request (confirmed via Baseten deploy logs: requesting PYANNOTE_MODEL above
# still made requests to this repo's plda/xvec_transform.npz and plda/plda.npz). Its own
# internal download call for those files does NOT correctly forward
# Pipeline.from_pretrained()'s `token` -- confirmed by comparing an explicit,
# hand-written hf_hub_download() call using the exact same token (succeeded) against
# pyannote's own internal one for the identical file (401'd). Worked around in
# _offline_with_prefetched_plda below rather than waiting on an upstream fix.
PLDA_SOURCE_REPO = "pyannote/speaker-diarization-community-1"

# Mount locations declared in config.yaml's `weights` block (BDN/Baseten Delivery
# Network) -- see that file's `weights` comment for the full caveat list on everything
# below (an unverified best guess at pyannote's internal config schema for this specific
# pinned pipeline/library version). Unlike the older, now-deprecated `model_cache`
# config key, `weights` guarantees these paths are already populated by the time load()
# runs -- no polling/blocking call needed here (see
# https://docs.baseten.co/development/model/bdn).
PYANNOTE_PIPELINE_DIR = Path("/models/pyannote-speaker-diarization-3-1")
PYANNOTE_SEGMENTATION_DIR = Path("/models/pyannote-segmentation-3-0")
PYANNOTE_EMBEDDING_DIR = Path("/models/pyannote-wespeaker-embedding")


class Model:
    def __init__(self, **kwargs):
        # Baseten injects secrets declared in config.yaml's `secrets:` block
        # here -- confirm this exact access pattern against current Truss
        # docs before first deploy (see README.md's "Verify before deploying" section).
        self._secrets = kwargs.get("secrets")
        self._whisper_models = {}  # cache by model_size ("base", "small", ...)
        self._diarization_pipeline = None

    def _find_checkpoint_file(self, mount_dir: Path) -> str | None:
        """The one principal weights file BDN mounted at `mount_dir` -- pyannote's own
        per-repo convention is a single .bin or .safetensors checkpoint alongside a
        small config.yaml/README, so locating it by extension is robust to either
        convention without needing to have browsed the (gated, so unverified from here)
        repo's exact file listing. Returns None if the directory's missing or empty --
        e.g. BDN wasn't configured, or the guessed repo id in config.yaml's `weights`
        doesn't exist -- so the caller can fall back cleanly instead of crashing on a
        confident-looking wrong path."""
        if not mount_dir.is_dir():
            return None
        candidates = sorted(mount_dir.glob("*.safetensors")) + sorted(mount_dir.glob("*.bin"))
        return str(candidates[0]) if candidates else None

    @contextmanager
    def _offline_with_prefetched_plda(self, hf_token: str | None):
        """Works around pyannote.audio 4.x's broken token-forwarding for its `plda`
        sub-component (see PLDA_SOURCE_REPO's comment above): pre-fetches the whole
        plda/ folder ourselves, using an explicit hf_hub_download-family call with
        hf_token that's confirmed to actually work, then forces huggingface_hub into
        offline mode for the duration of the `yield` (i.e. around Pipeline construction)
        so pyannote's own broken internal download call is never attempted at all -- it
        just resolves the files from the local cache this just populated. Restores the
        previous HF_HUB_OFFLINE value afterward either way, so this can wrap either
        pipeline-construction call (the BDN path and the network fallback) without
        leaking offline mode into anything after it -- notably the fallback's own
        segmentation/embedding fetch, which does still need real network access."""
        if hf_token:
            try:
                snapshot_download(repo_id=PLDA_SOURCE_REPO, token=hf_token, allow_patterns=["plda/*"])
            except Exception as e:
                print(f"Failed to pre-fetch {PLDA_SOURCE_REPO}'s plda/ folder: {e}", flush=True)
        previous_offline = os.environ.get("HF_HUB_OFFLINE")
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            yield
        finally:
            if previous_offline is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = previous_offline

    def _load_diarization_pipeline_from_cache(self) -> Pipeline:
        """BDN (config.yaml's `weights`) mounts each repo's raw files at its own
        mount_location -- but pyannote's top-level pipeline config.yaml still references
        its segmentation/embedding sub-models by their original Hugging Face repo ids
        internally, so pointing Pipeline.from_pretrained at the mounted top-level
        directory as-is would still hit the network for those two on every cold start,
        largely defeating the point (BDN's own "transparent from_pretrained()" example
        is for a single self-contained repo, not a multi-repo pipeline like this one).
        Rewriting a local copy of that config.yaml to point at the already-mounted local
        checkpoint files instead is what actually gets BDN's cold-start win for
        pyannote's real weights, not just its small top-level config file. Raises on any
        failure (missing files, an unexpected config.yaml shape, etc.) rather than
        guessing further -- load() catches it and falls back to the original, proven
        network path."""
        config = yaml.safe_load((PYANNOTE_PIPELINE_DIR / "config.yaml").read_text())

        segmentation_path = self._find_checkpoint_file(PYANNOTE_SEGMENTATION_DIR)
        embedding_path = self._find_checkpoint_file(PYANNOTE_EMBEDDING_DIR)
        if not segmentation_path or not embedding_path:
            raise RuntimeError(
                f"BDN mount incomplete (segmentation={segmentation_path}, embedding={embedding_path}) "
                f"-- check config.yaml's weights sources/allow_patterns."
            )
        config["pipeline"]["params"]["segmentation"] = segmentation_path
        config["pipeline"]["params"]["embedding"] = embedding_path

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as rewritten:
            yaml.safe_dump(config, rewritten)
            rewritten_path = rewritten.name
        return Pipeline.from_pretrained(rewritten_path)

    def load(self):
        """Runs once per replica at container start (and again on scale-out
        to a new replica) -- this is what fixes the CPU path's "reload every
        job" cost. Pre-warms the default whisper size; other sizes lazy-load
        into the cache on first request for that size, then stay warm too.

        No explicit wait for BDN here -- per its docs, `truss push` doesn't return
        until mirroring completes, and a replica isn't even started until its
        config.yaml `weights` are already present at their mount_location, so
        PYANNOTE_SEGMENTATION_DIR etc. are guaranteed populated (if configured at all)
        by the time this runs."""
        hf_token = self._secrets["hf_token"] if self._secrets else None
        # TEMPORARY diagnostic -- never logs the actual secret, just enough to tell
        # whether it's arriving at all (and unchanged) once config.yaml also declares a
        # `weights` block referencing the same secret name via auth_secret_name. Remove
        # once the community-1 401 is root-caused. self._secrets is Baseten's own
        # SecretsResolver, which supports lookup (`secrets["name"]`, used above) but
        # explicitly raises NotImplementedError on iteration (.keys()/for/etc.) -- so
        # this only ever looks hf_token up directly, nothing enumerated.
        print(
            f"[diag] hf_token present: {hf_token is not None}, "
            f"hf_token length: {len(hf_token) if hf_token else 0}, "
            f"hf_token prefix: {hf_token[:6] if hf_token else None}",
            flush=True,
        )
        print(
            f"[diag] BDN mount dirs -- pipeline: {PYANNOTE_PIPELINE_DIR.is_dir()}, "
            f"segmentation: {PYANNOTE_SEGMENTATION_DIR.is_dir()}, "
            f"embedding: {PYANNOTE_EMBEDDING_DIR.is_dir()}",
            flush=True,
        )
        try:
            with self._offline_with_prefetched_plda(hf_token):
                self._diarization_pipeline = self._load_diarization_pipeline_from_cache()
        except Exception as e:
            # Best-effort: the BDN fast path depends on several unverified guesses (see
            # config.yaml's `weights` comment) -- fall back to the original, proven
            # network load rather than failing the whole deployment if any of them
            # turn out wrong. Slower cold start, not a broken one.
            #
            # NOTE: unlike the primary path above, this fallback does NOT get the
            # plda pre-fetch/offline-mode workaround -- its config.yaml still
            # references segmentation/embedding by HF repo id rather than a local
            # path, so it genuinely needs real network access for those, and forcing
            # offline mode here would break that too. If this fallback is ever
            # actually reached and it ALSO 401s on PLDA_SOURCE_REPO's gated files,
            # that's the same pyannote.audio token-forwarding bug documented on
            # PLDA_SOURCE_REPO above, just not yet worked around on this path.
            print(f"BDN-mounted pyannote pipeline load failed, falling back to the network path: {e}", flush=True)
            self._diarization_pipeline = Pipeline.from_pretrained(PYANNOTE_MODEL, token=hf_token)
        # This pinned pyannote.audio version's Pipeline.to() requires an
        # actual torch.device, not a bare string -- passing "cuda" directly
        # raises TypeError.
        self._diarization_pipeline.to(torch.device("cuda"))
        # Whisper deliberately isn't part of the BDN mirroring above -- BDN only mirrors
        # Hugging Face/S3/GCS/R2/Azure/Baseten-blob sources, and this downloads its
        # checkpoint from OpenAI's own CDN instead (see config.yaml's `weights` comment).
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
            """Best-overlap match against pyannote's exclusive turns, falling back to
            the temporally NEAREST turn when none overlaps at all -- which happens
            disproportionately for short words/utterances: a brief interjection can
            fall entirely within a gap pyannote's segmentation didn't resolve as a
            turn boundary, or within a region exclusive_speaker_diarization drops
            because two speakers briefly overlapped there (see its own comment
            above). Previously this fell through to a generic "Speaker" placeholder
            for every such word -- not any real speaker in the conversation, and
            since every such word shared that exact same placeholder string, they
            all got grouped downstream into one spurious extra "speaker" (see
            backend/app/pipeline.py's _normalize_speaker_labels) instead of being
            reasonably attributed to whoever was actually nearby in time. Falling
            back to the nearest turn instead means every word lands on a real
            speaker who was actually in the conversation, which is far less
            damaging to short-turn accuracy than inventing a new, meaningless one."""
            best_speaker, best_overlap = None, 0.0
            for turn_start, turn_end, speaker in turns:
                overlap = min(turn_end, end) - max(turn_start, start)
                if overlap > best_overlap:
                    best_overlap, best_speaker = overlap, speaker
            if best_speaker is not None:
                return best_speaker
            if not turns:
                return "Speaker"

            def distance(turn: tuple[float, float, str]) -> float:
                turn_start, turn_end, _ = turn
                midpoint = (start + end) / 2
                if midpoint < turn_start:
                    return turn_start - midpoint
                if midpoint > turn_end:
                    return midpoint - turn_end
                return 0.0

            _, _, nearest_speaker = min(turns, key=distance)
            return nearest_speaker

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
