# Realtime (live-mic) diarization — fully client-side, true real-time

## Context

Framewrite's transcription+diarization today (`backend/app/stages/transcribe.py`,
dispatched from `backend/app/pipeline.py`) is entirely batch: AssemblyAI's async
API, or local/remote Whisper + `pyannote.audio` run once over a *complete* audio
file. There is no websocket/live-audio infrastructure anywhere in the backend,
and the job-queue worker model (`worker.py` polls Postgres for queued jobs,
spawns each as its own OS subprocess) is a batch-pull design.

The ask is a new product surface: record live via the browser microphone and
see a live transcript **with speaker labels appearing turn-by-turn as people
speak** — self-hosted (no new vendor/API key), entirely on-device/offline, and
sending only the finished transcript to the backend rather than streaming raw
audio to a server.

`sherpa-onnx` (already present on this machine as an iOS framework; also ships
prebuilt **WebAssembly** builds for browsers) is the right base, but I verified
two things concretely (not assumed) that shape this plan:

- Its `vad-asr` WASM build gives genuine live streaming ASR with VAD-based
  turn endpointing — real-time partial/finalized captions, no server round
  trip, confirmed as a real build target in the `k2-fsa/sherpa-onnx` repo.
- Its `speaker-diarization` WASM build is **strictly whole-buffer** — I pulled
  the actual demo source (`wasm/speaker-diarization/app-speaker-diarization.js`)
  and confirmed it only supports "upload a file → decode fully → one call to
  `sd.process(float32Samples)` → get all segments back." No mic input, no
  incremental API. There is **no official prebuilt WASM artifact for live,
  turn-by-turn diarization.**

The native C-API this is all built on (`sherpa-onnx/c-api/c-api.h`, already
inspected) *does* expose the right lower-level primitives for real-time
diarization — `SherpaOnnxSpeakerEmbeddingExtractor` (embed a short audio
window) and `SherpaOnnxSpeakerEmbeddingManager` (nearest-match / register-new
against previously seen speakers) — they're just never wrapped into an
official browser build. **Getting genuine real-time diarization therefore
means building a small custom WASM module ourselves**, following the exact
pattern sherpa-onnx already uses for its own demos (each `wasm/<name>/`
directory is a `CMakeLists.txt` + a `sherpa-onnx-wasm-main-<name>.cc` wrapper
that Embind/extern-C-exports a slice of the C-API for JS). This is real,
scoped engineering work — not just wiring up an existing demo — but every
primitive it needs already exists and is documented in the C-API, and
sherpa-onnx's own WASM build process is documented
(`sherpa/docs/source/onnx/wasm/build.rst`) and reproducible with the
Emscripten SDK.

## Design

**One shared VAD stream drives both transcription and diarization live**, so
there's no separate post-hoc alignment step:

1. **`vad-asr`** (official WASM build) runs continuously on the mic stream:
   live partial captions, and a "turn finalized" event (text + start_ts/end_ts)
   each time VAD detects an endpoint.
2. **Our custom `speaker-embedding` WASM module** (new, built by us) computes
   an embedding over that same just-finalized turn's audio window the moment
   the turn ends.
3. **Speaker matching** — cosine similarity of the new embedding against every
   previously-seen speaker embedding in this session, in plain JS (a small,
   easily unit-testable function: match the closest one above a similarity
   threshold, else register a new "Speaker N", numbered by first appearance —
   mirroring the same ordering convention `pipeline._normalize_speaker_labels`
   already uses server-side). No need to also wrap the C-API's
   `SpeakerEmbeddingManager` — the matching logic is simple enough to own
   directly in JS with full visibility/testability.
4. The finalized turn is immediately rendered with its speaker label — genuine
   turn-by-turn real-time diarization, not a retrofit. Latency per turn is
   bounded by the VAD's silence-detection window (typically a few hundred ms
   to ~1s), an inherent property of any turn-based diarization approach, not
   a bug.
5. Only that turn's short audio window needs to be held in memory for
   embedding extraction, and it can be discarded immediately after — **no
   need to buffer the full session's raw audio for diarization purposes.**
   (Audio buffering for optional *storage/upload* is a separate, independent
   concern — see below.)
6. On **Stop**, the segment list (`{speaker, text, start_ts, end_ts}`) is
   already fully assembled — POST it as-is to the backend. No second
   diarization pass, no alignment step.

Because the segment contract is exactly what `pipeline.py` already consumes
downstream of transcription, finalization can flow through the **existing
worker/job-queue model completely unchanged** — just short-circuiting the
transcription step when a precomputed transcript is already present. No
WebSocket, no auth-ticket workaround (this is an ordinary Bearer-authenticated
`fetch`, same as every other backend call via `apiFetch`), no server-side
sherpa-onnx dependency, no server-side audio streaming.

**Feasibility note**: the `vad-asr` official build and the underlying
embedding-extractor C-API are both confirmed real; what's *not* yet verified
is that our own custom WASM build actually compiles, loads, and gives stable,
correct speaker assignment in a browser at usable latency. That's exactly what
the spike (see Verification) is for, before the full UI is built on top of it.

## Backend changes (small, unaffected by the diarization-timing decision)

1. **`backend/app/pipeline.py` — `_transcribe_segments(job, output_dir)`**
   (currently: extract audio → resolve engine → `transcribe.transcribe_diarize`):
   add a short-circuit at the top — if `output_dir / "live_segments.json"`
   exists, load and return those segments directly, skipping audio extraction
   and `transcribe_diarize` entirely. This is the only change needed to make
   the existing `run_job` audio branch (`_transcribe_segments` →
   `_normalize_speaker_labels` → optional `compose.generate_summary` →
   `_build_audio_sections` → `_finalize_document`) work unmodified for
   client-diarized transcripts.

2. **New route `backend/app/routes/live.py`** — `POST /api/live/finalize`,
   protected by the existing `get_current_user` dependency like any other
   route (no new auth mechanism needed). Accepts `multipart/form-data`:
   `title`, `segments` (JSON string of the live-assembled result), and
   optionally an `audio` file blob. Handler:
   - Generates `job_id`, creates `output_dir`/`uploads_dir` per the existing
     convention (`settings.OUTPUT_DIR / job_id`, `settings.UPLOADS_DIR / job_id`).
   - Writes `output_dir / "live_segments.json"` with the posted segments.
   - If an audio blob was posted, saves/converts it (ffmpeg, already in the
     image) to match the existing audio-job convention; if not posted, this
     is still fully functional — duration for billing comes from the
     segments' own timestamps rather than probing a file.
   - Calls `jobs.create_job(job_id, source_path=..., user_id=user.id,
     job_type="audio", title=title, duration_seconds=<from last segment end_ts>)`
     with `status="queued"` — picked up by the **existing** `worker.py`/
     `job_runner.py` exactly like an uploaded-audio job. Reuse whatever
     duration/billing calculation `routes/audio.py`'s existing upload handler
     already does, rather than reimplementing it.
   - Register the router in `app/main.py` alongside the other 20 routers.

## Frontend changes

1. **New page `frontend/app/(app)/dashboard/live/page.tsx`** (sibling to
   `dashboard/audio/`, `dashboard/video/`), `"use client"`, following the
   existing `(app)` layout's auth gating.

2. **Custom WASM build** — new source directory (e.g.
   `frontend/native/sherpa-speaker-embedding/`) containing a
   `CMakeLists.txt` + `sherpa-onnx-wasm-main-speaker-embedding.cc` modeled
   directly on sherpa-onnx's own `wasm/speaker-diarization/` example, but
   exporting only `SherpaOnnxCreateSpeakerEmbeddingExtractor` +
   `...ComputeEmbedding` (not the full offline pipeline). Built with the
   Emscripten SDK via a documented script (e.g.
   `frontend/native/build-wasm.sh`), producing a `.wasm` + glue `.js`
   committed as a versioned build artifact (or built in CI) — this is a real
   one-time native-build investment, kept in-repo with source and a build
   script so it's reproducible, not a mystery binary.

3. **Model assets**: bundle the `vad-asr` model files and the speaker-embedding
   model as static assets (e.g. `frontend/public/models/sherpa-onnx/...`)
   rather than fetching from an external host at runtime — keeps the "offline"
   story honest and avoids a server-side model-hosting concern. Show a
   one-time loading/progress state on first visit (tens of MB); rely on normal
   HTTP caching for repeat visits.

4. **Web Worker**: run the `vad-asr` module and our custom speaker-embedding
   module inside a dedicated Web Worker so inference doesn't block the UI
   thread — new infra for this frontend (no existing Worker usage found).

5. **Capture**: `getUserMedia({audio: true})`, raw PCM fed to the worker via
   an `AudioWorkletNode`. A user-facing toggle on the page ("Save recording
   audio") controls whether a parallel `MediaRecorder` also runs on the same
   `MediaStream` to produce a compressed (webm/opus) file for upload at Stop
   — the browser handles that buffering internally; it's unrelated to the
   diarization pipeline above. When the toggle is off, no audio ever leaves
   the transcript stage.

6. **Live UI**: render each finalized turn with its speaker label the moment
   it's produced (see Design above) — a genuinely live, speaker-labeled
   transcript, not text-then-labels-later. Extract the per-speaker color
   scheme currently inline in `TranscriptViewer.tsx` into a small shared
   `lib/speakerColors.ts` so this view and the post-finalize job view stay
   visually consistent.

7. **On "Stop"**: stop capture, `apiFetch('/api/live/finalize', ...)` with
   the already-assembled segments (multipart, per the backend route above).
   On success, `router.push('/dashboard/jobs/${job_id}')` — landing on the
   **existing**, unmodified job detail page, which already renders
   `TranscriptViewer` for any `job_type === "audio"` job once
   `status === "done"`.

## Verification

- **Spike first** (throwaway, before wiring the full feature/page): confirm
  the custom speaker-embedding WASM module actually compiles via Emscripten,
  loads in a browser, and that per-turn embedding + cosine-match gives
  stable, correct speaker splits on a real two-person test recording, driven
  off `vad-asr`'s turn-endpoint events, at usable latency. This determines
  final model/threshold choices and whether any part of this plan needs
  adjusting before the full build.
- Full flow: `./restart-containers.sh --dev` for backend/worker, frontend dev
  server per `frontend/README.md`, log in, open the new live page, record
  with two distinct voices, confirm speaker labels appear live per-turn (not
  just at the end).
- Confirm `POST /api/live/finalize` creates a job that flows through the
  existing worker unmodified, ends in `status: done`, and that
  `/dashboard/jobs/[id]` renders `TranscriptViewer` with correct
  speakers/text; confirm speaker rename (`POST /api/jobs/{id}/speakers`)
  still works unmodified against this job.
- Test both the "save audio" and "transcript-only" toggle paths: confirm the
  backend route handles a missing `audio` part correctly (falls back to
  segment-derived duration) and that a saved recording plays back correctly
  from the job detail page like a normal uploaded-audio job.
- Unit test the JS speaker-matching function in isolation (synthetic fixed
  vectors: same vector → same label, distant vector → new label).
- Once approved, save this plan into the repo at
  `plan/realtime-diarization-plan.md` per `AGENTS.md` convention.

## Audio storage: user's choice, not fixed

The recording page includes a toggle so the person recording decides, per
session, whether the raw audio is uploaded/stored (enabling playback and
future reprocessing with a different engine) or never leaves the transcript
stage (nothing but text ever reaches the backend). Both paths are supported by
the same `POST /api/live/finalize` endpoint — the `audio` part is simply
optional. See frontend change #5 above.
