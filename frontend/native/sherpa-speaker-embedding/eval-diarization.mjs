#!/usr/bin/env node
// Minimal diarization-accuracy eval -- see plan/live-diarization-accuracy-plan.md's Tier 3.
//
// Scope, and why it's narrower than that plan's original description: this validates
// lib/speakerMatch.ts's matching/centroid logic (T1.2/T1.3) against REAL embeddings
// extracted from real (synthetic) short audio via the actual embedding WASM module -- the
// most directly testable part of the Tier 1 changes outside a browser. It deliberately does
// NOT exercise real VAD segmentation or the ASR model: the vendored vad-asr WASM build
// (public/wasm/v1/vad-asr/) is a plain global-scope Emscripten build (not the
// MODULARIZE=1/require()-friendly style the embedding build uses) whose pthread bootstrap
// unconditionally needs a browser's cross-origin-isolated SharedArrayBuffer transfer at load
// time -- getting it to run outside a browser at all would be its own significant, uncertain
// side project, not a quick addition to this harness. Ground-truth turn BOUNDARIES below are
// therefore taken directly from generate-eval-clips.mjs's own known construction (it placed
// every utterance at an exact sample offset), standing in for what VAD would have produced --
// this is instead the thing to check by ear in a real browser, per the plan's own manual
// smoke-test verification step (T1.1's minSilenceDuration change in particular). Similarly, no
// WER/transcription-accuracy check is attempted here for the same vad-asr-in-Node reason.
//
// Usage: node eval-diarization.mjs <path-to-sherpa-onnx-wasm-main-speaker-embedding.js> [path-to-embedding.onnx]
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLIPS_DIR = path.join(__dirname, "eval-clips");

const GLUE_JS = process.argv[2];
const MODEL_PATH = process.argv[3] || "./embedding.onnx";
if (!GLUE_JS) {
  console.error("Usage: node eval-diarization.mjs <glue.js> [embedding.onnx]");
  process.exit(1);
}

// Must match workers/embeddingWorker.ts's MIN_EMBEDDABLE_SECONDS -- duplicated here rather
// than imported since that file assumes a Worker global scope (self/importScripts), not a
// plain importable module. lib/speakerMatch.ts has no such constraint and IS imported for
// real below.
const MIN_EMBEDDABLE_SECONDS = 0.6;
const SAMPLE_RATE = 16000;

function readWavInt16Mono(filePath) {
  const buf = readFileSync(filePath);
  if (buf.toString("ascii", 0, 4) !== "RIFF" || buf.toString("ascii", 8, 12) !== "WAVE") {
    throw new Error(`${filePath} is not a RIFF/WAVE file`);
  }
  let offset = 12;
  let dataOffset = -1;
  let dataSize = 0;
  while (offset + 8 <= buf.length) {
    const chunkId = buf.toString("ascii", offset, offset + 4);
    const chunkSize = buf.readUInt32LE(offset + 4);
    const body = offset + 8;
    if (chunkId === "data") {
      dataOffset = body;
      dataSize = chunkSize;
    }
    offset = body + chunkSize + (chunkSize % 2);
  }
  if (dataOffset < 0) throw new Error(`${filePath}: no data chunk found`);
  const numSamples = dataSize / 2;
  const out = new Float32Array(numSamples);
  for (let i = 0; i < numSamples; i++) out[i] = buf.readInt16LE(dataOffset + i * 2) / 32768;
  return out;
}

async function main() {
  const { createSpeakerRegistry, matchOrRegisterSpeaker } = await import("../../lib/speakerMatch.ts");

  const glueModule = await import(path.resolve(GLUE_JS));
  const createModule = glueModule.default;
  if (typeof createModule !== "function") {
    throw new Error(`import() of ${GLUE_JS} didn't give a factory function -- MODULARIZE isn't wired up as expected`);
  }
  const Module = await createModule();

  function cStr(str) {
    const len = Module.lengthBytesUTF8(str) + 1;
    const ptr = Module._malloc(len);
    Module.stringToUTF8(str, ptr, len);
    return ptr;
  }

  const modelPtr = cStr(MODEL_PATH);
  const providerPtr = cStr("cpu");
  const configPtr = Module._malloc(16);
  Module.setValue(configPtr + 0, modelPtr, "i32");
  Module.setValue(configPtr + 4, 1, "i32");
  Module.setValue(configPtr + 8, 0, "i32");
  Module.setValue(configPtr + 12, providerPtr, "i32");
  const extractor = Module.ccall("SherpaOnnxCreateSpeakerEmbeddingExtractor", "number", ["number"], [configPtr]);
  if (!extractor) throw new Error("SherpaOnnxCreateSpeakerEmbeddingExtractor returned NULL");
  const dim = Module.ccall("SherpaOnnxSpeakerEmbeddingExtractorDim", "number", ["number"], [extractor]);

  // Mirrors workers/embeddingWorker.ts's computeEmbeddingForSegment exactly (including the
  // duration floor), just against a pre-loaded extractor/samples slice instead of a worker
  // message.
  function computeEmbeddingForSegment(samples) {
    if (samples.length < MIN_EMBEDDABLE_SECONDS * SAMPLE_RATE) return null;
    const stream = Module.ccall("SherpaOnnxSpeakerEmbeddingExtractorCreateStream", "number", ["number"], [extractor]);
    const samplesPtr = Module._malloc(samples.length * 4);
    Module.HEAPF32.set(samples, samplesPtr / 4);
    Module.ccall(
      "SherpaOnnxOnlineStreamAcceptWaveform",
      null,
      ["number", "number", "number", "number"],
      [stream, SAMPLE_RATE, samplesPtr, samples.length],
    );
    Module.ccall("SherpaOnnxOnlineStreamInputFinished", null, ["number"], [stream]);
    const isReady = Module.ccall("SherpaOnnxSpeakerEmbeddingExtractorIsReady", "number", ["number", "number"], [extractor, stream]);
    let embedding = null;
    if (isReady) {
      const embPtr = Module.ccall("SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding", "number", ["number", "number"], [extractor, stream]);
      if (embPtr) {
        embedding = new Float32Array(dim);
        for (let i = 0; i < dim; i++) embedding[i] = Module.getValue(embPtr + i * 4, "float");
        Module.ccall("SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding", null, ["number"], [embPtr]);
      }
    }
    Module.ccall("SherpaOnnxDestroyOnlineStream", null, ["number"], [stream]);
    Module._free(samplesPtr);
    return embedding;
  }

  const clipFiles = readdirSync(CLIPS_DIR).filter((f) => f.endsWith(".json"));
  if (clipFiles.length === 0) {
    throw new Error(`No clips found in ${CLIPS_DIR} -- run generate-eval-clips.mjs first.`);
  }

  let totalPairs = 0;
  let correctPairs = 0;

  for (const clipFile of clipFiles) {
    const clipName = clipFile.replace(/\.json$/, "");
    const { turns } = JSON.parse(readFileSync(path.join(CLIPS_DIR, clipFile), "utf8"));
    const allSamples = readWavInt16Mono(path.join(CLIPS_DIR, `${clipName}.wav`));

    // Fresh registry per clip -- mirrors a fresh recording session (page.tsx's handleStart
    // calls createSpeakerRegistry() anew each time).
    const registry = createSpeakerRegistry();
    let lastSpeaker = null;
    const predictions = [];
    const embeddingAttempted = [];

    for (const turn of turns) {
      const segment = allSamples.subarray(turn.startSample, turn.endSample);
      const embedding = computeEmbeddingForSegment(segment);
      embeddingAttempted.push(embedding !== null);
      // Mirrors page.tsx's onFinal exactly (see that file's comment for the rationale).
      const match = embedding ? matchOrRegisterSpeaker(registry, embedding) : null;
      const speaker = match?.confident ? match.label : (lastSpeaker ?? match?.label ?? "Speaker 1");
      lastSpeaker = speaker;
      predictions.push(speaker);
    }

    console.log(`\n--- ${clipName} ---`);
    for (let i = 0; i < turns.length; i++) {
      const dur = (turns[i].endSec - turns[i].startSec).toFixed(2);
      console.log(
        `  turn ${i} [${dur}s] ground truth=${turns[i].speakerId} predicted=${predictions[i]} ` +
          `(embedded=${embeddingAttempted[i]})  "${turns[i].text}"`,
      );
    }

    let clipCorrect = 0;
    let clipTotal = 0;
    for (let i = 0; i < turns.length; i++) {
      for (let j = i + 1; j < turns.length; j++) {
        const groundTruthSame = turns[i].speakerId === turns[j].speakerId;
        const predictedSame = predictions[i] === predictions[j];
        clipTotal++;
        if (groundTruthSame === predictedSame) {
          clipCorrect++;
        } else {
          console.log(
            `  MISMATCH: turns ${i}/${j} -- ground truth ${groundTruthSame ? "same" : "different"} speaker, ` +
              `predicted ${predictedSame ? "same" : "different"}`,
          );
        }
      }
    }
    console.log(`  pairwise accuracy: ${clipCorrect}/${clipTotal}`);
    totalPairs += clipTotal;
    correctPairs += clipCorrect;
  }

  console.log(`\n=== overall pairwise same/different-speaker accuracy: ${correctPairs}/${totalPairs} (${((correctPairs / totalPairs) * 100).toFixed(1)}%) ===`);
  process.exit(correctPairs === totalPairs ? 0 : 2);
}

main().catch((err) => {
  console.error("FATAL:", err);
  process.exit(1);
});
