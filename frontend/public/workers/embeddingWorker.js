"use strict";
const embeddingCtx = self;
// v1: see vadAsrWorker.ts's WASM_BASE comment -- same versioned-path/cache-busting rationale.
const EMBEDDING_WASM_BASE = "/wasm/v1/speaker-embedding/";
// Virtual-FS path the model was preloaded at when the WASM build was compiled
// (--preload-file assets@., with assets/embedding.onnx inside) -- not a real path on disk
// here, see frontend/native/sherpa-speaker-embedding/README.md.
const EMBEDDING_MODEL_PATH = "./embedding.onnx";
// Below this, there's genuinely not enough audio for ERes2Net's frame-pooling window to
// extract anything meaningful -- a hard model-capability floor, not a trust judgment (that
// decision now lives in speakerMatch.ts's confidence-margin matching, which can reject a
// short-but-above-this-floor embedding as unconfident rather than this file guessing by
// duration alone). Previously 1.2s and named MIN_RELIABLE_EMBEDDING_SECONDS, gating "trust"
// directly by duration -- lowered + renamed because that single hard cutoff meant genuinely
// short speaker turns (a quick interjection, a fast back-and-forth) could NEVER get a real
// identity check at all, always falling back to "assume same as previous speaker" regardless
// of how distinct the voices actually were. VAD's own minSpeechDuration (0.25s) lets shorter
// segments through than even this floor; those still skip embedding entirely. See
// plan/live-diarization-accuracy-plan.md.
const MIN_EMBEDDABLE_SECONDS = 0.6;
const EMBEDDING_SAMPLE_RATE = 16000;
let embeddingModule = null;
let embeddingExtractor = 0;
let embeddingDim = 0;
let embeddingReady = false;
function cStr(mod, str) {
    const len = mod.lengthBytesUTF8(str) + 1;
    const ptr = mod._malloc(len);
    mod.stringToUTF8(str, ptr, len);
    return ptr;
}
// Loads the WASM build and creates one extractor for the whole worker lifetime (a fresh
// *stream* per turn, further below, is what actually holds a turn's samples). Never throws:
// any failure here just leaves embeddingReady false, logged for debugging -- every `embed`
// request then simply gets back `embedding: null`, matching the degrade-to-one-speaker
// rationale on the module state above.
async function loadEmbeddingModule() {
    try {
        importScripts(EMBEDDING_WASM_BASE + "sherpa-onnx-wasm-main-speaker-embedding.js");
        const mod = await createSherpaOnnxSpeakerEmbeddingModule({
            locateFile: (path) => EMBEDDING_WASM_BASE + path,
        });
        // SherpaOnnxSpeakerEmbeddingExtractorConfig: { const char *model; int32 num_threads;
        // int32 debug; const char *provider; } -- 4 fields x 4 bytes, matches test-embedding.js.
        const modelPtr = cStr(mod, EMBEDDING_MODEL_PATH);
        const providerPtr = cStr(mod, "cpu");
        const configPtr = mod._malloc(16);
        mod.setValue(configPtr + 0, modelPtr, "i32");
        mod.setValue(configPtr + 4, 1, "i32");
        mod.setValue(configPtr + 8, 0, "i32");
        mod.setValue(configPtr + 12, providerPtr, "i32");
        const extractor = mod.ccall("SherpaOnnxCreateSpeakerEmbeddingExtractor", "number", ["number"], [configPtr]);
        mod._free(modelPtr);
        mod._free(providerPtr);
        mod._free(configPtr);
        if (!extractor) {
            throw new Error("SherpaOnnxCreateSpeakerEmbeddingExtractor returned NULL");
        }
        embeddingModule = mod;
        embeddingExtractor = extractor;
        embeddingDim = mod.ccall("SherpaOnnxSpeakerEmbeddingExtractorDim", "number", ["number"], [extractor]);
        embeddingReady = true;
    }
    catch (err) {
        console.error("Speaker-embedding WASM module failed to load -- diarization will degrade to a single speaker:", err);
    }
}
// Best-effort speaker embedding for one already-VAD-finalized turn's samples (16kHz,
// matching EMBEDDING_SAMPLE_RATE) -- returns null (never throws) on any failure. A fresh
// stream per call mirrors test-embedding.js's proven usage; the extractor itself is reused
// for the worker's whole lifetime.
function computeEmbeddingForSegment(samples) {
    if (!embeddingReady || !embeddingModule || !embeddingExtractor)
        return null;
    if (samples.length < MIN_EMBEDDABLE_SECONDS * EMBEDDING_SAMPLE_RATE)
        return null;
    const mod = embeddingModule;
    let stream = 0;
    let samplesPtr = 0;
    try {
        stream = mod.ccall("SherpaOnnxSpeakerEmbeddingExtractorCreateStream", "number", ["number"], [embeddingExtractor]);
        samplesPtr = mod._malloc(samples.length * 4);
        mod.HEAPF32.set(samples, samplesPtr / 4);
        mod.ccall("SherpaOnnxOnlineStreamAcceptWaveform", null, ["number", "number", "number", "number"], [stream, EMBEDDING_SAMPLE_RATE, samplesPtr, samples.length]);
        mod.ccall("SherpaOnnxOnlineStreamInputFinished", null, ["number"], [stream]);
        const isReady = mod.ccall("SherpaOnnxSpeakerEmbeddingExtractorIsReady", "number", ["number", "number"], [embeddingExtractor, stream]);
        if (!isReady)
            return null;
        const embPtr = mod.ccall("SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding", "number", ["number", "number"], [embeddingExtractor, stream]);
        if (!embPtr)
            return null;
        const embedding = new Float32Array(embeddingDim);
        for (let i = 0; i < embeddingDim; i++) {
            embedding[i] = mod.getValue(embPtr + i * 4, "float");
        }
        mod.ccall("SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding", null, ["number"], [embPtr]);
        return embedding;
    }
    catch (err) {
        console.error("Speaker-embedding extraction failed for this turn, skipping:", err);
        return null;
    }
    finally {
        if (stream)
            mod.ccall("SherpaOnnxDestroyOnlineStream", null, ["number"], [stream]);
        if (samplesPtr)
            mod._free(samplesPtr);
    }
}
embeddingCtx.onmessage = (ev) => {
    const msg = ev.data;
    if (msg.type === "embed") {
        const embedding = computeEmbeddingForSegment(msg.samples);
        const transfer = embedding ? [embedding.buffer] : [];
        embeddingCtx.postMessage({ type: "embedding", turnId: msg.turnId, embedding }, transfer);
    }
};
loadEmbeddingModule();
