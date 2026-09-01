// Dedicated Web Worker that owns sherpa-onnx's official `vad-asr` WebAssembly build end to
// end (see plan/realtime-diarization-plan.md): loads the WASM module + its bundled Silero
// VAD and Moonshine ASR models, runs VAD-based turn endpointing over incoming mic audio,
// and decodes each detected speech segment -- entirely off the main/UI thread, so
// inference never blocks rendering. lib/sherpaLiveEngine.ts is the only other file that
// talks to this worker, over the postMessage protocol in ./vadAsrProtocol.
//
// Architecture note on "partial" text: this build pairs a VAD with a *non-streaming*
// (offline/whole-utterance) ASR recognizer -- confirmed by reading the actual upstream
// demo source (wasm/vad-asr/app-vad-asr.js in k2-fsa/sherpa-onnx) rather than assumed from
// the C API. There is no native word-by-word streaming partial in this architecture: VAD
// buffers a turn internally and only hands it over, complete, once it detects the turn has
// ended. To still give a live "growing caption" feel instead of long silent gaps, this
// worker keeps its own copy of the in-progress utterance's samples and periodically
// re-decodes the whole thing so far with the same offline recognizer, emitting the result
// as a `partial` message. Only the VAD's own authoritative segment (from `vad.front()`) is
// ever used for the `final` message and its timestamps.
//
// The vendored WASM build's own JS glue (public/wasm/vad-asr/*.js) is NOT an ES module --
// it's the exact same plain global-scope script the upstream demo loads via <script> tags.
// Rather than fight a bundler into statically processing Emscripten's generated output
// (which has Node.js interop shims guarded by environment checks that can confuse static
// analysis), it's loaded at runtime with importScripts(), exactly like the upstream demo
// loads it with <script>, and kept byte-for-byte as downloaded so it stays easy to diff
// against a fresh release if sherpa-onnx ships an update.
//
// This file itself is compiled straight to a static asset (see package.json's
// "build:workers" script, output to public/workers/) and loaded with a plain
// `new Worker("/workers/vadAsrWorker.js")` rather than run through Next/Turbopack's
// `new Worker(new URL(...))` bundling: as of Next.js 16.2.10 that pattern doesn't actually
// compile the referenced TypeScript under Turbopack -- it hands the browser the raw,
// un-transpiled .ts source as a static-media response (confirmed by requesting it directly
// from `next dev`), which a JS engine can't execute. Compiling it ourselves and serving
// plain JS sidesteps that entirely. Because of that, this file intentionally has no
// `import`/`export` of its own (it's compiled solo, independent of the rest of the app) --
// the message-shape types below are duplicated from ./vadAsrProtocol.ts (the source of
// truth lib/sherpaLiveEngine.ts imports normally) rather than shared via `import type`,
// which is small enough to not be worth reintroducing module syntax for.
type PcmChunkMessage = { type: "pcm"; samples: Float32Array; sampleRate: number };
type FlushMessage = { type: "flush" };
type MainToWorkerMessage = PcmChunkMessage | FlushMessage;
type ReadyMessage = { type: "ready" };
type PartialMessage = { type: "partial"; text: string };
type FinalMessage = { type: "final"; text: string; startTs: number; endTs: number };
type FlushedMessage = { type: "flushed" };
type WorkerErrorMessage = { type: "error"; message: string };
type WorkerToMainMessage = ReadyMessage | PartialMessage | FinalMessage | FlushedMessage | WorkerErrorMessage;

// ---- worker-scope plumbing -------------------------------------------------------------

// lib.dom's ambient `self` is typed as `Window & typeof globalThis`, which is the wrong
// shape for a worker's global scope (no importScripts, wrong postMessage overload). Rather
// than redeclare `self`/`postMessage` globally (risking conflicts with lib.dom's own
// declarations elsewhere in the project), narrow it locally to just what's used here.
type WorkerScope = {
  postMessage(message: WorkerToMainMessage): void;
  onmessage: ((ev: MessageEvent<MainToWorkerMessage>) => void) | null;
  onerror: ((ev: ErrorEvent | string) => void) | null;
};
declare function importScripts(...urls: string[]): void;

const ctx = self as unknown as WorkerScope;

function post(message: WorkerToMainMessage) {
  ctx.postMessage(message);
}

function fail(message: string) {
  post({ type: "error", message } satisfies WorkerErrorMessage);
}

// ---- sherpa-onnx WASM module + vendored JS wrapper classes ------------------------------
//
// These classes/functions are defined at runtime by the importScripts() calls below (see
// public/wasm/vad-asr/sherpa-onnx-asr.js and sherpa-onnx-vad.js). They aren't real ES
// exports -- `declare` here just gives TypeScript a shape to check this file's own code
// against; the actual implementations only exist once loaded.

interface SherpaWasmModule {
  onRuntimeInitialized?: () => void;
  locateFile?: (path: string, scriptDirectory: string) => string;
  onAbort?: (reason: unknown) => void;
}

// `Module` itself must be a real (not `declare`-only) global assignment, since the
// vendored glue script checks `typeof Module !== "undefined"` and reuses whatever is
// already there -- see the comment above `applyModuleConfig()`.
declare let Module: SherpaWasmModule;

interface SpeechSegment {
  samples: Float32Array;
  start: number;
}

interface VadApi {
  config: { sileroVad: { windowSize: number } };
  acceptWaveform(samples: Float32Array): void;
  isEmpty(): boolean;
  isDetected(): boolean;
  pop(): void;
  front(): SpeechSegment;
  reset(): void;
  flush(): void;
  free(): void;
}
interface VadModelConfig {
  sileroVad: {
    model: string;
    threshold: number;
    minSilenceDuration: number;
    minSpeechDuration: number;
    maxSpeechDuration: number;
    windowSize: number;
  };
  tenVad: {
    model: string;
    threshold: number;
    minSilenceDuration: number;
    minSpeechDuration: number;
    maxSpeechDuration: number;
    windowSize: number;
  };
  sampleRate: number;
  numThreads: number;
  provider: string;
  debug: number;
  bufferSizeInSeconds: number;
}
declare function createVad(mod: SherpaWasmModule, config?: VadModelConfig): VadApi;

// The vendored createVad()'s own built-in default (used whenever no config is
// passed) hardcodes debug: 1, which dumps the full VAD config to the console
// on every session start via sherpa-onnx's native GetVadModelConfig logger --
// harmless, but noisy in production. Passing this explicit copy (identical to
// that default in every other field) is the only way to turn it off, since
// createVad() replaces the whole config wholesale rather than merging one in.
const VAD_CONFIG: VadModelConfig = {
  sileroVad: {
    model: "./silero_vad.onnx",
    threshold: 0.5,
    minSilenceDuration: 0.5,
    minSpeechDuration: 0.25,
    maxSpeechDuration: 20,
    windowSize: 512,
  },
  tenVad: {
    model: "",
    threshold: 0.5,
    minSilenceDuration: 0.5,
    minSpeechDuration: 0.25,
    maxSpeechDuration: 20,
    windowSize: 256,
  },
  sampleRate: 16000,
  numThreads: 1,
  provider: "cpu",
  debug: 0,
  bufferSizeInSeconds: 30,
};

declare class CircularBuffer {
  constructor(capacity: number, mod: SherpaWasmModule);
  push(samples: Float32Array): void;
  size(): number;
  head(): number;
  get(startIndex: number, n: number): Float32Array;
  pop(n: number): void;
  reset(): void;
  free(): void;
}

interface OfflineStreamApi {
  acceptWaveform(sampleRate: number, samples: Float32Array): void;
  free(): void;
}

interface OfflineRecognizerConfig {
  modelConfig: {
    debug?: number;
    tokens: string;
    moonshine: { encoder: string; mergedDecoder: string };
  };
}

declare class OfflineRecognizer {
  constructor(config: OfflineRecognizerConfig, mod: SherpaWasmModule);
  createStream(): OfflineStreamApi;
  decode(stream: OfflineStreamApi): void;
  getResult(stream: OfflineStreamApi): { text: string };
  free(): void;
}

// ---- constants ----------------------------------------------------------------------

const WASM_BASE = "/wasm/vad-asr/";
const SAMPLE_RATE = 16000;
// Re-decode the in-progress utterance for a `partial` preview at most this often.
const PARTIAL_INTERVAL_SAMPLES = Math.round(SAMPLE_RATE * 0.6);
// Don't bother decoding a partial until there's at least this much speech buffered.
const PARTIAL_MIN_SAMPLES = Math.round(SAMPLE_RATE * 0.3);
// Cap on the in-progress-utterance buffer kept for the `partial` preview. VAD_CONFIG's
// own maxSpeechDuration (20s) forces speech to split into `final` segments periodically
// even without a pause -- but VAD keeps reporting isDetected()==true continuously through
// that forced split for genuinely unbroken speech, and this buffer only resets on an
// actual pause (see wasDetected below). Without this cap, one long uninterrupted
// monologue re-decodes an ever-growing buffer every ~0.6s indefinitely, which has been
// observed to crash the ASR decoder outright once it gets large enough. Sized a little
// past VAD_CONFIG.sileroVad.maxSpeechDuration so the preview still normally spans one
// full VAD segment; it's a cosmetic live-caption preview only, not the source of truth
// for the eventual `final` text (that always comes from VAD's own front()/pop() segment).
const MAX_PARTIAL_PREVIEW_SAMPLES = SAMPLE_RATE * 25;

// ---- module state ---------------------------------------------------------------------

let vad: VadApi | null = null;
let circularBuffer: CircularBuffer | null = null;
let recognizer: OfflineRecognizer | null = null;
let ready = false;

// Raw (already 16kHz) samples of the utterance currently in progress, kept purely for the
// `partial` preview -- cleared whenever VAD is no longer in the "detected" state. This is
// separate from the VAD's own internal buffering; the VAD's `front()`/`pop()` segment
// remains the sole source of truth for the eventual `final` message.
let utteranceChunks: Float32Array[] = [];
let utteranceSampleCount = 0;
let samplesSinceLastPartial = 0;
let wasDetected = false;

// Leftover fractional-sample state for the linear-downsample carried over between chunks
// (mirrors the upstream demo's downsampleBuffer, just streaming instead of one-shot).
let resampleCarry: { ratio: number; offset: number } | null = null;

function concatFloat32(chunks: Float32Array[]): Float32Array {
  const total = chunks.reduce((sum, c) => sum + c.length, 0);
  const out = new Float32Array(total);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.length;
  }
  return out;
}

// Ported from sherpa-onnx's own wasm/vad-asr/app-vad-asr.js `downsampleBuffer` -- linear
// averaging down to 16kHz. Streaming-safe: `resampleCarry` tracks the fractional read
// offset across calls so chunk boundaries don't introduce clicks/drift.
function downsampleTo16k(input: Float32Array, inputSampleRate: number): Float32Array {
  if (inputSampleRate === SAMPLE_RATE) {
    return input;
  }
  const ratio = inputSampleRate / SAMPLE_RATE;
  if (!resampleCarry || resampleCarry.ratio !== ratio) {
    resampleCarry = { ratio, offset: 0 };
  }
  const carry = resampleCarry;
  const outLength = Math.floor((input.length - carry.offset) / ratio);
  if (outLength <= 0) {
    carry.offset -= input.length;
    return new Float32Array(0);
  }
  const out = new Float32Array(outLength);
  for (let i = 0; i < outLength; i++) {
    const start = carry.offset + i * ratio;
    const end = carry.offset + (i + 1) * ratio;
    const from = Math.max(0, Math.round(start));
    const to = Math.min(input.length, Math.round(end));
    let sum = 0;
    let count = 0;
    for (let j = from; j < to; j++) {
      sum += input[j];
      count++;
    }
    out[i] = count > 0 ? sum / count : input[Math.min(from, input.length - 1)];
  }
  carry.offset = carry.offset + outLength * ratio - input.length;
  return out;
}

function decodeSamples(samples: Float32Array): string {
  if (!recognizer) return "";
  const stream = recognizer.createStream();
  try {
    stream.acceptWaveform(SAMPLE_RATE, samples);
    recognizer.decode(stream);
    const result = recognizer.getResult(stream);
    return (result.text || "").trim();
  } catch (err) {
    // A single bad decode (e.g. a pathological input the ONNX model rejects) shouldn't
    // take down the whole live session -- log it for debugging and just skip this turn's
    // text, same as if the model had returned nothing. Deliberately NOT calling fail()
    // here: that posts a fatal error the main thread tears the whole session down for.
    console.error("sherpa-onnx decode failed, skipping this turn:", err);
    return "";
  } finally {
    stream.free();
  }
}

// Drops the oldest buffered chunks (front of the array, in push order) until back under
// MAX_PARTIAL_PREVIEW_SAMPLES, so one long unbroken monologue only ever re-decodes a
// bounded sliding window for the live preview instead of the whole thing so far.
function trimUtterancePreviewToCap() {
  while (utteranceSampleCount > MAX_PARTIAL_PREVIEW_SAMPLES && utteranceChunks.length > 1) {
    const dropped = utteranceChunks.shift()!;
    utteranceSampleCount -= dropped.length;
  }
}

function emitPartialIfDue() {
  if (utteranceSampleCount < PARTIAL_MIN_SAMPLES) return;
  if (samplesSinceLastPartial < PARTIAL_INTERVAL_SAMPLES) return;
  samplesSinceLastPartial = 0;

  const text = decodeSamples(concatFloat32(utteranceChunks));
  if (text) {
    post({ type: "partial", text } satisfies PartialMessage);
  }
}

function drainFinishedSegments() {
  if (!vad) return;
  while (!vad.isEmpty()) {
    const segment = vad.front();
    vad.pop();

    const text = decodeSamples(segment.samples);
    if (text) {
      const startTs = segment.start / SAMPLE_RATE;
      const endTs = startTs + segment.samples.length / SAMPLE_RATE;
      post({ type: "final", text, startTs, endTs } satisfies FinalMessage);
    }
  }
}

function processSamples(samples16k: Float32Array) {
  if (!vad || !circularBuffer) return;

  circularBuffer.push(samples16k);
  const windowSize = vad.config.sileroVad.windowSize;

  while (circularBuffer.size() > windowSize) {
    const window = circularBuffer.get(circularBuffer.head(), windowSize);
    circularBuffer.pop(windowSize);

    vad.acceptWaveform(window);

    const detected = vad.isDetected();
    if (detected) {
      utteranceChunks.push(window);
      utteranceSampleCount += window.length;
      samplesSinceLastPartial += window.length;
      trimUtterancePreviewToCap();
      emitPartialIfDue();
    } else if (wasDetected) {
      // Speech just ended (or never crossed the min-speech-duration threshold) --
      // whatever segment(s) VAD finalized are drained below; reset the partial-preview
      // accumulator regardless so a false-start doesn't linger into the next utterance.
      utteranceChunks = [];
      utteranceSampleCount = 0;
      samplesSinceLastPartial = 0;
    }
    wasDetected = detected;

    drainFinishedSegments();
  }
}

// The vendored glue script (sherpa-onnx-wasm-main-vad-asr.js) does
// `var Module = typeof Module !== "undefined" ? Module : {}` and expects a pre-existing
// `Module` object with `locateFile`/`onRuntimeInitialized` already set, exactly like the
// upstream demo's `Module = {}` before its own <script> tag. Since this is a plain
// assignment (not `var`/`let`), it's done via `globalThis` to stay valid under the strict
// mode ES modules always run in.
function applyModuleConfig() {
  const moduleConfig: SherpaWasmModule = {
    locateFile: (path) => WASM_BASE + path,
    onRuntimeInitialized: () => {
      try {
        vad = createVad(Module, VAD_CONFIG);
        circularBuffer = new CircularBuffer(30 * SAMPLE_RATE, Module);
        recognizer = new OfflineRecognizer(
          {
            modelConfig: {
              debug: 0,
              tokens: "./tokens.txt",
              moonshine: {
                encoder: "./moonshine-encoder.ort",
                mergedDecoder: "./moonshine-merged-decoder.ort",
              },
            },
          },
          Module,
        );
        ready = true;
        post({ type: "ready" });
      } catch (err) {
        fail(`Failed to initialize sherpa-onnx recognizer: ${String(err)}`);
      }
    },
    onAbort: (reason) => {
      fail(`sherpa-onnx WASM module aborted: ${String(reason)}`);
    },
  };
  (globalThis as typeof globalThis & { Module: SherpaWasmModule }).Module = moduleConfig;
}

function loadWasmModule() {
  try {
    applyModuleConfig();
    // Order matters: the wrapper classes (createVad/OfflineRecognizer/CircularBuffer) have
    // no dependency on the WASM runtime being initialized yet, but the main glue script
    // reads the `Module` global set up above as soon as it starts executing.
    importScripts(
      WASM_BASE + "sherpa-onnx-vad.js",
      WASM_BASE + "sherpa-onnx-asr.js",
      WASM_BASE + "sherpa-onnx-wasm-main-vad-asr.js",
    );
  } catch (err) {
    fail(`Failed to load sherpa-onnx vad-asr WASM build: ${String(err)}`);
  }
}

ctx.onmessage = (ev: MessageEvent<MainToWorkerMessage>) => {
  const msg = ev.data;
  if (!ready) {
    // Ignore audio that arrives before init finishes (shouldn't happen since
    // lib/sherpaLiveEngine.ts awaits `ready` before starting capture) rather than crash.
    if (msg.type === "flush") post({ type: "flushed" });
    return;
  }

  if (msg.type === "pcm") {
    const samples16k = downsampleTo16k(msg.samples, msg.sampleRate);
    if (samples16k.length > 0) {
      processSamples(samples16k);
    }
    return;
  }

  if (msg.type === "flush") {
    vad?.flush();
    drainFinishedSegments();
    utteranceChunks = [];
    utteranceSampleCount = 0;
    samplesSinceLastPartial = 0;
    post({ type: "flushed" });
  }
};

loadWasmModule();
