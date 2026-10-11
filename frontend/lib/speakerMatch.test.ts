import { describe, expect, it } from "vitest";

import { createSpeakerRegistry, matchOrRegisterSpeaker } from "./speakerMatch";

// Small, hand-verifiable 3-dim "embeddings" standing in for the real 192-dim ERes2Net
// vectors -- cosine similarity is dimension-agnostic, so these are enough to exercise every
// branch of matchOrRegisterSpeaker (confident match, low-margin rejection, new-speaker
// registration, centroid updates) with numbers that are easy to verify by hand.
const SPEAKER_A = new Float32Array([1, 0, 0]);
const SPEAKER_B = new Float32Array([0, 1, 0]);
const ORTHOGONAL_TO_BOTH = new Float32Array([0, 0, 1]);

describe("matchOrRegisterSpeaker", () => {
  it("registers the first embedding as Speaker 1, confidently", () => {
    const registry = createSpeakerRegistry();
    const match = matchOrRegisterSpeaker(registry, SPEAKER_A);
    expect(match).toEqual({ label: "Speaker 1", confident: true });
    expect(registry.labels).toEqual(["Speaker 1"]);
    expect(registry.sampleCounts).toEqual([1]);
  });

  it("matches a near-identical embedding to the same speaker, confidently", () => {
    const registry = createSpeakerRegistry();
    matchOrRegisterSpeaker(registry, SPEAKER_A);
    const nearlyA = new Float32Array([0.98, 0.1, 0]); // cosine with [1,0,0] ~= 0.995
    const match = matchOrRegisterSpeaker(registry, nearlyA);
    expect(match).toEqual({ label: "Speaker 1", confident: true });
    expect(registry.labels).toEqual(["Speaker 1"]);
  });

  it("registers a new speaker for an embedding far from the only known one", () => {
    const registry = createSpeakerRegistry();
    matchOrRegisterSpeaker(registry, SPEAKER_A);
    const match = matchOrRegisterSpeaker(registry, ORTHOGONAL_TO_BOTH); // cosine ~= 0
    expect(match).toEqual({ label: "Speaker 2", confident: true });
    expect(registry.labels).toEqual(["Speaker 1", "Speaker 2"]);
  });

  it("accepts a score right at the threshold when there's only one known speaker (no margin check yet)", () => {
    const registry = createSpeakerRegistry();
    matchOrRegisterSpeaker(registry, SPEAKER_A);
    // cosine([1,0,0], [0.5, sqrt(3)/2, 0]) = 0.5 exactly -- the default threshold's boundary.
    const atThreshold = new Float32Array([0.5, Math.sqrt(3) / 2, 0]);
    const match = matchOrRegisterSpeaker(registry, atThreshold);
    expect(match).toEqual({ label: "Speaker 1", confident: true });
  });

  it("registers a new speaker when the score is simply below threshold (not an ambiguity case)", () => {
    const registry = createSpeakerRegistry();
    matchOrRegisterSpeaker(registry, SPEAKER_A);
    // cosine with [1,0,0] is well under 0.5 -- not an ambiguity case, just a genuine miss.
    const match = matchOrRegisterSpeaker(registry, SPEAKER_B);
    expect(match).toEqual({ label: "Speaker 2", confident: true });
  });

  it("rejects a confident match when two known speakers are too close to call (low margin)", () => {
    const registry = createSpeakerRegistry();
    matchOrRegisterSpeaker(registry, SPEAKER_A); // Speaker 1
    matchOrRegisterSpeaker(registry, SPEAKER_B); // Speaker 2
    // Equidistant between A and B (cosine ~=0.707 against both) -- above the 0.5 threshold
    // against the best candidate, but zero margin over the second-best.
    const ambiguous = new Float32Array([0.7, 0.7, 0]);
    const match = matchOrRegisterSpeaker(registry, ambiguous);
    expect(match.confident).toBe(false);
    // Must not register a third speaker or mutate either existing centroid/count from weak,
    // ambiguous evidence.
    expect(registry.labels).toEqual(["Speaker 1", "Speaker 2"]);
    expect(registry.sampleCounts).toEqual([1, 1]);
    expect(registry.centroids[0]).toEqual(SPEAKER_A);
    expect(registry.centroids[1]).toEqual(SPEAKER_B);
  });

  it("folds a confident match into a running centroid instead of leaving the reference frozen", () => {
    const registry = createSpeakerRegistry();
    matchOrRegisterSpeaker(registry, SPEAKER_A); // centroid = [1,0,0], n=1
    const secondSample = new Float32Array([0.6, 0.6, 0]); // cosine with [1,0,0] ~= 0.707
    const match = matchOrRegisterSpeaker(registry, secondSample);
    expect(match).toEqual({ label: "Speaker 1", confident: true });
    expect(registry.sampleCounts).toEqual([2]);
    // Incremental mean with n=1 (prior count): centroid += (sample - centroid) / 2.
    const centroid = registry.centroids[0];
    expect(centroid[0]).toBeCloseTo(0.8, 5);
    expect(centroid[1]).toBeCloseTo(0.3, 5);
    expect(centroid[2]).toBeCloseTo(0, 5);
  });

  it("caps the running-mean update weight so a centroid can still adapt late in a long session", () => {
    const registry = createSpeakerRegistry();
    matchOrRegisterSpeaker(registry, SPEAKER_A);
    // Feed enough confident matches of the same vector to exceed CENTROID_CAP (20) --
    // sampleCounts keeps counting uncapped, but the update weight itself should plateau.
    for (let i = 0; i < 25; i++) {
      matchOrRegisterSpeaker(registry, SPEAKER_A);
    }
    expect(registry.sampleCounts).toEqual([26]);
    // Every fold-in so far has been the exact same vector as the centroid itself, so the
    // centroid should still read as exactly SPEAKER_A regardless of the cap -- this just
    // confirms the loop didn't throw/diverge and the count accounting is uncapped while the
    // weight calculation (exercised directly below) is capped.
    expect(registry.centroids[0]).toEqual(SPEAKER_A);

    // Now fold in a genuinely different sample and confirm the update weight matches a
    // capped n=20, not the true prior count of 26 (1/21 vs. the uncapped 1/27).
    const registry2 = createSpeakerRegistry();
    matchOrRegisterSpeaker(registry2, SPEAKER_A);
    for (let i = 0; i < 25; i++) {
      matchOrRegisterSpeaker(registry2, SPEAKER_A);
    }
    const closeNudge = new Float32Array([0.9, Math.sqrt(1 - 0.81), 0]); // cosine with [1,0,0] = 0.9
    matchOrRegisterSpeaker(registry2, closeNudge);
    const n = 20; // capped, not the true prior count of 26
    const expectedX = 1 + (closeNudge[0] - 1) / (n + 1);
    const expectedY = 0 + (closeNudge[1] - 0) / (n + 1);
    expect(registry2.centroids[0][0]).toBeCloseTo(expectedX, 5);
    expect(registry2.centroids[0][1]).toBeCloseTo(expectedY, 5);
  });

  it("respects explicit threshold/minMargin overrides", () => {
    const registry = createSpeakerRegistry();
    matchOrRegisterSpeaker(registry, SPEAKER_A);
    matchOrRegisterSpeaker(registry, SPEAKER_B);
    const ambiguous = new Float32Array([0.7, 0.7, 0]); // ~0.707 vs both, margin ~0
    // With minMargin relaxed to 0, the tie no longer gets rejected.
    const relaxed = matchOrRegisterSpeaker(registry, ambiguous, { minMargin: 0 });
    expect(relaxed.confident).toBe(true);
  });
});
