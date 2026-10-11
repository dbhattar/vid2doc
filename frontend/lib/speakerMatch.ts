// Turn-by-turn speaker assignment for the live recording page: given a new
// speaker embedding, either match it to a speaker already seen this session
// (cosine similarity above `threshold`, with a clear enough margin over the
// next-best candidate to actually trust it) or register a new one. Mirrors
// the ordering convention backend/app/pipeline.py's _normalize_speaker_labels
// already uses server-side (labels assigned "Speaker 1", "Speaker 2", ... in
// order of first appearance), just running client-side on live embeddings
// instead of a finished batch transcript. Kept as a small pure function
// (no WASM/model dependency) so it's directly unit-testable -- see
// speakerMatch.test.ts.
//
// Each speaker's reference is a running centroid (not a single frozen
// embedding) -- see updateCentroid below -- so later turns, including short
// ones that only barely clear the embedding worker's duration floor, match
// against a reference that's been calibrated by every confident match so
// far rather than just whichever embedding happened to be registered first
// (which could itself have been short/noisy). See
// plan/live-diarization-accuracy-plan.md for the full rationale.
export type SpeakerRegistry = {
  labels: string[];
  centroids: Float32Array[];
  // How many confident matches have been folded into each centroid so far
  // (capped at CENTROID_CAP for the update-weight calculation, but kept
  // uncapped here for debugging/introspection).
  sampleCounts: number[];
};

export function createSpeakerRegistry(): SpeakerRegistry {
  return { labels: [], centroids: [], sampleCounts: [] };
}

function cosineSimilarity(a: Float32Array, b: Float32Array): number {
  let dot = 0;
  let normA = 0;
  let normB = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  if (normA === 0 || normB === 0) return 0;
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

// Caps how much weight a single new embedding carries in a centroid's running mean once a
// speaker has accumulated this many confident matches -- without a cap, turn ~200's update
// weight (1/201) is small enough that the centroid is effectively frozen anyway by then,
// defeating the point of tracking a running centroid at all instead of a fixed reference. 20
// is a starting value (see plan/live-diarization-accuracy-plan.md) deliberately left to be
// tuned against the eval harness rather than treated as final.
const CENTROID_CAP = 20;

function updateCentroid(centroid: Float32Array, embedding: Float32Array, priorCount: number): void {
  const n = Math.min(priorCount, CENTROID_CAP);
  for (let d = 0; d < centroid.length; d++) {
    centroid[d] += (embedding[d] - centroid[d]) / (n + 1);
  }
}

export type SpeakerMatch = {
  label: string;
  /** False when the best candidate's score cleared `threshold` but not by a
   * wide enough margin over the next-best candidate to actually trust it --
   * callers should NOT treat `label` as a real identity decision in that
   * case (fall back to whatever the previous turn's speaker was instead),
   * and must not fold the embedding into that speaker's centroid. */
  confident: boolean;
};

/** Mutates `registry` in place (adds a new speaker, or folds a confidently-matched embedding
 * into an existing speaker's running centroid) and returns the label plus whether the match
 * was actually confident enough to trust. */
export function matchOrRegisterSpeaker(
  registry: SpeakerRegistry,
  embedding: Float32Array,
  options?: { threshold?: number; minMargin?: number },
): SpeakerMatch {
  const threshold = options?.threshold ?? 0.5;
  // 0.15 is conservative against the documented ~0.91 same-speaker vs. ~0.11
  // different-speaker cosine gap (frontend/native/sherpa-speaker-embedding/README.md) --
  // another value to validate against the eval harness rather than treat as final.
  const minMargin = options?.minMargin ?? 0.15;

  let bestIndex = -1;
  let bestScore = -Infinity;
  let secondBestScore = -Infinity;
  for (let i = 0; i < registry.centroids.length; i++) {
    const score = cosineSimilarity(embedding, registry.centroids[i]);
    if (score > bestScore) {
      secondBestScore = bestScore;
      bestScore = score;
      bestIndex = i;
    } else if (score > secondBestScore) {
      secondBestScore = score;
    }
  }

  // With fewer than 2 known speakers there's nothing to disambiguate against yet -- the
  // margin check would otherwise compare against -Infinity and trivially "pass" (or, with
  // exactly one registered speaker, has no second candidate to be confused with at all), so
  // skip it rather than let it vacuously succeed or fail.
  const hasMargin = registry.centroids.length < 2 || bestScore - secondBestScore >= minMargin;

  if (bestIndex !== -1 && bestScore >= threshold && hasMargin) {
    updateCentroid(registry.centroids[bestIndex], embedding, registry.sampleCounts[bestIndex]);
    registry.sampleCounts[bestIndex] += 1;
    return { label: registry.labels[bestIndex], confident: true };
  }

  if (bestIndex !== -1 && bestScore >= threshold) {
    // Scored above threshold but too close to a second candidate to trust -- genuinely
    // ambiguous evidence, not strong evidence of a NEW speaker either. Don't register
    // anything or touch any centroid; let the caller fall back to "assume same as whoever
    // was just speaking" (safer than a hasty new registration from weak evidence).
    return { label: registry.labels[bestIndex], confident: false };
  }

  const label = `Speaker ${registry.labels.length + 1}`;
  registry.labels.push(label);
  registry.centroids.push(embedding.slice());
  registry.sampleCounts.push(1);
  return { label, confident: true };
}
