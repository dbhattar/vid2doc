# sherpa-speaker-embedding (WASM)

Minimal custom WebAssembly build exposing only sherpa-onnx's
speaker-embedding-extractor C-API (no ASR, no TTS, no full offline
diarization/clustering pipeline). Built for Framewrite's real-time
live-mic diarization feature: the browser computes a speaker embedding for
each VAD-finalized turn and does cosine-similarity speaker matching in
plain JS (see `plan/realtime-diarization-plan.md`).

Modeled directly on sherpa-onnx's own `wasm/speaker-diarization/` example
(same onnxruntime-wasm linkage, same Emscripten build flags), but with the
exported function set trimmed to just:

- `SherpaOnnxCreateSpeakerEmbeddingExtractor`
- `SherpaOnnxDestroySpeakerEmbeddingExtractor`
- `SherpaOnnxSpeakerEmbeddingExtractorDim`
- `SherpaOnnxSpeakerEmbeddingExtractorCreateStream`
- `SherpaOnnxSpeakerEmbeddingExtractorIsReady`
- `SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding`
- `SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding`
- `SherpaOnnxOnlineStreamAcceptWaveform` / `InputFinished` / `SherpaOnnxDestroyOnlineStream`
  (the online-stream primitives the extractor's streaming API is built on)

## Pinned versions

- **sherpa-onnx**: tag `v1.10.30`, commit `91e090ff86f0773556059cb55183837d5687450b`
  (`https://github.com/k2-fsa/sherpa-onnx`)
- **Emscripten**: `3.1.53` (the version sherpa-onnx's own wasm build scripts
  recommend; newer emsdk (tested: 6.0.8 "latest") was NOT tried against this
  build — stick to 3.1.53 unless you re-verify)
- **cmake**: needs `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` on cmake >= 4.0
  (Homebrew's current cmake), because a transitively-fetched dependency
  (`kaldi-native-fbank`) declares `cmake_minimum_required(VERSION 2.8)`,
  which modern cmake refuses without that policy override. Already baked
  into `build-wasm.sh` below.

## Model

`3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx` (3D-Speaker ERes2Net,
trained on VoxCeleb -- English/multilingual celebrity-interview speech,
16 kHz), renamed to `embedding.onnx`.

The initial spike used sherpa-onnx's own `wasm/speaker-diarization` demo's
default model, `3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx`
(same ERes2Net family, but trained on Mandarin Chinese speech) -- it worked
well in testing (speaker embeddings capture voice/acoustic characteristics
more than linguistic content, so cross-lingual transfer is common), but for
an English-language product the VoxCeleb-trained variant is the correct
default: no cross-lingual-transfer question to answer, and the file is
smaller besides (26.5MB vs 38MB).

Download:
```
curl -SL -O https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx
mv 3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx embedding.onnx
```

Other English/multilingual alternatives in the same release, if this one
ever needs revisiting: `wespeaker_en_voxceleb_CAM++.onnx` (29.3MB),
`nemo_en_titanet_large.onnx` (101MB, likely higher accuracy, much bigger
download).

Embedding dimension: reported as **192** by
`SherpaOnnxSpeakerEmbeddingExtractorDim` (this VoxCeleb-trained variant
differs from the zh-cn model's 512-dim output -- `speakerMatch.ts`'s cosine
similarity is dimension-agnostic, so nothing downstream needed to change).

## Files here

- `CMakeLists.txt` — new wasm target, dropped into a sherpa-onnx checkout's
  `wasm/speaker-embedding/` directory.
- `sherpa-onnx-wasm-main-speaker-embedding.cc` — the wrapper source. Just a
  `MyPrint` debug helper and a `CopyHeap` helper (same pattern as the
  official speaker-diarization example) — every exported function beyond
  that is already `extern "C"` in sherpa-onnx's own `c-api.h`, so no new
  wrapper functions were needed for the embedding API itself.
- `build-wasm.sh` — reproduces the whole toolchain + build from scratch
  (installs emsdk 3.1.53, clones sherpa-onnx at the pinned commit, patches
  in this new wasm target, downloads the model, builds).
- `test-embedding.js` — Node.js harness: loads the compiled glue JS
  directly (no browser needed), computes embeddings for 4 short WAV clips
  (2 clips each of 2 different macOS `say` voices), and checks that
  same-voice cosine similarity clears different-voice similarity by a
  wide margin.
- `test-audio/` — the 4 synthesized clips (`say -v Samantha|Daniel ... |
  ffmpeg -ar 16000 -ac 1` down to 16 kHz mono WAV).

## Verification status

**Confirmed working** with the VoxCeleb English model, from a clean,
non-concurrent, from-scratch build. Measured result, via
`test-embedding.js` against the `test-audio/` clips (two macOS `say`
English voices):

```
Embedding dim: 192
same-speaker  alice1 vs alice2: 0.9089
same-speaker  bob1   vs bob2  : 0.9199
avg diff-speaker similarity   : 0.1066
DISCRIMINATES SPEAKERS: YES
```

An even wider gap than the earlier zh-cn-model spike (≈0.91-0.92 vs
≈0.11, previously ≈0.92-0.93 vs ≈0.23) — plenty of room for the real
feature's matching threshold, 0.5 is a safe default (see
`frontend/lib/speakerMatch.ts`).

**Build gotcha found and fixed**: the original draft of `CMakeLists.txt`
paired `-sMODULARIZE=1` with `-sWASM_ASYNC_COMPILATION=0`. That combination
made the factory function's returned promise resolve *before* the
`--preload-file` payload (the embedding model) actually finished mounting
into the virtual filesystem — `SherpaOnnxCreateSpeakerEmbeddingExtractor`
would silently return `NULL` (model "not found") even though the module
looked fully initialized from JS's side. Dropping
`WASM_ASYNC_COMPILATION=0` (MODULARIZE alone is enough) fixed it — the
version of `CMakeLists.txt` in this directory already has the fix. If you
ever reintroduce `WASM_ASYNC_COMPILATION=0` for some reason, re-verify with
`test-embedding.js` before trusting it.

To reverify from a clean state:
```
./build-wasm.sh
node test-embedding.js <build-output-dir>/sherpa-onnx-wasm-main-speaker-embedding.js embedding.onnx ./test-audio
```
Expect: embedding dim printed, then the same-speaker/different-speaker
numbers, then `DISCRIMINATES SPEAKERS: YES` (exit code 0).

## Compiled output

The compiled `.js`/`.wasm`/`.data` (~50MB total, dominated by the 39MB
preloaded embedding model) are checked into
`frontend/public/wasm/speaker-embedding/` for the frontend to fetch at
runtime — see that decision's size/git tradeoff noted in
`plan/realtime-diarization-plan.md`.
