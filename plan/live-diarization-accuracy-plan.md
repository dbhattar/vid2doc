# Improving live diarization accuracy for short speaker turns + transcription accuracy

## Context

The user asked whether the live, on-browser diarization feature can be made
to correctly identify different speakers even when they talk for only a
short period, and separately flagged that live transcription accuracy is
generally not very good. Both were investigated fresh (two parallel deep
reads of the actual pipeline, not assumed) rather than guessed at. The
short answer to "can this be done with the current approach": **yes, for
the common case** — several concrete, low-risk fixes are available within
the exact same models/WASM binaries already running today. The one
genuinely hard case (two speakers talking with *zero* pause between them,
so VAD never even creates a boundary to diarize across) is a real
architectural limitation of a silence-based VAD and is called out below as
explicitly out of scope for now, not silently ignored.

Scope for this plan, per direct confirmation: **Tier 1 (the 4 low-risk
fixes) + a minimal eval harness** to validate/tune them with real numbers
instead of guesses. A larger, separately-scoped Whisper-model-swap
investigation was considered and explicitly deferred (noted at the end).

## Root causes, confirmed by reading the actual code

1. **VAD only splits on silence.** `frontend/workers/vadAsrWorker.ts`'s
   `VAD_CONFIG` (lines 175-197) uses Silero VAD with
   `minSilenceDuration: 0.5` (sileroVad, line 179; tenVad, line 187) — a
   "turn" ends only once speech drops out for ≥0.5s, or a hard 8s cap is
   hit (`maxSpeechDuration`, forced by Moonshine's own ~9.27s input-length
   ceiling, see the comment at lines 161-172). VAD has zero concept of
   speaker identity — two different speakers talking back-to-back with
   <0.5s gap are merged into one segment with one speaker decision.
2. **Embedding reliability is a single hard length cutoff, not a
   confidence check.** `frontend/workers/embeddingWorker.ts`'s
   `MIN_RELIABLE_EMBEDDING_SECONDS = 1.2` (line 83), gated at line 143
   (`if (samples.length < MIN_RELIABLE_EMBEDDING_SECONDS * EMBEDDING_SAMPLE_RATE) return null`)
   — segments shorter than this skip embedding entirely, no SNR/confidence
   signal of any kind.
3. **Speaker matching uses one frozen reference embedding per speaker,
   forever.** `frontend/lib/speakerMatch.ts`'s `matchOrRegisterSpeaker`
   (lines 35-58) does a plain cosine-similarity nearest-neighbor scan
   against `registry.embeddings[]` (line 9's `SpeakerRegistry` type) —
   whichever embedding is first registered for a speaker is the *only*
   thing all future turns are compared against; it's never updated or
   averaged (confirmed: no mutation of `registry.embeddings[i]` anywhere,
   only `.push`, line 56).
4. **No embedding/no-confident-match both silently fall back to "same as
   last speaker," unlimited.** `frontend/app/(app)/dashboard/live/page.tsx`'s
   `onFinal` (lines 184-191):
   ```ts
   const speaker = turn.embedding
     ? matchOrRegisterSpeaker(registryRef.current, turn.embedding)
     : (lastSpeakerRef.current ?? UNKNOWN_SPEAKER_LABEL);
   ```
   There's a latent bug here too: a short-but->1.2s embedding that scores
   just under the 0.5 threshold against *every* known speaker immediately
   registers a **new** speaker today — a hasty decision from weak
   evidence, no margin check exists. T1.2 below fixes this as a side
   effect.
5. **Audio fed to the model is resampled with crude box-averaging, not a
   real anti-aliased resample.** `downsampleTo16k`
   (`vadAsrWorker.ts`, lines 297-327) is linear/box averaging with no
   low-pass filter — a real aliasing-accuracy hit on any mic running at a
   native rate other than 16kHz (44.1/48kHz is typical). It does already
   have a clean passthrough at line 298-300
   (`if (inputSampleRate === SAMPLE_RATE) return input;`), which T1.4 below
   exploits rather than replaces.
6. **Long (>8s) utterances get split mid-word with zero cross-chunk
   context.** `decodeSamples` (lines 394-404) splits into fixed 8s chunks
   purely because Moonshine has a hard input-length ceiling, each chunk
   decoded independently and text concatenated — a real accuracy cost for
   long monologues, called out in the code's own comment (lines 383-393).
   Left out of scope for this plan (see "Deferred" below) since it's a
   less common case than short back-and-forth turns and has no low-risk
   fix available without either a smaller/different model or
   silence-aware chunk placement (more invasive).

## Tier 1 — the fixes

### T1.1 — Lower `minSilenceDuration` 0.5s → 0.3s
**File:** `frontend/workers/vadAsrWorker.ts:179,187` (`VAD_CONFIG.sileroVad.minSilenceDuration`, `.tenVad.minSilenceDuration`).
Lets VAD actually create a boundary for faster, but still real, pauses
between speakers (typical conversational handoffs run 250-400ms) — leave
`minSpeechDuration: 0.25` untouched, that's a different "ignore this short
a blip" floor. Tradeoff: more same-speaker self-splits (one sentence
becomes two VAD segments) — explicitly acceptable because T1.2/T1.3 make
re-matching a self-split back to the *same* speaker far more reliable than
today, whereas the current failure mode (two *different* speakers silently
merged) is strictly worse. Must ship together with T1.2, since more/shorter
segments means more exposure to the embedding length floor.

### T1.2 — Replace the hard embedding-length gate with a lower floor + confidence-margin acceptance
Two files, one coordinated change:
- **`frontend/workers/embeddingWorker.ts:83`**: lower
  `MIN_RELIABLE_EMBEDDING_SECONDS` to a smaller **model-capability** floor
  (recommend `0.6`s — below this there's genuinely not enough audio for
  ERes2Net's pooling window, not a trust judgment) and rename to make that
  distinction clear (e.g. `MIN_EMBEDDABLE_SECONDS`). No other change here —
  it still returns `Float32Array | null` unchanged; *trust* now lives in
  the matching layer.
- **`frontend/lib/speakerMatch.ts`**: change `matchOrRegisterSpeaker` to
  track the second-best score alongside the best, and only accept a match
  (reuse that speaker's label) when `bestScore >= threshold` **and**
  (fewer than 2 speakers registered yet, or `bestScore - secondBestScore >= minMargin`,
  recommend `minMargin = 0.15` against the documented ~0.91 vs ~0.11
  same/different-speaker gap). On a low-margin result, don't register a
  new speaker either — return an explicit `{ label: string; confident: boolean }`
  instead of a bare string, so the caller can fall back to "assume same as
  previous speaker" rather than either a hasty new registration (today's
  latent bug) or a hasty wrong match.
- **`frontend/app/(app)/dashboard/live/page.tsx:184-191`**: update the
  `onFinal` call site to use the new return shape, collapsing the
  "no embedding" and "embedding present but unconfident" cases into the
  same existing fallback-to-`lastSpeakerRef` path.
- `minMargin` and the new `0.6`s floor are the two values to validate/tune
  with Tier 3's eval harness rather than treat as final.

### T1.3 — Replace the frozen reference embedding with a capped running centroid
**File:** `frontend/lib/speakerMatch.ts`. Change `SpeakerRegistry` from one
embedding per speaker to a running mean + count:
```ts
export type SpeakerRegistry = {
  labels: string[];
  centroids: Float32Array[];
  sampleCounts: number[];
};
```
On a **confident** match to speaker `i` (gate this on T1.2's `confident`
flag — an unconfident/low-margin embedding must never pull a centroid
toward a possibly-wrong voice): incremental mean, capped at
`CENTROID_CAP = 20` —
```ts
const n = Math.min(sampleCounts[i], CENTROID_CAP);
for each dim d: centroids[i][d] += (embedding[d] - centroids[i][d]) / (n + 1);
sampleCounts[i] += 1;
```
Capping `n` (rather than an uncapped running mean) keeps the update step
from decaying to near-zero late in a long session, so the centroid can
still track a genuine mid-session voice/position change. New-speaker
registration is unchanged in spirit (`centroids.push(embedding)`,
`sampleCounts.push(1)`). `createSpeakerRegistry()` and `page.tsx:177`'s
call to it need updating for the new shape; `page.tsx` is confirmed the
only other consumer of `SpeakerRegistry`. `CENTROID_CAP` is another value
for Tier 3 to validate.

### T1.4 — Native 16kHz capture instead of manual box-average downsampling
**File:** `frontend/lib/sherpaLiveEngine.ts:250`. Change
```ts
audioContext = new AudioContext();
```
to request 16kHz directly, wrapped with a fallback for devices that reject
the constructor option:
```ts
try {
  audioContext = new AudioContext({ sampleRate: 16000 }); // matches workers/vadAsrWorker.ts's SAMPLE_RATE
} catch {
  audioContext = new AudioContext(); // downsampleTo16k's existing linear-resample path covers this case
}
```
This is additive, not a replacement — `downsampleTo16k`'s existing
passthrough (`vadAsrWorker.ts:298-300`) already no-ops once
`audioContext.sampleRate` (reported in every `pcm` message,
`sherpaLiveEngine.ts`) is 16000, so **no change needed inside
`vadAsrWorker.ts` at all**, and the old linear-resample path remains the
safety net for any browser/device that ignores the requested rate. Lets
the browser's real anti-aliased resampler handle the downsample instead of
box-averaging — pure input-quality improvement, very low risk, worth a
manual check on one mobile Safari session since that's historically the
flakiest `AudioContext({sampleRate})` support.

## Tier 3 — minimal eval harness (scoped, not a production eval system)

Needed because T1.1-T1.3's tuning values (`0.3s`, `0.6s`, `0.15` margin,
`CENTROID_CAP=20`) are reasoned defaults, not measured ones.

- **New labeled clips, not `local_test/`'s existing samples** — those
  (`apchem.mp4`, `caiso_edam.mp4`, `podcast.mp3`, etc.) have no ground-truth
  speaker/word labels and are long-form, not suited to controlled
  short-turn testing. Record 5-8 new short clips instead:
  - 3-4 clips, 2 known speakers, deliberately fast (<0.5s) back-and-forth
    handoffs — directly exercises T1.1-T1.3.
  - 2-3 clips with a hand-typed reference transcript (one clean/quiet, one
    noisier) for a basic word-error-rate check, stress-testing T1.4.
  - Each clip gets a small JSON sidecar checked in alongside it:
    `{ turns: [{ speakerId, startSec, endSec }], referenceText }`.
- **What's measured** (intentionally simple, not full DER):
  1. Pairwise same/different-speaker consistency against the labeled turns
     — did the pipeline agree with ground truth on which turns are the
     same speaker vs. different speakers.
  2. Basic word-error-rate via a small word-level edit-distance function
     (no existing WER library in this repo; ~20 lines, no new dependency)
     comparing final transcript text against the hand-typed reference.
- **Where this lives** — `frontend/` has no test runner at all today
  (confirmed: no `vitest`/`jest` in `package.json`). Two pieces:
  - `frontend/lib/speakerMatch.test.ts` via a new, minimal **Vitest**
    setup (add `vitest` devDependency + `vitest.config.ts` +
    `"test": "vitest run"` script) — covers the pure matching/centroid
    logic from T1.2/T1.3 with synthetic fixed vectors (same-vector match,
    distant-vector new-speaker, boundary-at-threshold/margin cases). No
    WASM, no audio I/O, fast and deterministic.
  - A new Node script, `frontend/native/sherpa-speaker-embedding/eval-diarization.js`,
    following the existing `test-embedding.js` precedent (same directory,
    same `ccall`-based WASM loading pattern) for the audio-clip-based
    diarization/WER checks, which need the actual embedding (and VAD/ASR)
    WASM modules running outside a browser.
- **Explicitly out of scope**: full DER scoring (the already-installed,
  unused `pyannote-metrics` in `local_test/venv` would be the natural tool
  if a more rigorous number is ever needed later), CI integration, more
  than ~8 clips, anything beyond English (the embedding model is
  VoxCeleb-English-trained per `speakerMatch.ts:30-34`'s own comment — a
  known, separate limitation this harness isn't trying to validate).

## Deferred (explicitly out of scope for this plan)

- **True mid-segment speaker-change detection** (sliding-window embeddings
  + change-point detection *within* one long VAD segment, to catch
  genuinely zero-pause speaker handoffs) — the one case T1.1-T1.3 cannot
  fix, since VAD never creates a boundary to diarize across in the first
  place. Needs word-level ASR timestamps (not available today —
  `decodeOneChunk` returns only `{ text }`) to re-split transcript text at
  a detected audio boundary, plus new clustering logic. Real, separate
  project — worth revisiting only if Tier 3's eval shows this is still a
  meaningful residual error source after Tier 1 ships.
- **Swapping the Moonshine ASR model for Whisper** — the vendored
  `public/wasm/v1/vad-asr/sherpa-onnx-asr.js` glue script's strings
  confirm the binary already references `whisper`/`paraformer`/`zipformer`
  model-family support (not Moonshine-specific), suggesting a model swap
  might be possible by repackaging the Emscripten `.data` asset rather
  than a full WASM/C++ rebuild — but this is unverified beyond that grep
  (no confirmed compatible Whisper ONNX export for this exact build, no
  tested VAD+Whisper combined-mode behavior, no packaging script in this
  repo today). Could be the bigger lever for raw transcription accuracy
  specifically, but was explicitly deferred as its own time-boxed
  investigation, not bundled into this plan.
- **Mid-word chunk-splitting on >8s utterances** — see root cause #6
  above. No low-risk fix available without either the Whisper
  investigation (larger native window) or silence-aware chunk placement;
  left as a known, accepted limitation for now.

## Verification

- **T1.1-T1.4 manual smoke test**: record a short live session (via the
  existing `/dashboard/live` page) with two people doing fast
  back-and-forth, with `saveAudio` on; confirm turn count and speaker
  labels look right by ear, and that an isolated same-speaker self-split
  (if it still happens) gets the *same* label on both halves rather than
  spawning a spurious new speaker.
- **Tier 3's own checks are the real verification**: `npm run test` (new
  Vitest script) for the pure matching/centroid logic, and
  `node eval-diarization.js <clips dir>` for the pairwise
  same/different-speaker accuracy + WER numbers on the labeled clips —
  run once on the current code to get a baseline, then again after
  T1.1-T1.4 land, to confirm the changes are a measured improvement, not
  just a vibe.
- Standard existing checks: `npx tsc --noEmit`, `npm run build:workers`,
  `npm run build` (per this repo's established verification pattern for
  worker/live-engine changes).
