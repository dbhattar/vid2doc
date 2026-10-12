"use client";

import { useRouter } from "next/navigation";
import { memo, useCallback, useEffect, useRef, useState } from "react";

import Button from "@/components/Button";
import { GlobeIcon, MicrophoneIcon, PauseIcon, PlayIcon, StopIcon } from "@/components/icons";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { formatTimestamp } from "@/lib/jobs";
import type { LiveEngineHandle, LiveTurn } from "@/lib/liveEngine";
import { createLiveEngine, preloadLiveEngine, subscribeToLoadProgress } from "@/lib/liveEngineProvider";
import { createSpeakerRegistry, matchOrRegisterSpeaker, type SpeakerRegistry } from "@/lib/speakerMatch";
import { speakerColorFor, speakerInitials } from "@/lib/speakerColors";
import { useElapsedSeconds } from "@/lib/useElapsedSeconds";

type Status = "idle" | "starting" | "recording" | "paused" | "finalizing";

type FinalizedTurn = { speaker: string; text: string; start_ts: number; end_ts: number };

type ResearchLink = { title: string; url: string };
type ResearchNote = { topic: string; body: string; links: ResearchLink[] };

// The same source URL often comes back across multiple notes in one session
// (e.g. a topic's own overview page cited again for a related follow-up) --
// shown/saved as one shared "References" list instead of repeating it under
// every note. Dedupes by URL, keeping the first title seen for it.
function dedupeReferences(notes: ResearchNote[]): ResearchLink[] {
  const seen = new Map<string, ResearchLink>();
  for (const note of notes) {
    for (const link of note.links) {
      if (!link.url || seen.has(link.url)) continue;
      seen.set(link.url, link);
    }
  }
  return [...seen.values()];
}

// Cadence for the opt-in live-research panel (see POST /api/live/research,
// backend/app/live_research.py) -- a plain interval, not a generic debounce
// utility (none exists in this codebase, and this is the only call site).
// 30s keeps the panel feeling "live" without hammering the backend/OpenAI on
// every short pause; MIN_CHARS_TO_TRIGGER skips a call if too little new
// speech has accumulated since the last one (e.g. a few acknowledgements),
// so most ticks with nothing substantive to say just no-op locally instead
// of spending a real OpenAI call to get back `note: null`.
const RESEARCH_INTERVAL_MS = 30_000;
const MIN_CHARS_TO_TRIGGER = 120;
// Capped client-side too (the backend independently caps what it accepts --
// see routes/live.py's MAX_COVERED_TOPICS) so the prompt sent each call
// doesn't grow unbounded over a long session.
const MAX_COVERED_TOPICS = 15;

// Fallback for the very first turn of a session, if even that one has no usable embedding
// (engine still loading it, browser can't support it, or the turn was too short for the
// embedding worker to attempt extraction at all -- see workers/embeddingWorker.ts's
// MIN_EMBEDDABLE_SECONDS). Every later turn without a usable (or confidently matched --
// see lib/speakerMatch.ts's SpeakerMatch.confident) embedding instead reuses the previous
// turn's speaker (see lastSpeakerRef below) -- a short or ambiguous segment is far more
// likely to be a continuation of whoever was just speaking than a brand-new person, so
// that's a safer default than resetting to this label mid-conversation. See
// plan/realtime-diarization-plan.md's degradation path and
// plan/live-diarization-accuracy-plan.md for the confidence-margin matching itself.
const UNKNOWN_SPEAKER_LABEL = "Speaker 1";

// Split out of LivePage and memoized so that `partialText` updates (every ~1s while
// recording, see workers/vadAsrWorker.ts's PARTIAL_INTERVAL_SAMPLES) only re-render the one
// in-progress preview line below, not this whole finalized-transcript history -- without
// this, every partial update re-mapped and re-rendered every past turn too, since both lived
// in the same component's render scope. Only re-renders when `turns` itself changes.
const LiveTranscriptTurns = memo(function LiveTranscriptTurns({ turns }: { turns: FinalizedTurn[] }) {
  const speakers = [...new Set(turns.map((t) => t.speaker))];
  return (
    <>
      {turns.map((turn, i) => {
        const speakerIndex = speakers.indexOf(turn.speaker);
        return (
          <div key={i} className="flex gap-3">
            <span
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${speakerColorFor(speakerIndex).avatar}`}
            >
              {speakerInitials(turn.speaker)}
            </span>
            <div>
              <p className="text-xs font-medium text-ink-soft">
                {turn.speaker} &middot; {formatTimestamp(turn.start_ts)}
              </p>
              <p className="text-sm text-ink">{turn.text}</p>
            </div>
          </div>
        );
      })}
    </>
  );
});

export default function LivePage() {
  const router = useRouter();
  const [status, setStatus] = useState<Status>("idle");
  const [saveAudio, setSaveAudio] = useState(false);
  const [turns, setTurns] = useState<FinalizedTurn[]>([]);
  const [partialText, setPartialText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [recordingStartedAt, setRecordingStartedAt] = useState<string | null>(null);
  const [loadProgress, setLoadProgress] = useState<{ loaded: number; total: number } | null>(null);
  const [engineReady, setEngineReady] = useState(false);
  const [liveResearchEnabled, setLiveResearchEnabled] = useState(false);
  const [researchNotes, setResearchNotes] = useState<ResearchNote[]>([]);

  // sherpa-onnx's vad-asr WASM build is a pthreads (multi-threaded) Emscripten build -- its
  // internal worker-pool bootstrap unconditionally transfers a SharedArrayBuffer between
  // workers at load time, which the browser only allows from a cross-origin-isolated page
  // (self.crossOriginIsolated === true, gated on this route's COOP/COEP response headers --
  // see next.config.ts). That isolation state is fixed at the top-level document's own
  // navigation and never changes afterward: reaching this page via client-side routing
  // (e.g. Sidebar's plain <Link href="/dashboard/live">, as opposed to a full page
  // load/reload) means the browser never actually re-requested this route's document, so it
  // keeps whichever (non-isolated) state the PREVIOUS page had -- the headers exist but were
  // never fetched. A single full reload forces a genuine navigation that does fetch them,
  // self-healing before the engine ever tries to load. Guarded by sessionStorage so a
  // browser that can never become cross-origin isolated (shouldn't happen in any supported
  // browser, but a backstop regardless) doesn't reload forever -- createLiveEngine's own
  // error handling takes over from there if isolation still isn't active after one try.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const key = "live-cross-origin-isolation-reload";
    if (window.crossOriginIsolated) {
      // Only ever meant to suppress a repeat reload while isolation is still broken --
      // clear it once fixed so a later soft-nav into this page within the same tab session
      // (if isolation somehow regresses again) still gets exactly one more retry rather than
      // being silently blocked by a flag from an earlier, already-resolved visit.
      sessionStorage.removeItem(key);
      return;
    }
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, "1");
    window.location.reload();
  }, []);

  // Starts the engine's one-time ~95MB WASM/model download as soon as this page mounts,
  // instead of only once the user clicks Record -- avoids the "Starting..." wait (and the UI
  // flicker that comes with it) happening only after they've already committed to recording.
  // Guarded on crossOriginIsolated for the same reason as the effect above: if isolation
  // isn't active yet, that effect's reload is already in flight (this mount is about to be
  // discarded) or will never fix it (unsupported browser) -- either way, preloading from a
  // non-isolated page would just fail the way it always has, so there's nothing useful to
  // start yet. createLiveEngine() still works fine even if this never ran (it calls the same
  // underlying preload itself) -- this is purely a head start, not a dependency.
  useEffect(() => {
    if (typeof window === "undefined" || !window.crossOriginIsolated) return;
    const unsubscribe = subscribeToLoadProgress((loaded, total) => setLoadProgress({ loaded, total }));
    preloadLiveEngine()
      .then(() => setEngineReady(true))
      .catch(() => {
        // Swallowed here -- the same failure surfaces again (with a user-facing error) via
        // handleStart's own createLiveEngine() call, which awaits this same cached promise.
      });
    return unsubscribe;
  }, []);

  const streamRef = useRef<MediaStream | null>(null);
  const engineRef = useRef<LiveEngineHandle | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recordedChunksRef = useRef<Blob[]>([]);
  const registryRef = useRef<SpeakerRegistry>(createSpeakerRegistry());
  const lastSpeakerRef = useRef<string | null>(null);
  // Timestamp (ms) a pause began, if currently paused -- used to shift recordingStartedAt
  // forward by the paused duration on resume, so the elapsed-time display (driven by
  // useElapsedSeconds, which just measures wall-clock time since recordingStartedAt) excludes
  // time spent paused instead of jumping forward the moment recording resumes.
  const pauseStartRef = useRef<number | null>(null);
  // Accumulates finalized-turn text since the last successful research call (cleared right
  // before each call fires, not when it resolves, so new speech keeps building up during the
  // round-trip instead of being dropped). coveredTopicsRef tracks topic labels already
  // surfaced this session so the backend doesn't repeat itself; researchInFlightRef guards
  // against a slow call still running when the next interval tick fires.
  const pendingResearchTextRef = useRef("");
  const coveredTopicsRef = useRef<string[]>([]);
  const researchInFlightRef = useRef(false);

  const elapsedSeconds = useElapsedSeconds(recordingStartedAt ?? new Date().toISOString(), status === "recording");

  const handleAuthError = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) {
        clearSession();
        router.replace("/login");
        return true;
      }
      return false;
    },
    [router],
  );

  const teardownMedia = useCallback(() => {
    engineRef.current?.dispose();
    engineRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recorderRef.current = null;
  }, []);

  useEffect(() => teardownMedia, [teardownMedia]);

  // Opt-in live-research cadence -- see POST /api/live/research
  // (backend/app/live_research.py) and the constants above. Runs only while
  // actually recording with the feature on; naturally stops (effect cleanup)
  // on pause/stop and restarts on resume via the status dependency, no
  // special-casing needed. A missed or failed beat is swallowed rather than
  // surfaced as a page-level error -- this is a secondary, best-effort
  // feature that should never interrupt the actual recording.
  useEffect(() => {
    if (status !== "recording" || !liveResearchEnabled) return;

    const id = setInterval(async () => {
      const text = pendingResearchTextRef.current.trim();
      if (!text || text.length < MIN_CHARS_TO_TRIGGER || researchInFlightRef.current) return;

      researchInFlightRef.current = true;
      pendingResearchTextRef.current = "";
      try {
        const result = await apiFetch<{ note: ResearchNote | null }>("/api/live/research", {
          method: "POST",
          body: JSON.stringify({ recent_text: text, covered_topics: coveredTopicsRef.current }),
        });
        if (result.note) {
          const note = result.note;
          setResearchNotes((prev) => [...prev, note]);
          coveredTopicsRef.current = [...coveredTopicsRef.current, note.topic].slice(-MAX_COVERED_TOPICS);
        }
      } catch (err) {
        handleAuthError(err);
      } finally {
        researchInFlightRef.current = false;
      }
    }, RESEARCH_INTERVAL_MS);

    return () => clearInterval(id);
  }, [status, liveResearchEnabled, handleAuthError]);

  async function handleStart() {
    setError(null);
    setStatus("starting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      if (saveAudio) {
        recordedChunksRef.current = [];
        const recorder = new MediaRecorder(stream);
        recorder.ondataavailable = (e) => {
          if (e.data.size > 0) recordedChunksRef.current.push(e.data);
        };
        recorder.start();
        recorderRef.current = recorder;
      }

      registryRef.current = createSpeakerRegistry();
      lastSpeakerRef.current = null;
      setTurns([]);
      setPartialText("");
      setResearchNotes([]);
      pendingResearchTextRef.current = "";
      coveredTopicsRef.current = [];

      const engine = await createLiveEngine({
        onPartial: (text) => setPartialText(text),
        onFinal: (turn: LiveTurn) => {
          // Both "no embedding at all" and "embedding present but not a confident match"
          // collapse into the same fallback -- see matchOrRegisterSpeaker's own comments for
          // why an unconfident match shouldn't be trusted as a real identity decision.
          const match = turn.embedding ? matchOrRegisterSpeaker(registryRef.current, turn.embedding) : null;
          const speaker = match?.confident ? match.label : (lastSpeakerRef.current ?? match?.label ?? UNKNOWN_SPEAKER_LABEL);
          lastSpeakerRef.current = speaker;
          setTurns((prev) => [...prev, { speaker, text: turn.text, start_ts: turn.startTs, end_ts: turn.endTs }]);
          setPartialText("");
          if (liveResearchEnabled) {
            pendingResearchTextRef.current += (pendingResearchTextRef.current ? " " : "") + turn.text;
          }
        },
        onError: (message) => {
          setError(message);
          setStatus("idle");
          teardownMedia();
        },
        onLoadProgress: (loaded, total) => setLoadProgress({ loaded, total }),
      });
      engineRef.current = engine;
      await engine.start(stream);

      setRecordingStartedAt(new Date().toISOString());
      setStatus("recording");
    } catch (err) {
      teardownMedia();
      setStatus("idle");
      if (err instanceof DOMException && (err.name === "NotAllowedError" || err.name === "PermissionDeniedError")) {
        setError("Microphone access was denied. Allow microphone access and try again.");
      } else {
        setError(err instanceof Error ? err.message : "Could not start recording.");
      }
    }
  }

  async function handlePause() {
    await engineRef.current?.pause();
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.pause();
    }
    pauseStartRef.current = Date.now();
    setStatus("paused");
  }

  async function handleResume() {
    const pausedMs = pauseStartRef.current ? Date.now() - pauseStartRef.current : 0;
    pauseStartRef.current = null;
    await engineRef.current?.resume();
    if (recorderRef.current?.state === "paused") {
      recorderRef.current.resume();
    }
    setRecordingStartedAt((prev) => (prev ? new Date(new Date(prev).getTime() + pausedMs).toISOString() : prev));
    setStatus("recording");
  }

  async function handleStop() {
    pauseStartRef.current = null;
    setStatus("finalizing");
    setError(null);

    await engineRef.current?.stop();

    let audioBlob: Blob | null = null;
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      audioBlob = await new Promise<Blob>((resolve) => {
        recorder.addEventListener(
          "stop",
          () => resolve(new Blob(recordedChunksRef.current, { type: recorder.mimeType || "audio/webm" })),
          { once: true },
        );
        recorder.stop();
      });
    }

    teardownMedia();
    setRecordingStartedAt(null);

    if (turns.length === 0) {
      setError("No speech was captured -- nothing to save.");
      setStatus("idle");
      return;
    }

    try {
      const formData = new FormData();
      formData.append("title", `Live recording -- ${new Date().toLocaleString()}`);
      formData.append("segments", JSON.stringify(turns));
      if (audioBlob) {
        const ext = audioBlob.type.includes("webm") ? "webm" : "ogg";
        formData.append("audio", audioBlob, `recording.${ext}`);
      }
      if (researchNotes.length > 0) {
        // Links are sent as one shared, already-deduped list (see
        // dedupeReferences) rather than left attached per-note -- the
        // backend just renders both into research.md verbatim, see
        // live_research.render_research_document.
        formData.append(
          "research_notes",
          JSON.stringify(researchNotes.map(({ topic, body }) => ({ topic, body }))),
        );
        formData.append("research_references", JSON.stringify(dedupedReferences));
      }
      const result = await apiFetch<{ job_id: string }>("/api/live/finalize", { method: "POST", body: formData });
      router.push(`/dashboard/jobs/${result.job_id}`);
    } catch (err) {
      if (handleAuthError(err)) return;
      setError(err instanceof ApiError ? err.message : "Failed to save the recording.");
      setStatus("idle");
    }
  }

  const isRecording = status === "recording";
  const isPaused = status === "paused";
  // Once a session has actually started, the main section shows the real transcript instead
  // of the idle/loading graphic -- including while "idle" if turns from a just-finished
  // session are still sitting there because the save to the server failed (see handleStop's
  // catch branch), so that transcript isn't visually discarded just because status reverted.
  const showTranscript = isRecording || isPaused || status === "finalizing" || (status === "idle" && turns.length > 0);
  const loadPercent = loadProgress ? Math.round((loadProgress.loaded / loadProgress.total) * 100) : null;
  // Covers both "status is literally starting" (user clicked Record before preloading
  // finished) and "still idle, but the background preload kicked off on mount hasn't
  // resolved yet" -- either way, the hero below should read as "loading", not "ready".
  const engineLoading = !engineReady && (status === "idle" || status === "starting");
  const dedupedReferences = dedupeReferences(researchNotes);

  const transcriptCardContent = (
    <>
      <h2 className="shrink-0 font-display text-lg font-bold text-ink">Transcript</h2>
      <div className="mt-4 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        <LiveTranscriptTurns turns={turns} />
        {partialText && (
          <div className="flex gap-3 opacity-60">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold bg-paper-shade text-ink-soft">
              ...
            </span>
            <p className="text-sm italic text-ink-soft">{partialText}</p>
          </div>
        )}
        {isRecording && turns.length === 0 && !partialText && <p className="text-sm text-ink-soft">Listening...</p>}
        {isPaused && turns.length === 0 && !partialText && <p className="text-sm text-ink-soft">Paused.</p>}
      </div>
    </>
  );

  // Notes only ever accumulate (see the research effect above, and
  // handleStart's reset) -- never replaced or trimmed, so earlier notes stay
  // visible for the whole session, each rendered as its own card. Links live
  // in one shared, deduped "References" section below rather than repeated
  // per-note (see dedupeReferences) -- the same source commonly gets cited
  // across multiple topics in one session.
  const researchPanelContent = (
    <>
      <h2 className="flex shrink-0 items-center gap-2 font-display text-lg font-bold text-ink">
        <GlobeIcon className="h-4 w-4 text-accent" />
        Research
      </h2>
      <div className="mt-4 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {researchNotes.map((note, i) => (
          <div key={i} className="rounded-md border border-line bg-paper-shade p-3">
            <p className="text-sm font-semibold text-ink">{note.topic}</p>
            <p className="mt-1 text-sm leading-relaxed text-ink-soft">{note.body}</p>
          </div>
        ))}
        {researchNotes.length === 0 && <p className="text-sm text-ink-soft">Listening for a topic to research...</p>}
        {dedupedReferences.length > 0 && (
          <div className="border-t border-line pt-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-ink-soft">References</p>
            <ul className="mt-2 space-y-1">
              {dedupedReferences.map((link) => (
                <li key={link.url}>
                  <a
                    href={link.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-accent underline hover:no-underline"
                  >
                    {link.title}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </>
  );

  return (
    <div className="flex h-full flex-col px-6 py-6">
      <p className="shrink-0 font-sans text-xs font-semibold text-accent">Live → Transcript</p>
      <h1 className="mt-2 shrink-0 font-display text-2xl font-bold tracking-tight text-ink">
        Record live, see who said what as it happens.
      </h1>
      <p className="mt-1 max-w-2xl shrink-0 text-sm text-ink-soft">
        {liveResearchEnabled ? (
          <>
            Speech recognition and speaker diarization run entirely on your device. With live research enabled,
            recent snippets of your transcript are sent to our server as you talk, to look up background info -- the
            finished transcript itself is still only sent anywhere if you choose to save it.
          </>
        ) : (
          <>
            Speech recognition and speaker diarization run entirely on your device -- nothing but the finished
            transcript is sent anywhere, and only if you choose to save it.
          </>
        )}
      </p>

      <div className="mt-6 min-h-0 flex-1">
        {showTranscript ? (
          liveResearchEnabled ? (
            <div className="flex h-full min-h-0 flex-col gap-6 lg:flex-row">
              <div className="flex h-full min-h-0 flex-1 flex-col rounded-lg border border-line bg-paper p-6 shadow-sm">
                {transcriptCardContent}
              </div>
              <div className="flex h-full min-h-0 w-full flex-col rounded-lg border border-line bg-paper p-6 shadow-sm lg:w-80 xl:w-96">
                {researchPanelContent}
              </div>
            </div>
          ) : (
            <div className="mx-auto flex h-full w-full max-w-2xl flex-col rounded-lg border border-line bg-paper p-6 shadow-sm">
              {transcriptCardContent}
            </div>
          )
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <div
              className={`flex h-20 w-20 items-center justify-center rounded-full bg-accent-soft ${
                engineLoading ? "animate-pulse" : ""
              }`}
            >
              <MicrophoneIcon className="h-10 w-10 text-accent" />
            </div>
            <div className="max-w-sm">
              <h2 className="font-display text-xl font-bold text-ink">
                {engineLoading ? "Loading the on-device engine..." : "Ready when you are"}
              </h2>
              <p className="mt-1 text-sm text-ink-soft">
                {engineLoading
                  ? "Downloading the speech + speaker models. This only happens once per browser -- after that, it's cached."
                  : "Press Record below to start a live transcript with speaker labels."}
              </p>
            </div>
            {engineLoading && (
              <div className="w-full max-w-xs">
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-paper-shade">
                  <div
                    className="h-full rounded-full bg-accent transition-[width]"
                    style={{ width: `${loadPercent ?? 0}%` }}
                  />
                </div>
                {loadPercent !== null && <p className="mt-1.5 text-xs text-ink-soft">{loadPercent}%</p>}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="mt-6 shrink-0 rounded-lg border border-line bg-paper p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={saveAudio}
                disabled={status !== "idle"}
                onChange={(e) => setSaveAudio(e.target.checked)}
                className="h-4 w-4"
              />
              Save recording audio (for playback and reprocessing later)
            </label>

            <label className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={liveResearchEnabled}
                disabled={status !== "idle"}
                onChange={(e) => setLiveResearchEnabled(e.target.checked)}
                className="h-4 w-4"
              />
              Show live research panel (sends recent transcript to our server)
            </label>
          </div>

          <div className="flex items-center gap-3">
            {(isRecording || isPaused) && (
              <span className="flex items-center gap-2 text-sm font-medium text-ink-soft">
                <span
                  className={`h-2 w-2 rounded-full ${isRecording ? "animate-pulse bg-status-error" : "bg-ink-soft"}`}
                  aria-hidden
                />
                {isPaused ? "Paused" : "Recording"} -- {formatTimestamp(elapsedSeconds)}
              </span>
            )}

            {status === "idle" && (
              <Button onClick={handleStart}>
                <MicrophoneIcon className="h-4 w-4" />
                Record
              </Button>
            )}
            {status === "starting" && <Button disabled>{loadPercent !== null ? `Loading... ${loadPercent}%` : "Starting..."}</Button>}
            {isRecording && (
              <>
                <Button variant="outline" onClick={handlePause}>
                  <PauseIcon className="h-4 w-4" />
                  Pause
                </Button>
                <Button variant="outline" onClick={handleStop}>
                  <StopIcon className="h-4 w-4" />
                  Stop
                </Button>
              </>
            )}
            {isPaused && (
              <>
                <Button onClick={handleResume}>
                  <PlayIcon className="h-4 w-4" />
                  Resume
                </Button>
                <Button variant="outline" onClick={handleStop}>
                  <StopIcon className="h-4 w-4" />
                  Stop
                </Button>
              </>
            )}
            {status === "finalizing" && <Button disabled>Finalizing...</Button>}
          </div>
        </div>

        {error && <p className="mt-3 text-sm text-status-error">{error}</p>}
      </div>
    </div>
  );
}
