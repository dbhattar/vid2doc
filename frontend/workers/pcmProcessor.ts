// AudioWorkletProcessor running on the browser's real-time audio-rendering thread. Its
// only job is to buffer the 128-sample render quanta the Web Audio API hands it into
// larger (~4096-sample) chunks of raw Float32 PCM at the AudioContext's native sample
// rate, and forward those chunks up through its MessagePort. No resampling, VAD, or ASR
// happens here -- all of that runs off-thread in the dedicated worker
// (workers/vadAsrWorker.ts) instead, so this processor stays cheap enough to never glitch
// audio capture. See lib/sherpaLiveEngine.ts for how this is wired up to the worker.
//
// TypeScript's bundled "dom" lib doesn't declare the AudioWorkletGlobalScope APIs (they're
// a separate spec from the main-thread DOM lib this project otherwise uses), so the couple
// used here are declared locally rather than pulling in a whole extra lib for one file.
declare class AudioWorkletProcessor {
  readonly port: MessagePort;
  process(
    inputs: Float32Array[][],
    outputs: Float32Array[][],
    parameters: Record<string, Float32Array>,
  ): boolean;
}

declare function registerProcessor(name: string, processorCtor: new () => AudioWorkletProcessor): void;

const CHUNK_SIZE = 4096;

class PcmCaptureProcessor extends AudioWorkletProcessor {
  private chunk = new Float32Array(CHUNK_SIZE);
  private writeIndex = 0;

  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0];
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
