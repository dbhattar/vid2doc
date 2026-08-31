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

/** A lightweight, non-final preview of the turn currently being spoken -- produced by
 * re-decoding the growing in-progress utterance on a timer, since this WASM build's VAD +
 * offline-ASR architecture has no native word-by-word streaming partials (see
 * plan/realtime-diarization-plan.md and the worker's module comment for why). */
export type PartialMessage = { type: "partial"; text: string };

/** A VAD-endpointed turn has been fully decoded. `startTs`/`endTs` are seconds since this
 * worker (i.e. this recording session) started, matching LiveTurn's contract. */
export type FinalMessage = { type: "final"; text: string; startTs: number; endTs: number };

/** Acks a `flush` request once any trailing speech has been drained into `final` messages
 * (or determined to be empty) -- lets stop() know it's safe to tear the worker down. */
export type FlushedMessage = { type: "flushed" };

export type WorkerErrorMessage = { type: "error"; message: string };

export type WorkerToMainMessage =
  | ReadyMessage
  | PartialMessage
  | FinalMessage
  | FlushedMessage
  | WorkerErrorMessage;
