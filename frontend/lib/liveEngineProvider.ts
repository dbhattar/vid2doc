import type { LiveEngineFactory } from "@/lib/liveEngine";
import { createSherpaLiveEngine, preloadLiveEngine, subscribeToLoadProgress } from "@/lib/sherpaLiveEngine";

// Single switch point: sherpaLiveEngine.ts wires up the real, on-device engine (VAD-based
// turn-by-turn ASR via sherpa-onnx's official vad-asr WASM build, plus our custom
// speaker-embedding WASM build for turn-by-turn LiveTurn.embedding -- see
// plan/realtime-diarization-plan.md and workers/vadAsrWorker.ts's module comment).
// LiveTurn.embedding can still come back undefined per-turn in practice (the embedding
// module loads independently and may not be ready yet for an early turn, or extraction can
// fail for an unusually short/quiet segment) -- the live page already degrades to a single
// "Speaker 1" label for those, by design, not as a placeholder for unfinished wiring.
export const createLiveEngine: LiveEngineFactory = createSherpaLiveEngine;

// Re-exported so the live page can kick off (and show progress for) the engine's one-time
// WASM/model load as soon as it mounts, well before the user has clicked Record -- see
// sherpaLiveEngine.ts's preloadLiveEngine() for why that's safe to call speculatively and
// why it doesn't redo work a later createLiveEngine() call would otherwise repeat.
export { preloadLiveEngine, subscribeToLoadProgress };
