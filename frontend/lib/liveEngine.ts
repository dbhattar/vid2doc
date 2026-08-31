// The contract between the live-recording page and whichever WASM engine
// actually does the on-device work (sherpa-onnx's official vad-asr build for
// streaming captions, plus our custom speaker-embedding build for real-time
// diarization -- see plan/realtime-diarization-plan.md). Kept as its own
// module so the page can be built and reviewed against a stable interface
// while the WASM integration underneath it lands separately.
//
// `embedding` is omitted when the speaker-embedding model isn't available
// yet (e.g. still loading, or unsupported browser) -- callers should fall
// back to a single default speaker label rather than fail, per the plan's
// "labels only at Stop" degradation path.
export type LiveTurn = {
  text: string;
  startTs: number;
  endTs: number;
  embedding?: Float32Array;
};

export type LiveEngineCallbacks = {
  onPartial: (text: string) => void;
  onFinal: (turn: LiveTurn) => void;
  /** Fatal engine error (e.g. WASM/model failed to load) -- the page should
   * surface this and let the user retry, not keep waiting silently. */
  onError: (message: string) => void;
};

export interface LiveEngineHandle {
  start(stream: MediaStream): Promise<void>;
  stop(): Promise<void>;
  dispose(): void;
}

export type LiveEngineFactory = (callbacks: LiveEngineCallbacks) => Promise<LiveEngineHandle>;
