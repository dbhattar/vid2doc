// On-device text-to-speech for the agent chat, backed by Gradium's Phonon
// (phonon-31m-en, ~65MB) running as WebAssembly in a worker via the
// `phonon-tts` package. Nothing is sent to a server: the model and voices are
// downloaded once from Hugging Face, kept in the browser's Cache API, and
// every later load -- including offline -- reads them from there. Needs a
// secure context (https or localhost) to cache, and WebAssembly SIMD.
//
// One module-level singleton, like lib/sherpaLiveEngine.ts's worker pool: the
// model is loaded once per page visit and reused for every message. The
// whole package -- index.js, worker and .wasm files -- is served as static
// files from /phonon/ (copied out of node_modules by `npm run copy:phonon`, see
// package.json) and loaded with a runtime import, so it never ships to pages
// that don't speak. Deliberately NOT bundled: as of Next.js 16.2.10, letting
// Turbopack bundle `phonon-tts` (a worker + wasm via `new URL(..., import.meta.url)`)
// hangs `next build` indefinitely -- same family of problem as the worker note
// on lib/sherpaLiveEngine.ts's WORKER_URL. Types only come from the package.
import type { PhononTTS as PhononTTSClass } from "phonon-tts";

import { PHONON_VOICES, voiceUrl } from "@/lib/phononVoices";

export type SpeechStatus = "idle" | "loading" | "ready" | "speaking" | "error";

const PHONON_MODULE_URL = "/phonon/index.js";

type Listener = () => void;

let tts: PhononTTSClass | null = null;
let loading: Promise<PhononTTSClass> | null = null;
let status: SpeechStatus = "idle";
let loadPercent: number | null = null;
let errorMessage: string | null = null;
let speakingId: string | null = null;
let current: { cancel: () => void } | null = null;
const loadedVoices = new Set<string>();
const listeners = new Set<Listener>();

function setState(patch: { status?: SpeechStatus; loadPercent?: number | null; error?: string | null; speakingId?: string | null }) {
  if (patch.status !== undefined) status = patch.status;
  if (patch.loadPercent !== undefined) loadPercent = patch.loadPercent;
  if (patch.error !== undefined) errorMessage = patch.error;
  if (patch.speakingId !== undefined) speakingId = patch.speakingId;
  snapshot = { status, loadPercent, error: errorMessage, speakingId };
  listeners.forEach((l) => l());
}

export type SpeechSnapshot = {
  status: SpeechStatus;
  loadPercent: number | null;
  error: string | null;
  /** Id passed to speak() for the message currently being read, if any. */
  speakingId: string | null;
};

// Cached object so useSyncExternalStore sees a stable reference between changes.
let snapshot: SpeechSnapshot = { status, loadPercent, error: errorMessage, speakingId };

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getSnapshot(): SpeechSnapshot {
  return snapshot;
}

export const SERVER_SNAPSHOT: SpeechSnapshot = { status: "idle", loadPercent: null, error: null, speakingId: null };

/** Downloads (first time) or loads from cache (afterwards) the model. Safe to
 * call repeatedly -- concurrent callers share one load. */
export function loadSpeech(): Promise<PhononTTSClass> {
  if (tts) return Promise.resolve(tts);
  if (loading) return loading;
  setState({ status: "loading", loadPercent: 0, error: null });
  loading = (async () => {
    try {
      const { PhononTTS } = (await import(
        /* turbopackIgnore: true */ /* webpackIgnore: true */ PHONON_MODULE_URL
      )) as typeof import("phonon-tts");
      // Per-file progress, folded into one overall figure.
      const files = new Map<string, number>();
      const instance = await PhononTTS.load({
        lang: "en",
        workerUrl: "/phonon/worker.js",
        wasmUrl: "/phonon/wasm/phonon_tts_bg.wasm",
        simdWasmUrl: "/phonon/wasm/phonon_tts_simd_bg.wasm",
        threadsWasmUrl: "/phonon/wasm-threads/phonon_tts_bg.wasm",
        threadsSimdWasmUrl: "/phonon/wasm-threads/phonon_tts_simd_bg.wasm",
        onProgress: ({ file, loaded, total }) => {
          if (!total) return;
          files.set(file, loaded / total);
          const avg = [...files.values()].reduce((a, b) => a + b, 0) / files.size;
          setState({ loadPercent: Math.round(avg * 100) });
        },
      });
      tts = instance;
      setState({ status: "ready", loadPercent: null });
      return instance;
    } catch (err) {
      loading = null;
      setState({ status: "error", loadPercent: null, error: err instanceof Error ? err.message : String(err) });
      throw err;
    }
  })();
  return loading;
}

/** Stops whatever is being read aloud. */
export function stopSpeaking(): void {
  current?.cancel();
  current = null;
  if (status === "speaking") setState({ status: "ready", speakingId: null });
}

/** Reads `text` aloud with the given voice (a PHONON_VOICES id; undefined =
 * the model's built-in default). Replaces anything already being read. `id`
 * identifies the message, so the UI can show which one is playing. Resolves
 * when playback ends or is stopped. */
export async function speak(id: string, text: string, voiceId?: string): Promise<void> {
  stopSpeaking();
  const model = await loadSpeech();

  // A newer speak()/stop() call during the awaits below flips this.
  let cancelled = false;
  let stream: ReturnType<PhononTTSClass["stream"]> | null = null;
  const audio = new AudioContext({ sampleRate: model.sampleRate });
  const handle = {
    cancel: () => {
      cancelled = true;
      stream?.cancel();
      void audio.close().catch(() => {});
    },
  };
  current = handle;
  setState({ status: "speaking", speakingId: id });

  try {
    let voiceName: string | undefined;
    const voice = PHONON_VOICES.find((v) => v.id === voiceId);
    if (voice) {
      // Fetched on first use (~250KB) and cached; the default voice ships with the model.
      if (!loadedVoices.has(voice.id)) {
        await model.addVoice(voice.id, voiceUrl(voice));
        loadedVoices.add(voice.id);
      }
      voiceName = voice.id;
    }
    if (cancelled) return;

    stream = model.stream(text, { voice: voiceName });
    // Chunks are scheduled back to back on a running cursor so playback
    // starts after the first 80ms chunk instead of after the whole reply.
    let cursor = audio.currentTime;
    let lastEnd = Promise.resolve();
    for await (const chunk of stream) {
      if (cancelled) break;
      const buffer = audio.createBuffer(1, chunk.length, model.sampleRate);
      buffer.copyToChannel(chunk as Float32Array<ArrayBuffer>, 0);
      const source = audio.createBufferSource();
      source.buffer = buffer;
      source.connect(audio.destination);
      cursor = Math.max(cursor, audio.currentTime);
      source.start(cursor);
      cursor += buffer.duration;
      lastEnd = new Promise((resolve) => (source.onended = () => resolve()));
    }
    if (!cancelled) await lastEnd;
  } catch (err) {
    if (!cancelled) setState({ error: err instanceof Error ? err.message : String(err) });
  } finally {
    if (current === handle) {
      current = null;
      void audio.close().catch(() => {});
      setState({ status: tts ? "ready" : status, speakingId: null });
    }
  }
}

/** Markdown (what agents reply with) to something worth reading aloud: no
 * symbols, urls, or code. Phonon normalizes numbers/dates itself. */
export function markdownToSpeech(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " (code omitted) ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/^\s*\|?[\s:|-]{3,}\|?\s*$/gm, "")
    .replace(/\|/g, ", ")
    .replace(/[*_~]{1,3}([^*_~]+)[*_~]{1,3}/g, "$1")
    .replace(/\n{2,}/g, ". ")
    .replace(/\s+/g, " ")
    .trim();
}
