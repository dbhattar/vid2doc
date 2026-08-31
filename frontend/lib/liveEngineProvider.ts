import type { LiveEngineFactory } from "@/lib/liveEngine";
import { createSherpaLiveEngine } from "@/lib/sherpaLiveEngine";

// Single switch point: sherpaLiveEngine.ts wires up the real, on-device engine (VAD-based
// turn-by-turn ASR via sherpa-onnx's official vad-asr WASM build -- see
// plan/realtime-diarization-plan.md). Turn-by-turn speaker embeddings are a separate,
// independently-landing piece (lib/speakerMatch.ts) -- LiveTurn.embedding is left
// undefined until that's wired in here too, and the live page already degrades to a
// single "Speaker 1" label when it's absent. Nothing else in the live page needs to
// change, since the page is written against the LiveEngineFactory contract, not this file.
export const createLiveEngine: LiveEngineFactory = createSherpaLiveEngine;
