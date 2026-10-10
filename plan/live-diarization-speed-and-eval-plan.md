# Speeding up live diarization + adding a diarization accuracy eval

## Context

The live, on-browser diarization feature (`frontend/workers/vadAsrWorker.ts`,
`frontend/lib/sherpaLiveEngine.ts`, `frontend/lib/speakerMatch.ts`,
`frontend/native/sherpa-speaker-embedding/`) runs entirely client-side: a
Silero VAD + offline Moonshine ASR WASM build (official, vendored) for
text, and a custom-built WASM module (ERes2Net speaker embeddings) for
voice fingerprints, matched via a plain cosine-similarity scan. This was
investigated fresh (4 parallel research passes, not assumed) to find real,
measured bottlenecks rather than guessing. Two asks: (A) make it faster,
(B) add an accuracy eval harness, since none exists today for diarization
specifically anywhere in this repo.

## A. Speed — ranked by impact vs. effort

**1. Stop re-decoding the entire in-progress utterance on every partial
(biggest lever, confirmed root cause).** `emitPartialIfDue()`
(`vadAsrWorker.ts:446-455`) concatenates and fully re-decodes the whole
turn-so-far buffer through the offline Moonshine recognizer every ~0.6s
during speech (`PARTIAL_INTERVAL_SAMPLES`, line 265), capped at 8.5s of
audio (`MAX_PARTIAL_PREVIEW_SAMPLES`, line 281) — no incremental/cached
decode state exists. This is repeated, avoidable CPU churn that scales with
how long a turn has been running. Two independent, low-risk mitigations,
combinable:
   - Raise `PARTIAL_INTERVAL_SAMPLES` (e.g. 0.6s → 1.0-1.2s) — halves
     redecode frequency, costs only a little partial-caption freshness
     (finals are unaffected — `drainFinishedSegments()`, line 558, decodes
     each finished segment exactly once regardless).
   - Shrink the partial-preview window further (e.g. cap at ~4s instead of
     8.5s) — bounds worst-case per-decode cost more tightly; the complete,
     correct text still arrives at turn-end via the separate final decode.

**2. Switch the ASR model to `moonshine-tiny` and/or int8-quantize it.**
File sizes (`moonshine-encoder.ort` ~12.7MB, `moonshine-merged-decoder.ort`
~29MB) indicate full fp32 `moonshine-base`, not the smaller `tiny` variant.
Since every partial AND final decode pays this model's cost, a
smaller/quantized model speeds up everything in #1 for free, at some
transcription-accuracy cost to weigh — worth a quick side-by-side accuracy
check (see Part B) before committing.

**3. Enable WASM SIMD for the custom speaker-embedding build — currently
missing entirely.** `frontend/native/sherpa-speaker-embedding/CMakeLists.txt`
has no `-msimd128`/SIMD flag anywhere, despite its build directory being
named `build-wasm-simd-speaker-embedding` (a copied naming convention, not
a real flag). The *official* vad-asr build already proves SIMD works fine
in this exact toolchain. Low-risk, likely-pure-win: add the SIMD flag,
rebuild, re-run `test-embedding.js` to confirm correctness is unaffected,
measure the speedup.

**4. Move speaker-embedding inference off the ASR/VAD worker thread.**
Confirmed: both WASM modules load and run in the *same single* Web Worker
(`vadAsrWorker.ts` loads both via sequential `importScripts`, lines
652-656 and 472). `computeEmbeddingForSegment()` runs synchronously inside
`drainFinishedSegments()` (line 568) on that same thread — a slow embedding
call measurably delays processing of the *next* incoming audio chunk, since
WASM execution on one worker is inherently serial. The embedding extractor
is already session-long-lived and reused (only a lightweight stream object
is created per turn), so moving it to a second dedicated Worker is a
contained change: post the turn's audio samples over, get the embedding (or
just the final match decision) back, while the main VAD/ASR worker keeps
decoding new audio in parallel on another core. This is the right fix for
"embedding work delays live captions," which #3 only partially addresses.

**5. Fix a real (unrelated, free) React jank source.** `turns` is a single
flat state array (`page.tsx:34`) fully re-mapped (`page.tsx:216-233`) on
*every* partial-token update, since `setPartialText` and the turns list live
in the same component's render scope. Extract the finalized-turns list into
its own memoized child keyed only on `turns`, so partial updates
(≤~1.6Hz already, not itself a cost problem) only re-render the one
in-progress line, not the whole transcript history.

**6. Cache the ~95MB of WASM/model assets properly.** No `Cache-Control`
override exists for `/wasm/*` (`next.config.ts` only sets COOP/COEP there,
for cross-origin isolation) and there's no service worker/Cache
API/IndexedDB caching anywhere — a repeat visit's reload behavior depends
entirely on the browser's default HTTP cache. Add explicit long-lived
`Cache-Control: public, max-age=31536000, immutable` for these static,
rarely-changing files, paired with a version path segment (they're
currently unhashed filenames, so a future model update needs a cache-buster
or stale clients could keep an old cached copy indefinitely).

**7. (Nice-to-have, perceived speed only) Show real load progress.**
Recording is gated behind `waitForReady()` (`sherpaLiveEngine.ts:33-63`,
30s timeout) until the ~58MB VAD+ASR bundle finishes loading — currently a
generic "Starting..." button with no progress indication
(`page.tsx:199`). A real fetch-progress bar would not make it faster but
would make the wait feel shorter.

**Bigger, longer-term swing, not recommended first:** enabling pthreads
(`SharedArrayBuffer`-based multithreading) for a custom vad-asr rebuild —
the COOP/COEP headers already in `next.config.ts` exist specifically to
allow this, but the *official* vad-asr artifact used today is
single-threaded-only. Would need a from-scratch custom build (same shape
of effort as the existing embedding module's own build script) and is a
bigger lift than #1-#6 for likely diminishing additional return once those
are done.

## B. Accuracy eval — nothing exists today, build from the one real precedent

Confirmed: `validation/` is unrelated (API-contract HTTP tests, no model
accuracy content). Frontend has **zero test runner** configured at all
(`frontend/package.json` has no vitest/jest, no `*.test.ts` anywhere).
`local_test/`'s sample media has no ground-truth speaker labels for
anything. The one genuine precedent is
`frontend/native/sherpa-speaker-embedding/test-embedding.js` +
`test-audio/` — a small Node harness proving same-speaker vs.
different-speaker cosine separation (~0.91-0.92 vs. ~0.11) on 4 synthesized
clips. Recommended build order, cheapest first:

**1. Add Vitest + the originally-planned unit test for `speakerMatch.ts`.**
Its own code comment already flags intent ("kept as a small pure function
... directly unit-testable") per `plan/realtime-diarization-plan.md`'s own
verification step, which was never actually done. Fast, cheap, catches
regressions in the matching/threshold logic itself: synthetic fixed
vectors (same vector → same label, distant vector → new label, boundary
cases right at the 0.5 threshold).

**2. Extend `test-embedding.js`'s pattern into a real labeled-clip eval.**
Record (or carefully hand-label) a handful of short, clean 2-3-speaker test
clips with known ground-truth speaker turns — can reuse `local_test/`'s
existing samples (`caiso_edam.mp4`, `sudheer.mp4`, etc.) if a human
spot-checks and labels a short excerpt of each once. Run each clip's audio
through the embedding extractor (already proven to run fine in Node, per
the existing harness) + `speakerMatch.ts`'s real clustering logic, and
report: detected-speaker-count accuracy, and a simple confusion metric
(fraction of reference speech time assigned to the wrong speaker label).

**3. Compute a standard metric, not a hand-rolled one, if it's cheap to get
for free.** `pyannote-metrics` is already installed in `local_test/venv`
(an unused transitive dependency of the old pyannote-based engine) and
computes real DER (Diarization Error Rate = false-alarm + missed-detection
+ speaker-confusion, over total reference speech time) from standard RTTM
files. If ground truth from #2 is stored as RTTM, this eval can shell out
to the already-installed tool for a credible, standards-based score instead
of reinventing DER math.

**4. (Gold standard, highest effort — later) Full-pipeline eval via
Playwright.** Everything above validates the embedding+matching logic in
isolation, not the real end-to-end behavior (VAD endpointing timing, the
1.2s-minimum-embedding-duration rule, last-speaker fallback on short
segments — see `vadAsrWorker.ts`'s `MIN_RELIABLE_EMBEDDING_SECONDS`). A
Playwright test driving the actual `/dashboard/live` page with Chrome's
fake-audio-capture-from-file flag (feeding a real labeled WAV as the
"microphone") would exercise the complete real pipeline exactly as a user
experiences it. No Playwright setup exists in this repo yet — a bigger
lift, worth doing once #1-#3 are in place and have already caught the
cheap bugs.

## Verification (once any of the above is actually implemented)

- Speed changes: before/after wall-clock measurement of per-partial decode
  time (the worker can `console.time` around `decodeOneChunk`/
  `computeEmbeddingForSegment` during a manual test recording) on the same
  test clip, same machine.
- Eval harness: run it against the same labeled clips before and after any
  model/threshold change (e.g. the moonshine-tiny swap in A.2) to make
  accuracy tradeoffs visible, not just assumed.
