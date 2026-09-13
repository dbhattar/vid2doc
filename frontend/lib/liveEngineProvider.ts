import type { LiveEngineFactory } from "@/lib/liveEngine";
import { createSherpaLiveEngine } from "@/lib/sherpaLiveEngine";

// Single switch point: sherpaLiveEngine.ts wires up the real, on-device engine (VAD-based
// turn-by-turn ASR via sherpa-onnx's official vad-asr WASM build, plus our custom
// speaker-embedding WASM build for turn-by-turn LiveTurn.embedding -- see
// plan/realtime-diarization-plan.md and workers/vadAsrWorker.ts's module comment).
// LiveTurn.embedding can still come back undefined per-turn in practice (the embedding
// module loads independently and may not be ready yet for an early turn, or extraction can
// fail for an unusually short/quiet segment) -- the live page already degrades to a single
// "Speaker 1" label for those, by design, not as a placeholder for unfinished wiring.
export const createLiveEngine: LiveEngineFactory = createSherpaLiveEngine;
