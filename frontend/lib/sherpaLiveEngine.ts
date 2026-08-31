// Real implementation of LiveEngineFactory (see lib/liveEngine.ts), backed by
// sherpa-onnx's official `vad-asr` WebAssembly build running entirely on-device (see
// plan/realtime-diarization-plan.md). This file owns everything on the main thread: mic
// capture via an AudioWorkletNode (raw PCM, not MediaRecorder -- the recognizer needs
// samples, not a compressed container), and talking to the dedicated
// workers/vadAsrWorker.ts over postMessage. All WASM/model loading and inference happens
// in that worker, off the UI thread; this file only ever sees partial/final text and
// timestamps coming back.
import type { LiveEngineCallbacks, LiveEngineFactory, LiveEngineHandle, LiveTurn } from "@/lib/liveEngine";
import type { MainToWorkerMessage, WorkerToMainMessage } from "@/workers/vadAsrProtocol";

// Generous: first load fetches ~55MB of WASM + bundled models from public/wasm/vad-asr/
// and compiles the module -- see plan/realtime-diarization-plan.md for the size tradeoff.
const WORKER_READY_TIMEOUT_MS = 30000;
// How long stop() waits for the worker to finish flushing a trailing in-progress turn
// before giving up and tearing down anyway.
const FLUSH_TIMEOUT_MS = 3000;

// Loaded as a plain static file (compiled by "npm run build:workers", see
// tsconfig.workers.json) rather than via Next/Turbopack's `new Worker(new URL(...))`
// bundling -- as of Next.js 16.2.10, Turbopack doesn't actually compile the referenced
// TypeScript for that pattern, it serves the raw .ts source verbatim as a static-media
// response (confirmed directly against `next dev`), which a JS engine can't execute as a
// worker. See the comment at the top of workers/vadAsrWorker.ts for the full story.
const WORKER_URL = "/workers/vadAsrWorker.js";
const PCM_PROCESSOR_URL = "/workers/pcmProcessor.js";

function createWorker(): Worker {
  return new Worker(WORKER_URL);
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

export const createSherpaLiveEngine: LiveEngineFactory = async (
  callbacks: LiveEngineCallbacks,
): Promise<LiveEngineHandle> => {
  const worker = createWorker();

  try {
    await waitForReady(worker);
  } catch (err) {
    worker.terminate();
    throw err;
  }

  let audioContext: AudioContext | null = null;
  let sourceNode: MediaStreamAudioSourceNode | null = null;
  let workletNode: AudioWorkletNode | null = null;
  let silentGain: GainNode | null = null;
  let disposed = false;

  function postToWorker(message: MainToWorkerMessage, transfer?: Transferable[]) {
    worker.postMessage(message, transfer ?? []);
  }

  function onWorkerMessage(ev: MessageEvent<WorkerToMainMessage>) {
    const msg = ev.data;
    if (msg.type === "partial") {
      callbacks.onPartial(msg.text);
    } else if (msg.type === "final") {
      const turn: LiveTurn = { text: msg.text, startTs: msg.startTs, endTs: msg.endTs };
      callbacks.onFinal(turn);
    } else if (msg.type === "error") {
      callbacks.onError(msg.message);
    }
    // "flushed" acks are consumed directly by stop()'s own one-shot listener below.
  }
  worker.addEventListener("message", onWorkerMessage);
  worker.addEventListener("error", (ev) => callbacks.onError(ev.message || "Speech recognition worker crashed."));

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
      }

      if (audioContext && audioContext.state !== "closed") {
        await audioContext.close();
      }
      audioContext = null;
    },

    dispose() {
      disposed = true;
      disconnectAudioGraph();
      worker.removeEventListener("message", onWorkerMessage);
      worker.terminate();
      if (audioContext && audioContext.state !== "closed") {
        audioContext.close().catch(() => {});
      }
      audioContext = null;
    },
  };
};
