// Message protocol between the main thread (lib/sherpaLiveEngine.ts) and the dedicated
// vad-asr worker (workers/vadAsrWorker.ts). Kept as its own tiny types-only module so both
// sides stay in sync -- these are erased at compile time, so importing this file adds no
// runtime code to either the worker bundle or the main bundle.

/** Raw PCM chunk captured off the mic, forwarded up from workers/pcmProcessor.ts via the
 * main thread. `sampleRate` is the AudioContext's native rate the samples were captured
 * at -- the worker downsamples to the 16kHz the models expect. */
export type PcmChunkMessage = {
  type: "pcm";
  samples: Float32Array;
  sampleRate: number;
};

/** Sent on stop(): flush any speech VAD is still holding (without waiting for trailing
 * silence) so a turn in progress when the user hits Stop isn't silently dropped. */
export type FlushMessage = { type: "flush" };

export type MainToWorkerMessage = PcmChunkMessage | FlushMessage;

export type ReadyMessage = { type: "ready" };

/** Real byte-level download progress for the ~58MB WASM+model bundle, forwarded from the
 * vendored glue script's own `Module.setStatus` hook (see vadAsrWorker.ts's
 * applyModuleConfig) while it fetches its preloaded `.data` package. Purely cosmetic --
 * doesn't speed anything up -- but lets the live page show real progress instead of a
 * generic "Starting..." label during the first load. */
export type ProgressMessage = { type: "progress"; loaded: number; total: number };

/** A lightweight, non-final preview of the turn currently being spoken -- produced by
 * re-decoding the growing in-progress utterance on a timer, since this WASM build's VAD +
 * offline-ASR architecture has no native word-by-word streaming partials (see
 * plan/realtime-diarization-plan.md and the worker's module comment for why). */
export type PartialMessage = { type: "partial"; text: string };

/** A VAD-endpointed turn has been fully decoded. `startTs`/`endTs` are seconds since this
 * worker (i.e. this recording session) started, matching LiveTurn's contract. `samples` is
 * this turn's raw 16kHz audio (transferred, not copied) -- lib/sherpaLiveEngine.ts forwards
 * it to the separate speaker-embedding worker (workers/embeddingWorker.ts) rather than this
 * worker computing an embedding itself, so a slow embedding call never delays this worker's
 * own processing of the next incoming audio chunk. */
export type FinalMessage = {
  type: "final";
  text: string;
  startTs: number;
  endTs: number;
  samples: Float32Array;
};

/** Acks a `flush` request once any trailing speech has been drained into `final` messages
 * (or determined to be empty) -- lets stop() know it's safe to tear the worker down. */
export type FlushedMessage = { type: "flushed" };

export type WorkerErrorMessage = { type: "error"; message: string };

export type WorkerToMainMessage =
  | ReadyMessage
  | ProgressMessage
  | PartialMessage
  | FinalMessage
  | FlushedMessage
  | WorkerErrorMessage;
