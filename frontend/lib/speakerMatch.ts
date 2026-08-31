// Turn-by-turn speaker assignment for the live recording page: given a new
// speaker embedding, either match it to a speaker already seen this session
// (cosine similarity above `threshold`) or register a new one. Mirrors the
// ordering convention backend/app/pipeline.py's _normalize_speaker_labels
// already uses server-side (labels assigned "Speaker 1", "Speaker 2", ... in
// order of first appearance), just running client-side on live embeddings
// instead of a finished batch transcript. Kept as a small pure function
// (no WASM/model dependency) so it's directly unit-testable.
export type SpeakerRegistry = { labels: string[]; embeddings: Float32Array[] };

export function createSpeakerRegistry(): SpeakerRegistry {
  return { labels: [], embeddings: [] };
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

/** Mutates `registry` in place (adds a new speaker if no existing one is
 * close enough) and returns the label the given embedding was assigned. */
// 0.5 is a safe default: the custom sherpa-onnx speaker-embedding WASM build
// (frontend/native/sherpa-speaker-embedding/, VoxCeleb-trained English
// model) measured same-speaker cosine similarity around 0.91-0.92 vs.
// different-speaker around 0.11 on real speech -- see that directory's
// README for the full spike results.
export function matchOrRegisterSpeaker(
  registry: SpeakerRegistry,
  embedding: Float32Array,
  threshold = 0.5,
): string {
  let bestIndex = -1;
  let bestScore = -Infinity;
  for (let i = 0; i < registry.embeddings.length; i++) {
    const score = cosineSimilarity(embedding, registry.embeddings[i]);
    if (score > bestScore) {
      bestScore = score;
      bestIndex = i;
    }
  }

  if (bestIndex !== -1 && bestScore >= threshold) {
    return registry.labels[bestIndex];
  }

  const label = `Speaker ${registry.labels.length + 1}`;
  registry.labels.push(label);
  registry.embeddings.push(embedding);
  return label;
}
