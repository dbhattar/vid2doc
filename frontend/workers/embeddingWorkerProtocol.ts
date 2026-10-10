// Message protocol between the main thread (lib/sherpaLiveEngine.ts) and the dedicated
// speaker-embedding worker (workers/embeddingWorker.ts). Kept as its own tiny types-only
// module, same convention as ./vadAsrProtocol.ts -- erased at compile time, adds no runtime
// code to either bundle.
//
// This worker exists separately from workers/vadAsrWorker.ts specifically so a slow
// embedding computation never delays that worker's own processing of the next incoming
// audio chunk -- both WASM modules used to run on one shared worker thread, which is
// inherently serial; see workers/vadAsrWorker.ts's and lib/sherpaLiveEngine.ts's comments
// for the full history.

/** One VAD-finalized turn's raw (16kHz) audio samples, sent for embedding extraction.
 * `turnId` is an opaque, monotonically increasing counter sherpaLiveEngine.ts assigns per
 * turn so a response can be matched back to the request that produced it (the two workers
 * process independently, so responses aren't guaranteed to arrive in request order if this
 * worker is ever extended to pipeline multiple requests). */
export type EmbedRequestMessage = { type: "embed"; turnId: number; samples: Float32Array };

export type MainToEmbeddingWorkerMessage = EmbedRequestMessage;

/** `embedding` is null (never a worker-level error) whenever the module isn't ready yet, the
 * segment was too short to embed reliably, or extraction failed for this turn -- same
 * best-effort/never-fatal contract workers/vadAsrWorker.ts's computeEmbeddingForSegment used
 * to have, just relocated. Callers should degrade to the previous turn's speaker, per
 * lib/liveEngine.ts's LiveTurn.embedding doc comment. */
export type EmbeddingResultMessage = { type: "embedding"; turnId: number; embedding: Float32Array | null };

export type EmbeddingWorkerToMainMessage = EmbeddingResultMessage;
