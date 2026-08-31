// v2: this build is compiled with -sMODULARIZE=1 -sEXPORT_NAME=createSherpaOnnxSpeakerEmbeddingModule,
// so require() returns a proper factory function.
"use strict";
const fs = require("fs");
const path = require("path");

const GLUE_JS = process.argv[2];
const MODEL_PATH = process.argv[3] || "./embedding.onnx";
const AUDIO_DIR = process.argv[4];

function readWavMonoFloat32(filePath) {
  const buf = fs.readFileSync(filePath);
  if (buf.toString("ascii", 0, 4) !== "RIFF" || buf.toString("ascii", 8, 12) !== "WAVE") {
    throw new Error(`${filePath} is not a RIFF/WAVE file`);
  }
  let offset = 12, sampleRate = 0, bitsPerSample = 0, numChannels = 0, dataOffset = -1, dataSize = 0;
  while (offset + 8 <= buf.length) {
    const chunkId = buf.toString("ascii", offset, offset + 4);
    const chunkSize = buf.readUInt32LE(offset + 4);
    const body = offset + 8;
    if (chunkId === "fmt ") {
      numChannels = buf.readUInt16LE(body + 2);
      sampleRate = buf.readUInt32LE(body + 4);
      bitsPerSample = buf.readUInt16LE(body + 14);
    } else if (chunkId === "data") {
      dataOffset = body;
      dataSize = chunkSize;
    }
    offset = body + chunkSize + (chunkSize % 2);
  }
  if (dataOffset < 0) throw new Error(`${filePath}: no data chunk found`);
  if (bitsPerSample !== 16) throw new Error(`${filePath}: expected 16-bit PCM, got ${bitsPerSample}`);
  if (numChannels !== 1) throw new Error(`${filePath}: expected mono, got ${numChannels} channels`);
  const numSamples = dataSize / 2;
  const out = new Float32Array(numSamples);
  for (let i = 0; i < numSamples; i++) out[i] = buf.readInt16LE(dataOffset + i * 2) / 32768.0;
  return { sampleRate, samples: out };
}

function cosineSimilarity(a, b) {
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

async function main() {
  const createModule = require(path.resolve(GLUE_JS));
  if (typeof createModule !== "function") {
    throw new Error(`require() returned a ${typeof createModule}, not a factory function -- MODULARIZE isn't wired up as expected`);
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
  console.log("Embedding dim:", dim);

  function computeEmbedding(wavPath) {
    const { sampleRate, samples } = readWavMonoFloat32(wavPath);
    const stream = Module.ccall("SherpaOnnxSpeakerEmbeddingExtractorCreateStream", "number", ["number"], [extractor]);
    const samplesPtr = Module._malloc(samples.length * 4);
    Module.HEAPF32.set(samples, samplesPtr / 4);
    Module.ccall("SherpaOnnxOnlineStreamAcceptWaveform", null, ["number", "number", "number", "number"], [stream, sampleRate, samplesPtr, samples.length]);
    Module.ccall("SherpaOnnxOnlineStreamInputFinished", null, ["number"], [stream]);
    const isReady = Module.ccall("SherpaOnnxSpeakerEmbeddingExtractorIsReady", "number", ["number", "number"], [extractor, stream]);
    if (!isReady) throw new Error(`${wavPath}: extractor stream not ready after feeding full clip`);
    const embPtr = Module.ccall("SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding", "number", ["number", "number"], [extractor, stream]);
    if (!embPtr) throw new Error(`${wavPath}: ComputeEmbedding returned NULL`);
    const emb = new Float32Array(dim);
    for (let i = 0; i < dim; i++) emb[i] = Module.getValue(embPtr + i * 4, "float");
    Module.ccall("SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding", null, ["number"], [embPtr]);
    Module.ccall("SherpaOnnxDestroyOnlineStream", null, ["number"], [stream]);
    Module._free(samplesPtr);
    return emb;
  }

  const files = {
    alice1: path.join(AUDIO_DIR, "alice1.wav"),
    alice2: path.join(AUDIO_DIR, "alice2.wav"),
    bob1: path.join(AUDIO_DIR, "bob1.wav"),
    bob2: path.join(AUDIO_DIR, "bob2.wav"),
  };
  const embeddings = {};
  for (const [name, filePath] of Object.entries(files)) {
    embeddings[name] = computeEmbedding(filePath);
  }

  const sameA = cosineSimilarity(embeddings.alice1, embeddings.alice2);
  const sameB = cosineSimilarity(embeddings.bob1, embeddings.bob2);
  const diffs = [
    cosineSimilarity(embeddings.alice1, embeddings.bob1),
    cosineSimilarity(embeddings.alice1, embeddings.bob2),
    cosineSimilarity(embeddings.alice2, embeddings.bob1),
    cosineSimilarity(embeddings.alice2, embeddings.bob2),
  ];
  const avgDiff = diffs.reduce((a, b) => a + b, 0) / diffs.length;

  console.log("same-speaker  alice1 vs alice2:", sameA.toFixed(4));
  console.log("same-speaker  bob1   vs bob2  :", sameB.toFixed(4));
  console.log("avg diff-speaker similarity   :", avgDiff.toFixed(4));

  const ok = sameA > avgDiff && sameB > avgDiff;
  console.log("DISCRIMINATES SPEAKERS (MODULARIZE build):", ok ? "YES" : "NO");
  process.exit(ok ? 0 : 2);
}

main().catch((err) => {
  console.error("FATAL:", err);
  process.exit(1);
});
