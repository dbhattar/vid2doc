#!/usr/bin/env node
// Generates small, synthetic two-speaker WAV clips (via macOS `say`) + JSON ground-truth
// sidecars, for eval-diarization.mjs to validate lib/speakerMatch.ts's matching/centroid
// logic against real embeddings extracted from real (if synthetic) short audio -- see
// plan/live-diarization-accuracy-plan.md's Tier 3. Requires macOS (`say` ships with the OS);
// only needs to be re-run if the clip definitions below change -- the generated output
// (eval-clips/) is checked in so the eval itself runs anywhere.
//
// Two distinct `say` voices stand in for two distinct speakers -- not real human recordings,
// but real synthesized audio, same spirit as the existing
// frontend/native/sherpa-speaker-embedding/test-audio/ precedent. Deliberately short gaps
// between some turns (as little as 0.2s) specifically stress-test T1.1's lowered
// minSilenceDuration and T1.2's lowered embedding-length floor -- the two mechanisms that
// decide whether a short, fast speaker handoff ever gets a real identity check at all.
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, unlinkSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.join(__dirname, "eval-clips");
const SAMPLE_RATE = 16000;

const VOICES = { A: "Samantha", B: "Fred" };

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
  const out = new Int16Array(numSamples);
  for (let i = 0; i < numSamples; i++) out[i] = buf.readInt16LE(dataOffset + i * 2);
  return out;
}

function writeWavInt16Mono(filePath, samples) {
  const dataSize = samples.length * 2;
  const buf = Buffer.alloc(44 + dataSize);
  buf.write("RIFF", 0, "ascii");
  buf.writeUInt32LE(36 + dataSize, 4);
  buf.write("WAVE", 8, "ascii");
  buf.write("fmt ", 12, "ascii");
  buf.writeUInt32LE(16, 16); // fmt chunk size
  buf.writeUInt16LE(1, 20); // PCM
  buf.writeUInt16LE(1, 22); // mono
  buf.writeUInt32LE(SAMPLE_RATE, 24);
  buf.writeUInt32LE(SAMPLE_RATE * 2, 28); // byte rate
  buf.writeUInt16LE(2, 32); // block align
  buf.writeUInt16LE(16, 34); // bits per sample
  buf.write("data", 36, "ascii");
  buf.writeUInt32LE(dataSize, 40);
  for (let i = 0; i < samples.length; i++) buf.writeInt16LE(samples[i], 44 + i * 2);
  writeFileSync(filePath, buf);
}

function sayUtterance(voice, text) {
  const tmpFile = path.join(OUT_DIR, `_tmp_${process.pid}_${Math.random().toString(36).slice(2)}.wav`);
  execFileSync("say", ["-v", voice, "--data-format=LEI16@16000", "-o", tmpFile, text]);
  const samples = readWavInt16Mono(tmpFile);
  unlinkSync(tmpFile);
  return samples;
}

/** `script` is an array of { speakerId: "A"|"B", text: string, gapAfterSec: number } --
 * gapAfterSec is the silence inserted AFTER this utterance, before the next one (ignored for
 * the last entry). Returns the concatenated samples plus a ground-truth turns[] with exact
 * sample offsets AND derived seconds (both -- samples for exact slicing in the eval script,
 * seconds because that's the sidecar shape the plan calls for). */
function buildClip(script) {
  const chunks = [];
  const turns = [];
  let cursor = 0;
  for (let i = 0; i < script.length; i++) {
    const { speakerId, text, gapAfterSec = 0 } = script[i];
    const samples = sayUtterance(VOICES[speakerId], text);
    chunks.push(samples);
    const startSample = cursor;
    const endSample = cursor + samples.length;
    turns.push({
      speakerId,
      text,
      startSample,
      endSample,
      startSec: startSample / SAMPLE_RATE,
      endSec: endSample / SAMPLE_RATE,
    });
    cursor = endSample;
    if (i < script.length - 1 && gapAfterSec > 0) {
      const gapSamples = Math.round(gapAfterSec * SAMPLE_RATE);
      chunks.push(new Int16Array(gapSamples)); // silence
      cursor += gapSamples;
    }
  }
  const total = new Int16Array(cursor);
  let offset = 0;
  for (const chunk of chunks) {
    total.set(chunk, offset);
    offset += chunk.length;
  }
  return { samples: total, turns };
}

// ---- clip definitions ----------------------------------------------------------------
//
// Gaps are deliberately varied: some comfortably above both the old (0.5s) and new (0.3s)
// minSilenceDuration, some specifically in the 0.2-0.4s band that only the new, lowered
// threshold (T1.1) would ever let VAD split on -- though this harness doesn't run real VAD
// (see eval-diarization.mjs's own header comment for why), it uses these same boundaries
// directly as the "segments" fed to the embedding model, so the gap values themselves don't
// change the eval's outcome -- what matters here is utterance DURATION relative to
// MIN_EMBEDDABLE_SECONDS (0.6s) and how distinct two voices embed at that length.
const CLIPS = {
  "fast-handoff": [
    { speakerId: "A", text: "I think we should launch the feature today.", gapAfterSec: 0.3 },
    { speakerId: "B", text: "Really?", gapAfterSec: 0.25 },
    { speakerId: "A", text: "Yes, I'm confident it's ready.", gapAfterSec: 0.4 },
    { speakerId: "B", text: "Okay, let's do it.", gapAfterSec: 0.2 },
    { speakerId: "A", text: "Great, I'll notify the team.", gapAfterSec: 0 },
  ],
  "self-split": [
    // Ground truth: both halves are the SAME speaker (A), split by a pause short enough that
    // a silence-based VAD could plausibly treat it as two segments -- tests that matching
    // correctly re-identifies them as the same person rather than spawning a new one.
    { speakerId: "A", text: "The quarterly results were strong,", gapAfterSec: 0.25 },
    { speakerId: "A", text: "and the board was very pleased.", gapAfterSec: 0 },
  ],
  interjection: [
    // "Sounds good." (~0.94s synthesized) is deliberately chosen to land ABOVE the new
    // MIN_EMBEDDABLE_SECONDS floor (0.6s) but BELOW the old one (1.2s) -- this is exactly the
    // case T1.2 is meant to fix: previously this interjection would never even attempt an
    // embedding and would always inherit Speaker A's label by fallback (wrong); now it should
    // get a real identity check.
    { speakerId: "A", text: "So the plan is to migrate the database next week,", gapAfterSec: 0.3 },
    { speakerId: "B", text: "Sounds good.", gapAfterSec: 0.3 },
    { speakerId: "A", text: "and then update the API clients after that.", gapAfterSec: 0 },
  ],
};

mkdirSync(OUT_DIR, { recursive: true });
for (const [name, script] of Object.entries(CLIPS)) {
  const { samples, turns } = buildClip(script);
  writeWavInt16Mono(path.join(OUT_DIR, `${name}.wav`), samples);
  writeFileSync(
    path.join(OUT_DIR, `${name}.json`),
    JSON.stringify({ sampleRate: SAMPLE_RATE, turns }, null, 2),
  );
  console.log(`Wrote eval-clips/${name}.wav + .json (${turns.length} turns, ${(samples.length / SAMPLE_RATE).toFixed(2)}s)`);
}
