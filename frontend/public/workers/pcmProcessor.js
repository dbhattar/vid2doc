"use strict";
const CHUNK_SIZE = 4096;
class PcmCaptureProcessor extends AudioWorkletProcessor {
    constructor() {
        super(...arguments);
        this.chunk = new Float32Array(CHUNK_SIZE);
        this.writeIndex = 0;
    }
    process(inputs) {
        var _a;
        const channel = (_a = inputs[0]) === null || _a === void 0 ? void 0 : _a[0];
        if (!channel || channel.length === 0) {
            // No mic data this quantum (e.g. track briefly muted) -- keep the node alive.
            return true;
        }
        for (let i = 0; i < channel.length; i++) {
            this.chunk[this.writeIndex++] = channel[i];
            if (this.writeIndex === CHUNK_SIZE) {
                this.port.postMessage(this.chunk, [this.chunk.buffer]);
                this.chunk = new Float32Array(CHUNK_SIZE);
                this.writeIndex = 0;
            }
        }
        return true;
    }
}
registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
