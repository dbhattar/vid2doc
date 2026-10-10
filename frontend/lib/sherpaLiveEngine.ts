// Real implementation of LiveEngineFactory (see lib/liveEngine.ts), backed by
// sherpa-onnx's official `vad-asr` WebAssembly build plus our custom speaker-embedding WASM
// build, both running entirely on-device (see plan/realtime-diarization-plan.md). This file
// owns everything on the main thread: mic capture via an AudioWorkletNode (raw PCM, not
// MediaRecorder -- the recognizer needs samples, not a compressed container), and talking
// to two dedicated workers over postMessage:
//   - workers/vadAsrWorker.ts -- VAD + ASR, produces partial/final text.
//   - workers/embeddingWorker.ts -- speaker embeddings, one request per finalized turn.
// Two separate workers, not one, specifically so a slow embedding computation never delays
// the VAD/ASR worker's own processing of the next incoming audio chunk -- WASM execution on
// a single worker thread is inherently serial, and the two used to share one.
//
// Both workers are a module-level singleton pool (below), not created fresh inside
// createSherpaLiveEngine() -- preloadLiveEngine() lets the live page kick off the one-time
// ~95MB WASM/model download as soon as it mounts (see page.tsx), rather than only once the
// user clicks Record, and every createSherpaLiveEngine() call (including a second
// recording in the same visit) reuses whatever's already loaded instead of redownloading.
// createSherpaLiveEngine() itself is the per-session orchestrator: it holds a finalized
// turn's text until that turn's embedding request resolves (or times out), then calls
// callbacks.onFinal with both together.
import type { LiveEngineCallbacks, LiveEngineFactory, LiveEngineHandle, LiveTurn } from "@/lib/liveEngine";
import type { EmbeddingWorkerToMainMessage, MainToEmbeddingWorkerMessage } from "@/workers/embeddingWorkerProtocol";
import type { MainToWorkerMessage, WorkerToMainMessage } from "@/workers/vadAsrProtocol";

// Generous: first load fetches ~55MB of WASM + bundled models from public/wasm/v1/vad-asr/
// and compiles the module -- see plan/realtime-diarization-plan.md for the size tradeoff.
const WORKER_READY_TIMEOUT_MS = 30000;
// How long stop() waits for the worker to finish flushing a trailing in-progress turn
// before giving up and tearing down anyway.
const FLUSH_TIMEOUT_MS = 3000;
// How long to wait for one turn's embedding before giving up and calling onFinal with no
// embedding anyway (same degrade-to-previous-speaker fallback as a worker load failure) --
// a stuck/crashed embedding worker should never permanently withhold a turn's text.
const EMBED_TIMEOUT_MS = 5000;

// Loaded as a plain static file (compiled by "npm run build:workers", see
// tsconfig.workers.json) rather than via Next/Turbopack's `new Worker(new URL(...))`
// bundling -- as of Next.js 16.2.10, Turbopack doesn't actually compile the referenced
// TypeScript for that pattern, it serves the raw .ts source verbatim as a static-media
// response (confirmed directly against `next dev`), which a JS engine can't execute as a
// worker. See the comment at the top of workers/vadAsrWorker.ts for the full story.
const WORKER_URL = "/workers/vadAsrWorker.js";
const EMBEDDING_WORKER_URL = "/workers/embeddingWorker.js";
const PCM_PROCESSOR_URL = "/workers/pcmProcessor.js";

// ---- module-level worker pool -----------------------------------------------------------
//
// Created at most once per page load (via preloadLiveEngine(), below) and never terminated
// by an ordinary stop()/dispose() any more -- they live for as long as this page stays
// mounted, exactly like any other in-memory module state. Reusing them across every
// recording session in the same visit (not just the first) is deliberate: the worker's own
// `ready` flag (workers/vadAsrWorker.ts) and the embedding extractor
// (workers/embeddingWorker.ts) are both already designed to be loaded once and reused for
// the module's whole lifetime -- recreating the workers per session was just redundantly
// redoing that one-time load every time.
let vadAsrWorker: Worker | null = null;
let vadAsrWorkerReady: Promise<void> | null = null;
let embeddingWorkerInstance: Worker | null = null;

type ProgressListener = (loaded: number, total: number) => void;
let latestProgress: { loaded: number; total: number } | null = null;
const progressListeners = new Set<ProgressListener>();

function notifyProgress(loaded: number, total: number) {
  latestProgress = { loaded, total };
  progressListeners.forEach((listener) => listener(loaded, total));
}

/** Replays the latest known progress immediately if loading already started before this
 * call (so a late subscriber -- e.g. a user who clicks Record mid-download -- doesn't see a
 * blank/zero progress bar), then keeps calling `listener` for every future update. Returns
 * an unsubscribe function. */
export function subscribeToLoadProgress(listener: ProgressListener): () => void {
  if (latestProgress) listener(latestProgress.loaded, latestProgress.total);
  progressListeners.add(listener);
  return () => progressListeners.delete(listener);
}

function waitForReady(worker: Worker): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error("Timed out loading the on-device speech recognition engine."));
    }, WORKER_READY_TIMEOUT_MS);

    function cleanup() {
      clearTimeout(timeout);
      worker.removeEventListener("message", onMessage);
      worker.removeEventListener("error", onWorkerError);
    }
    function onMessage(ev: MessageEvent<WorkerToMainMessage>) {
      const msg = ev.data;
      if (msg.type === "ready") {
        cleanup();
        resolve();
      } else if (msg.type === "progress") {
        notifyProgress(msg.loaded, msg.total);
      } else if (msg.type === "error") {
        cleanup();
        reject(new Error(msg.message));
      }
    }
    function onWorkerError(ev: ErrorEvent) {
      cleanup();
      reject(new Error(ev.message || "Failed to load the speech recognition worker."));
    }

    worker.addEventListener("message", onMessage);
    worker.addEventListener("error", onWorkerError);
  });
}

/** Starts loading both workers if they haven't been already -- safe to call more than once
 * (a repeat call just returns the same in-flight/already-resolved promise), and safe to call
 * speculatively before this page is actually cross-origin isolated yet (it then simply fails
 * the same way createSherpaLiveEngine's own call into this always has, just discovered in
 * the background instead of only once the user clicks Record). Call this as soon as the live
 * page mounts (see page.tsx) rather than waiting for a recording session to actually start --
 * the one-time ~95MB download/init is by far the slowest part of starting a session, so
 * paying for it while the user is still looking at the page (or deciding whether to record)
 * avoids the "Starting..." wait happening only after they've already clicked. */
export function preloadLiveEngine(): Promise<void> {
  if (!vadAsrWorker) {
    vadAsrWorker = new Worker(WORKER_URL);
    vadAsrWorkerReady = waitForReady(vadAsrWorker);
  }
  if (!embeddingWorkerInstance) {
    embeddingWorkerInstance = new Worker(EMBEDDING_WORKER_URL);
  }
  return vadAsrWorkerReady!;
}

export const createSherpaLiveEngine: LiveEngineFactory = async (
  callbacks: LiveEngineCallbacks,
): Promise<LiveEngineHandle> => {
  const unsubscribeProgress = callbacks.onLoadProgress ? subscribeToLoadProgress(callbacks.onLoadProgress) : null;
  try {
    await preloadLiveEngine();
  } finally {
    unsubscribeProgress?.();
  }

  const worker = vadAsrWorker!;
  // Not gated on its own readiness the way the vad-asr worker is above -- embedding is a
  // best-effort layer on top of the transcript (see workers/embeddingWorker.ts), so
  // recording can start as soon as VAD+ASR are ready. If this worker is slow to load (or
  // fails/crashes), embedSegment's own timeout/error handling below just resolves every
  // request with no embedding instead of blocking anything.
  const embeddingWorker = embeddingWorkerInstance!;

  let nextTurnId = 0;
  const pendingEmbeds = new Map<number, (embedding: Float32Array | null) => void>();

  // Named (not inline) so dispose() can remove exactly this session's listener -- both
  // workers are now shared across every session in this page visit, so a listener left
  // behind from a previous (stopped) session would otherwise keep firing into that old
  // session's now-irrelevant closures indefinitely.
  function onEmbeddingMessage(ev: MessageEvent<EmbeddingWorkerToMainMessage>) {
    const msg = ev.data;
    const resolve = pendingEmbeds.get(msg.turnId);
    if (resolve) {
      pendingEmbeds.delete(msg.turnId);
      resolve(msg.embedding);
    }
  }
  embeddingWorker.addEventListener("message", onEmbeddingMessage);

  function embedSegment(samples: Float32Array): Promise<Float32Array | null> {
    const turnId = nextTurnId++;
    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        pendingEmbeds.delete(turnId);
        resolve(null);
      }, EMBED_TIMEOUT_MS);
      pendingEmbeds.set(turnId, (embedding) => {
        clearTimeout(timeout);
        resolve(embedding);
      });
      embeddingWorker.postMessage(
        { type: "embed", turnId, samples } satisfies MainToEmbeddingWorkerMessage,
        [samples.buffer],
      );
    });
  }

  let audioContext: AudioContext | null = null;
  let sourceNode: MediaStreamAudioSourceNode | null = null;
  let workletNode: AudioWorkletNode | null = null;
  let silentGain: GainNode | null = null;
  let disposed = false;

  function postToWorker(message: MainToWorkerMessage, transfer?: Transferable[]) {
    worker.postMessage(message, transfer ?? []);
  }

  // A "final" message's onFinal delivery is now async (it waits on embedSegment below), so
  // the vad-asr worker's "flushed" ack -- which only guarantees every trailing `final`
  // postMessage has been *sent* -- is no longer enough on its own for stop() to know every
  // trailing turn has actually reached callbacks.onFinal yet. Tracked here so stop() can
  // await the lot of them after "flushed" arrives, instead of (rarely, but really) racing a
  // dropped last turn if its embedding was still pending when stop() returned.
  const pendingFinalizations = new Set<Promise<void>>();

  function onWorkerMessage(ev: MessageEvent<WorkerToMainMessage>) {
    const msg = ev.data;
    if (msg.type === "partial") {
      callbacks.onPartial(msg.text);
    } else if (msg.type === "final") {
      // Held until the embedding resolves (or times out) before calling onFinal, so the
      // external per-turn contract is exactly what it was before embedding moved to its own
      // worker -- one onFinal call per turn, embedding already decided one way or the other.
      // This does make a turn's text arrive slightly later than it would if onFinal fired
      // immediately, but the vad-asr worker itself is never blocked by it: it's already free
      // to keep decoding the next turn's audio while this promise is still pending.
      const finalization = embedSegment(msg.samples).then((embedding) => {
        const turn: LiveTurn = {
          text: msg.text,
          startTs: msg.startTs,
          endTs: msg.endTs,
          embedding: embedding ?? undefined,
        };
        callbacks.onFinal(turn);
      });
      pendingFinalizations.add(finalization);
      finalization.finally(() => pendingFinalizations.delete(finalization));
    } else if (msg.type === "error") {
      callbacks.onError(msg.message);
    }
    // "progress"/"ready" are consumed by preloadLiveEngine's own listener (via waitForReady,
    // long since torn down by the time a session exists); "flushed" acks are consumed
    // directly by stop()'s own one-shot listener below.
  }
  function onWorkerError(ev: ErrorEvent) {
    callbacks.onError(ev.message || "Speech recognition worker crashed.");
  }
  worker.addEventListener("message", onWorkerMessage);
  worker.addEventListener("error", onWorkerError);

  function disconnectAudioGraph() {
    sourceNode?.disconnect();
    workletNode?.disconnect();
    silentGain?.disconnect();
    sourceNode = null;
    workletNode = null;
    silentGain = null;
  }

  return {
    async start(stream: MediaStream) {
      audioContext = new AudioContext();
      await audioContext.audioWorklet.addModule(PCM_PROCESSOR_URL);

      sourceNode = audioContext.createMediaStreamSource(stream);
      workletNode = new AudioWorkletNode(audioContext, "pcm-capture-processor");
      workletNode.port.onmessage = (ev: MessageEvent<Float32Array>) => {
        const samples = ev.data;
        postToWorker({ type: "pcm", samples, sampleRate: audioContext!.sampleRate }, [samples.buffer]);
      };

      // An AudioWorkletNode only keeps being pulled for audio while it's part of a graph
      // that reaches the destination. Route through a muted gain node so capture keeps
      // running without audibly looping the mic back to the speakers.
      silentGain = audioContext.createGain();
      silentGain.gain.value = 0;
      sourceNode.connect(workletNode);
      workletNode.connect(silentGain);
      silentGain.connect(audioContext.destination);
    },

    // Suspending the AudioContext stops the AudioWorkletNode from being pulled for audio at
    // all -- no PCM reaches the vad-asr worker while paused -- without disconnecting the
    // graph or touching any VAD/ASR state, so resume() continues the in-progress utterance
    // exactly where it left off instead of starting a new one.
    async pause() {
      if (audioContext && audioContext.state === "running") {
        await audioContext.suspend();
      }
    },

    async resume() {
      if (audioContext && audioContext.state === "suspended") {
        await audioContext.resume();
      }
    },

    async stop() {
      disconnectAudioGraph();

      if (!disposed) {
        await new Promise<void>((resolve) => {
          const timeout = setTimeout(() => {
            worker.removeEventListener("message", onFlushed);
            resolve();
          }, FLUSH_TIMEOUT_MS);
          function onFlushed(ev: MessageEvent<WorkerToMainMessage>) {
            if (ev.data.type === "flushed") {
              clearTimeout(timeout);
              worker.removeEventListener("message", onFlushed);
              resolve();
            }
          }
          worker.addEventListener("message", onFlushed);
          postToWorker({ type: "flush" });
        });
        // "flushed" only guarantees every trailing `final` has been *sent* -- wait for their
        // embedding+onFinal chains to actually finish too (see pendingFinalizations above),
        // so a caller awaiting stop() is guaranteed every turn has already reached onFinal
        // before it proceeds (e.g. page.tsx reading its own turns state right after this).
        await Promise.all(pendingFinalizations);
      }

      if (audioContext && audioContext.state !== "closed") {
        await audioContext.close();
      }
      audioContext = null;
    },

    // Deliberately does NOT terminate either worker any more -- they're a page-lifetime pool
    // (see the module comment above), reused by the next recording session in this same
    // visit. Only this session's own listeners and audio graph are torn down.
    dispose() {
      disposed = true;
      disconnectAudioGraph();
      worker.removeEventListener("message", onWorkerMessage);
      worker.removeEventListener("error", onWorkerError);
      embeddingWorker.removeEventListener("message", onEmbeddingMessage);
      if (audioContext && audioContext.state !== "closed") {
        audioContext.close().catch(() => {});
      }
      audioContext = null;
    },
  };
};
