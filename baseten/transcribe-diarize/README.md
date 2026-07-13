# transcribe-diarize (Baseten Truss)

GPU-hosted whisper + pyannote speaker diarization, bundled into one Truss
deployment. This is the remote counterpart to
`backend/app/stages/transcribe.py`'s `transcribe_whisper_diarized()` -- same
approach, same speaker-overlap assignment logic, just running on a GPU
instead of the backend worker's CPU, and kept warm across requests instead
of reloading models on every job.

## Verify before deploying

Nothing below has been confirmed against Baseten's current live
documentation -- treat this file and `config.yaml` as a starting sketch, not
ground truth:

- Exact `config.yaml` schema keys/nesting and valid GPU-type strings (e.g.
  whether `L4` is the right accelerator string today).
- The `Model` class's exact `load()`/`predict()`/secrets-access contract --
  compare against a fresh `truss init` scaffold.
- Whether Baseten has an official Python SDK worth using from the backend
  instead of raw `requests` (see `backend/app/stages/transcribe.py`'s
  `transcribe_baseten()`).
- The auth header format the backend should send (`transcribe_baseten()`
  currently sends `Authorization: Api-Key <key>` -- confirm this is still
  correct).
- Whether a "stay warm for N minutes" idle-timeout option exists between
  scale-to-zero and always-on, and its config key if so.
- Current GPU pricing, to actually weigh the scale-to-zero-vs-always-warm
  tradeoff below with real numbers.

## Deploying

```bash
cd baseten/transcribe-diarize
pip install --upgrade truss   # Baseten's CLI/SDK, if not already installed
truss push
```

Before the first deploy:

1. **Hugging Face token + gated model access.** Same requirement as the
   local CPU `HF_TOKEN` path: generate a Hugging Face access token, and
   while logged in as that account, accept the gated model terms for
   `pyannote/speaker-diarization-3.1` *and* its dependency
   `pyannote/segmentation-3.0` on huggingface.co. Without accepting both,
   `Pipeline.from_pretrained(...)` fails inside `load()` even with a valid
   token.
2. Set that token as this Truss's `hf_token` secret in the Baseten
   workspace (UI or CLI) -- **not** committed to `config.yaml`.
3. Decide GPU type and scale-to-zero vs always-warm (see the tradeoff notes
   in `config.yaml`) before or shortly after first deploy.

After `truss push` finishes, Baseten gives you a deployed model's predict
URL. Put the **full URL** in the main backend's `.env`:

```
BASETEN_API_KEY=<your Baseten API key>
BASETEN_MODEL_URL=<the predict URL truss push gave you>
TRANSCRIPTION_ENGINE=baseten   # or leave TRANSCRIPTION_ENGINE=auto, which
                                # prefers baseten automatically once
                                # BASETEN_API_KEY is set (see pipeline.py's
                                # _resolve_engine())
```

Then restart the backend's `api`/`worker` containers so they pick up the
new env vars.

## Why this isn't inside `backend/`

This has its own independent dependency set (GPU-enabled torch, not the
CPU-only wheels `backend/Dockerfile` deliberately installs) and its own
deploy lifecycle (`truss push` from a dev machine, not Docker Compose or the
`deploy/` Fabric tooling). Keeping it as a sibling top-level directory
avoids it ever being swept into the backend image's CPU-only torch install
or mistaken for code that runs inside the `api`/`worker` containers.

## Local CPU path stays as a fallback

Nothing about this deployment removes or replaces
`transcribe_whisper_local`/`transcribe_whisper_diarized` in
`backend/app/stages/transcribe.py` -- if `BASETEN_API_KEY` is unset, or this
deployment is down, `_resolve_engine()`'s auto-fallback chain still lands on
the local `HF_TOKEN`-based path (or plain `whisper` if that's unset too).
