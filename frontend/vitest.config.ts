import { defineConfig } from "vitest/config";

// Minimal, deliberately -- this project has no other test infrastructure (see
// plan/live-diarization-accuracy-plan.md's Tier 3). Only covers plain TypeScript
// logic (e.g. lib/speakerMatch.ts) with no WASM/browser dependency; the
// WASM-dependent audio-clip eval lives separately as a Node script under
// native/sherpa-speaker-embedding/ (see that directory's eval-diarization.js).
export default defineConfig({
  test: {
    environment: "node",
    include: ["**/*.test.ts"],
  },
});
