// Dedicated Web Worker that owns the custom speaker-embedding WASM build
// (frontend/native/sherpa-speaker-embedding/) end to end, loading the model and computing
// one embedding per finalized turn on request. lib/sherpaLiveEngine.ts is the only other
// file that talks to this worker, over the postMessage protocol in
// ./embeddingWorkerProtocol.
//
// Split out of workers/vadAsrWorker.ts (which used to load and run this same WASM module
// on its own thread, alongside VAD+ASR) specifically so a slow embedding computation never
// delays that worker's own processing of the next incoming audio chunk -- WASM execution on
// one worker thread is inherently serial, so the two could only ever run one at a time when
// they shared a thread. Running on a separate worker lets them run genuinely in parallel
// (on separate cores, browser/OS scheduling permitting).
//
// Compiled the same way as vadAsrWorker.ts -- see that file's top comment for the full story
// on why this is a plain classic-script build (tsconfig.workers.json) rather than bundled by
// Next/Turbopack, and why the message-shape types below are duplicated from
// ./embeddingWorkerProtocol.ts (the source of truth lib/sherpaLiveEngine.ts imports
// normally) instead of shared via `import type`.
//
// Naming note: tsc compiles every import/export-free worker entry point in
// tsconfig.workers.json's `include` together as one shared global-script scope (that's what
// "no import/export" actually means to the type checker, not just at runtime) -- so every
// top-level name here must be unique across workers/vadAsrWorker.ts too, not just within
// this file. Prefixed accordingly wherever a name would otherwise collide (both files
// independently want a "WorkerScope"/"ctx"/"SAMPLE_RATE", say).
type EmbedRequestMessage = { type: "embed"; turnId: number; samples: Float32Array };
type EmbeddingMainToWorkerMessage = EmbedRequestMessage;
type EmbeddingResultMessage = { type: "embedding"; turnId: number; embedding: Float32Array | null };
type EmbeddingWorkerToMainMessage = EmbeddingResultMessage;

// ---- worker-scope plumbing -------------------------------------------------------------
// Same narrowing rationale as workers/vadAsrWorker.ts's identical block.
type EmbeddingWorkerScope = {
  postMessage(message: EmbeddingWorkerToMainMessage, transfer?: Transferable[]): void;
  onmessage: ((ev: MessageEvent<EmbeddingMainToWorkerMessage>) => void) | null;
};
declare function importScripts(...urls: string[]): void;

const embeddingCtx = self as unknown as EmbeddingWorkerScope;

// ---- custom speaker-embedding WASM build (frontend/native/sherpa-speaker-embedding/) ---
//
// No hand-written JS wrapper classes -- it's a minimal build exporting only the raw C-API
// functions (see that directory's README), so this file calls them directly via `ccall`,
// the same way frontend/native/sherpa-speaker-embedding/test-embedding.js's already-verified
// Node harness does.

interface EmbeddingWasmModule {
  ccall(name: string, returnType: "number" | null, argTypes: string[], args: (number | string)[]): number;
  _malloc(size: number): number;
  _free(ptr: number): void;
  setValue(ptr: number, value: number, type: string): void;
  getValue(ptr: number, type: string): number;
  lengthBytesUTF8(str: string): number;
  stringToUTF8(str: string, ptr: number, maxBytes: number): void;
  HEAPF32: Float32Array;
}

// Defined as a global by importScripts() below (Emscripten's MODULARIZE=1 +
// EXPORT_NAME=... output) -- a factory, not a ready-to-use module: call it and await the
// returned promise.
declare function createSherpaOnnxSpeakerEmbeddingModule(config?: {
  locateFile?: (path: string) => string;
}): Promise<EmbeddingWasmModule>;

// v1: see vadAsrWorker.ts's WASM_BASE comment -- same versioned-path/cache-busting rationale.
const EMBEDDING_WASM_BASE = "/wasm/v1/speaker-embedding/";
// Virtual-FS path the model was preloaded at when the WASM build was compiled
// (--preload-file assets@., with assets/embedding.onnx inside) -- not a real path on disk
// here, see frontend/native/sherpa-speaker-embedding/README.md.
const EMBEDDING_MODEL_PATH = "./embedding.onnx";
// Below this, a speaker embedding is unreliable enough to do more harm than good -- the
// model's own verification (frontend/native/sherpa-speaker-embedding/README.md) measured
// same/different-speaker separation on 2-4s clips; VAD's own minSpeechDuration (0.25s) lets
// much shorter segments through, and a noisy embedding from just a few hundred ms of audio
// is exactly the kind of input that can fall below matchOrRegisterSpeaker's similarity
// threshold against the true speaker's own past embeddings, spuriously registering a
// brand-new speaker for what was actually a short interjection by someone already in the
// conversation. Segments shorter than this skip embedding entirely -- `embedding` comes
// back null, and the live page falls back to the previous turn's speaker (a much safer
// default for a short segment than a fresh, unreliable match) rather than guessing wrong
// with false confidence.
const MIN_RELIABLE_EMBEDDING_SECONDS = 1.2;
const EMBEDDING_SAMPLE_RATE = 16000;

let embeddingModule: EmbeddingWasmModule | null = null;
let embeddingExtractor = 0;
let embeddingDim = 0;
let embeddingReady = false;

function cStr(mod: EmbeddingWasmModule, str: string): number {
  const len = mod.lengthBytesUTF8(str) + 1;
  const ptr = mod._malloc(len);
  mod.stringToUTF8(str, ptr, len);
  return ptr;
}

// Loads the WASM build and creates one extractor for the whole worker lifetime (a fresh
// *stream* per turn, further below, is what actually holds a turn's samples). Never throws:
// any failure here just leaves embeddingReady false, logged for debugging -- every `embed`
// request then simply gets back `embedding: null`, matching the degrade-to-one-speaker
// rationale on the module state above.
async function loadEmbeddingModule() {
  try {
    importScripts(EMBEDDING_WASM_BASE + "sherpa-onnx-wasm-main-speaker-embedding.js");
    const mod = await createSherpaOnnxSpeakerEmbeddingModule({
      locateFile: (path) => EMBEDDING_WASM_BASE + path,
    });

    // SherpaOnnxSpeakerEmbeddingExtractorConfig: { const char *model; int32 num_threads;
    // int32 debug; const char *provider; } -- 4 fields x 4 bytes, matches test-embedding.js.
    const modelPtr = cStr(mod, EMBEDDING_MODEL_PATH);
    const providerPtr = cStr(mod, "cpu");
    const configPtr = mod._malloc(16);
    mod.setValue(configPtr + 0, modelPtr, "i32");
    mod.setValue(configPtr + 4, 1, "i32");
    mod.setValue(configPtr + 8, 0, "i32");
    mod.setValue(configPtr + 12, providerPtr, "i32");

    const extractor = mod.ccall("SherpaOnnxCreateSpeakerEmbeddingExtractor", "number", ["number"], [configPtr]);
    mod._free(modelPtr);
    mod._free(providerPtr);
    mod._free(configPtr);
    if (!extractor) {
      throw new Error("SherpaOnnxCreateSpeakerEmbeddingExtractor returned NULL");
    }

    embeddingModule = mod;
    embeddingExtractor = extractor;
    embeddingDim = mod.ccall("SherpaOnnxSpeakerEmbeddingExtractorDim", "number", ["number"], [extractor]);
    embeddingReady = true;
  } catch (err) {
    console.error("Speaker-embedding WASM module failed to load -- diarization will degrade to a single speaker:", err);
  }
}

// Best-effort speaker embedding for one already-VAD-finalized turn's samples (16kHz,
// matching EMBEDDING_SAMPLE_RATE) -- returns null (never throws) on any failure. A fresh
// stream per call mirrors test-embedding.js's proven usage; the extractor itself is reused
// for the worker's whole lifetime.
function computeEmbeddingForSegment(samples: Float32Array): Float32Array | null {
  if (!embeddingReady || !embeddingModule || !embeddingExtractor) return null;
  if (samples.length < MIN_RELIABLE_EMBEDDING_SECONDS * EMBEDDING_SAMPLE_RATE) return null;
  const mod = embeddingModule;
  let stream = 0;
  let samplesPtr = 0;
  try {
    stream = mod.ccall("SherpaOnnxSpeakerEmbeddingExtractorCreateStream", "number", ["number"], [embeddingExtractor]);
    samplesPtr = mod._malloc(samples.length * 4);
    mod.HEAPF32.set(samples, samplesPtr / 4);
    mod.ccall(
      "SherpaOnnxOnlineStreamAcceptWaveform",
      null,
      ["number", "number", "number", "number"],
      [stream, EMBEDDING_SAMPLE_RATE, samplesPtr, samples.length],
    );
    mod.ccall("SherpaOnnxOnlineStreamInputFinished", null, ["number"], [stream]);

    const isReady = mod.ccall(
      "SherpaOnnxSpeakerEmbeddingExtractorIsReady",
      "number",
      ["number", "number"],
      [embeddingExtractor, stream],
    );
    if (!isReady) return null;

    const embPtr = mod.ccall(
      "SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding",
      "number",
      ["number", "number"],
      [embeddingExtractor, stream],
    );
    if (!embPtr) return null;

    const embedding = new Float32Array(embeddingDim);
    for (let i = 0; i < embeddingDim; i++) {
      embedding[i] = mod.getValue(embPtr + i * 4, "float");
    }
    mod.ccall("SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding", null, ["number"], [embPtr]);
    return embedding;
  } catch (err) {
    console.error("Speaker-embedding extraction failed for this turn, skipping:", err);
    return null;
  } finally {
    if (stream) mod.ccall("SherpaOnnxDestroyOnlineStream", null, ["number"], [stream]);
    if (samplesPtr) mod._free(samplesPtr);
  }
}

embeddingCtx.onmessage = (ev: MessageEvent<EmbeddingMainToWorkerMessage>) => {
  const msg = ev.data;
  if (msg.type === "embed") {
    const embedding = computeEmbeddingForSegment(msg.samples);
    const transfer = embedding ? [embedding.buffer] : [];
    embeddingCtx.postMessage(
      { type: "embedding", turnId: msg.turnId, embedding } satisfies EmbeddingResultMessage,
      transfer,
    );
  }
};

loadEmbeddingModule();
