"use strict";
const ctx = self;
function post(message) {
    ctx.postMessage(message);
}
function fail(message) {
    post({ type: "error", message });
}
// ---- constants ----------------------------------------------------------------------
const WASM_BASE = "/wasm/vad-asr/";
const SAMPLE_RATE = 16000;
// Re-decode the in-progress utterance for a `partial` preview at most this often.
const PARTIAL_INTERVAL_SAMPLES = Math.round(SAMPLE_RATE * 0.6);
// Don't bother decoding a partial until there's at least this much speech buffered.
const PARTIAL_MIN_SAMPLES = Math.round(SAMPLE_RATE * 0.3);
// ---- module state ---------------------------------------------------------------------
let vad = null;
let circularBuffer = null;
let recognizer = null;
let ready = false;
// Raw (already 16kHz) samples of the utterance currently in progress, kept purely for the
// `partial` preview -- cleared whenever VAD is no longer in the "detected" state. This is
// separate from the VAD's own internal buffering; the VAD's `front()`/`pop()` segment
// remains the sole source of truth for the eventual `final` message.
let utteranceChunks = [];
let utteranceSampleCount = 0;
let samplesSinceLastPartial = 0;
let wasDetected = false;
// Leftover fractional-sample state for the linear-downsample carried over between chunks
// (mirrors the upstream demo's downsampleBuffer, just streaming instead of one-shot).
let resampleCarry = null;
function concatFloat32(chunks) {
    const total = chunks.reduce((sum, c) => sum + c.length, 0);
    const out = new Float32Array(total);
    let offset = 0;
    for (const c of chunks) {
        out.set(c, offset);
        offset += c.length;
    }
    return out;
}
// Ported from sherpa-onnx's own wasm/vad-asr/app-vad-asr.js `downsampleBuffer` -- linear
// averaging down to 16kHz. Streaming-safe: `resampleCarry` tracks the fractional read
// offset across calls so chunk boundaries don't introduce clicks/drift.
function downsampleTo16k(input, inputSampleRate) {
    if (inputSampleRate === SAMPLE_RATE) {
        return input;
    }
    const ratio = inputSampleRate / SAMPLE_RATE;
    if (!resampleCarry || resampleCarry.ratio !== ratio) {
        resampleCarry = { ratio, offset: 0 };
    }
    const carry = resampleCarry;
    const outLength = Math.floor((input.length - carry.offset) / ratio);
    if (outLength <= 0) {
        carry.offset -= input.length;
        return new Float32Array(0);
    }
    const out = new Float32Array(outLength);
    for (let i = 0; i < outLength; i++) {
        const start = carry.offset + i * ratio;
        const end = carry.offset + (i + 1) * ratio;
        const from = Math.max(0, Math.round(start));
        const to = Math.min(input.length, Math.round(end));
        let sum = 0;
        let count = 0;
        for (let j = from; j < to; j++) {
            sum += input[j];
            count++;
        }
        out[i] = count > 0 ? sum / count : input[Math.min(from, input.length - 1)];
    }
    carry.offset = carry.offset + outLength * ratio - input.length;
    return out;
}
function decodeSamples(samples) {
    if (!recognizer)
        return "";
    const stream = recognizer.createStream();
    try {
        stream.acceptWaveform(SAMPLE_RATE, samples);
        recognizer.decode(stream);
        const result = recognizer.getResult(stream);
        return (result.text || "").trim();
    }
    finally {
        stream.free();
    }
}
function emitPartialIfDue() {
    if (utteranceSampleCount < PARTIAL_MIN_SAMPLES)
        return;
    if (samplesSinceLastPartial < PARTIAL_INTERVAL_SAMPLES)
        return;
    samplesSinceLastPartial = 0;
    const text = decodeSamples(concatFloat32(utteranceChunks));
    if (text) {
        post({ type: "partial", text });
    }
}
function drainFinishedSegments() {
    if (!vad)
        return;
    while (!vad.isEmpty()) {
        const segment = vad.front();
        vad.pop();
        const text = decodeSamples(segment.samples);
        if (text) {
            const startTs = segment.start / SAMPLE_RATE;
            const endTs = startTs + segment.samples.length / SAMPLE_RATE;
            post({ type: "final", text, startTs, endTs });
        }
    }
}
function processSamples(samples16k) {
    if (!vad || !circularBuffer)
        return;
    circularBuffer.push(samples16k);
    const windowSize = vad.config.sileroVad.windowSize;
    while (circularBuffer.size() > windowSize) {
        const window = circularBuffer.get(circularBuffer.head(), windowSize);
        circularBuffer.pop(windowSize);
        vad.acceptWaveform(window);
        const detected = vad.isDetected();
        if (detected) {
            utteranceChunks.push(window);
            utteranceSampleCount += window.length;
            samplesSinceLastPartial += window.length;
            emitPartialIfDue();
        }
        else if (wasDetected) {
            // Speech just ended (or never crossed the min-speech-duration threshold) --
            // whatever segment(s) VAD finalized are drained below; reset the partial-preview
            // accumulator regardless so a false-start doesn't linger into the next utterance.
            utteranceChunks = [];
            utteranceSampleCount = 0;
            samplesSinceLastPartial = 0;
        }
        wasDetected = detected;
        drainFinishedSegments();
    }
}
// The vendored glue script (sherpa-onnx-wasm-main-vad-asr.js) does
// `var Module = typeof Module !== "undefined" ? Module : {}` and expects a pre-existing
// `Module` object with `locateFile`/`onRuntimeInitialized` already set, exactly like the
// upstream demo's `Module = {}` before its own <script> tag. Since this is a plain
// assignment (not `var`/`let`), it's done via `globalThis` to stay valid under the strict
// mode ES modules always run in.
function applyModuleConfig() {
    const moduleConfig = {
        locateFile: (path) => WASM_BASE + path,
        onRuntimeInitialized: () => {
            try {
                vad = createVad(Module);
                circularBuffer = new CircularBuffer(30 * SAMPLE_RATE, Module);
                recognizer = new OfflineRecognizer({
                    modelConfig: {
                        debug: 0,
                        tokens: "./tokens.txt",
                        moonshine: {
                            encoder: "./moonshine-encoder.ort",
                            mergedDecoder: "./moonshine-merged-decoder.ort",
                        },
                    },
                }, Module);
                ready = true;
                post({ type: "ready" });
            }
            catch (err) {
                fail(`Failed to initialize sherpa-onnx recognizer: ${String(err)}`);
            }
        },
        onAbort: (reason) => {
            fail(`sherpa-onnx WASM module aborted: ${String(reason)}`);
        },
    };
    globalThis.Module = moduleConfig;
}
function loadWasmModule() {
    try {
        applyModuleConfig();
        // Order matters: the wrapper classes (createVad/OfflineRecognizer/CircularBuffer) have
        // no dependency on the WASM runtime being initialized yet, but the main glue script
        // reads the `Module` global set up above as soon as it starts executing.
        importScripts(WASM_BASE + "sherpa-onnx-vad.js", WASM_BASE + "sherpa-onnx-asr.js", WASM_BASE + "sherpa-onnx-wasm-main-vad-asr.js");
    }
    catch (err) {
        fail(`Failed to load sherpa-onnx vad-asr WASM build: ${String(err)}`);
    }
}
ctx.onmessage = (ev) => {
    const msg = ev.data;
    if (!ready) {
        // Ignore audio that arrives before init finishes (shouldn't happen since
        // lib/sherpaLiveEngine.ts awaits `ready` before starting capture) rather than crash.
        if (msg.type === "flush")
            post({ type: "flushed" });
        return;
    }
    if (msg.type === "pcm") {
        const samples16k = downsampleTo16k(msg.samples, msg.sampleRate);
        if (samples16k.length > 0) {
            processSamples(samples16k);
        }
        return;
    }
    if (msg.type === "flush") {
        vad === null || vad === void 0 ? void 0 : vad.flush();
        drainFinishedSegments();
        utteranceChunks = [];
        utteranceSampleCount = 0;
        samplesSinceLastPartial = 0;
        post({ type: "flushed" });
    }
};
loadWasmModule();
