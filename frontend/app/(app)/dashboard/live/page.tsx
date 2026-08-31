"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import Button from "@/components/Button";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { formatTimestamp } from "@/lib/jobs";
import type { LiveEngineHandle, LiveTurn } from "@/lib/liveEngine";
import { createLiveEngine } from "@/lib/liveEngineProvider";
import { createSpeakerRegistry, matchOrRegisterSpeaker, type SpeakerRegistry } from "@/lib/speakerMatch";
import { speakerColorFor, speakerInitials } from "@/lib/speakerColors";
import { useElapsedSeconds } from "@/lib/useElapsedSeconds";

type Status = "idle" | "starting" | "recording" | "finalizing";

type FinalizedTurn = { speaker: string; text: string; start_ts: number; end_ts: number };

// No speaker embedding available yet for a turn (engine still loading it, or
// running in a browser that can't support it) -- everything collapses into
// one speaker rather than failing the whole recording. See
// plan/realtime-diarization-plan.md's degradation path.
const UNKNOWN_SPEAKER_LABEL = "Speaker 1";

export default function LivePage() {
  const router = useRouter();
  const [status, setStatus] = useState<Status>("idle");
  const [saveAudio, setSaveAudio] = useState(false);
  const [turns, setTurns] = useState<FinalizedTurn[]>([]);
  const [partialText, setPartialText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [recordingStartedAt, setRecordingStartedAt] = useState<string | null>(null);

  const streamRef = useRef<MediaStream | null>(null);
  const engineRef = useRef<LiveEngineHandle | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recordedChunksRef = useRef<Blob[]>([]);
  const registryRef = useRef<SpeakerRegistry>(createSpeakerRegistry());

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
      setTurns([]);
      setPartialText("");

      const engine = await createLiveEngine({
        onPartial: (text) => setPartialText(text),
        onFinal: (turn: LiveTurn) => {
          const speaker = turn.embedding
            ? matchOrRegisterSpeaker(registryRef.current, turn.embedding)
            : UNKNOWN_SPEAKER_LABEL;
          setTurns((prev) => [...prev, { speaker, text: turn.text, start_ts: turn.startTs, end_ts: turn.endTs }]);
          setPartialText("");
        },
        onError: (message) => {
          setError(message);
          setStatus("idle");
          teardownMedia();
        },
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

  async function handleStop() {
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
      const result = await apiFetch<{ job_id: string }>("/api/live/finalize", { method: "POST", body: formData });
      router.push(`/dashboard/jobs/${result.job_id}`);
    } catch (err) {
      if (handleAuthError(err)) return;
      setError(err instanceof ApiError ? err.message : "Failed to save the recording.");
      setStatus("idle");
    }
  }

  const isRecording = status === "recording";
  const speakers = [...new Set(turns.map((t) => t.speaker))];

  return (
    <div className="w-full px-6 py-10">
      <p className="font-sans text-xs font-semibold text-accent">Live → Transcript</p>
      <h1 className="mt-2 font-display text-2xl font-bold tracking-tight text-ink">
        Record live, see who said what as it happens.
      </h1>
      <p className="mt-1 max-w-2xl text-sm text-ink-soft">
        Speech recognition and speaker diarization run entirely on your device -- nothing but the finished transcript
        is sent anywhere, and only if you choose to save it.
      </p>

      <div className="mt-8 max-w-2xl rounded-lg border border-line bg-paper p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
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

          {status === "idle" && (
            <Button onClick={handleStart}>Start recording</Button>
          )}
          {status === "starting" && <Button disabled>Starting...</Button>}
          {isRecording && (
            <Button variant="outline" onClick={handleStop}>
              <span className="h-2 w-2 rounded-full bg-status-error" aria-hidden />
              Stop -- {formatTimestamp(elapsedSeconds)}
            </Button>
          )}
          {status === "finalizing" && <Button disabled>Finalizing...</Button>}
        </div>

        {error && <p className="mt-3 text-sm text-status-error">{error}</p>}
      </div>

      {(turns.length > 0 || partialText || isRecording) && (
        <div className="mt-6 max-w-2xl rounded-lg border border-line bg-paper p-6 shadow-sm">
          <h2 className="font-display text-lg font-bold text-ink">Transcript</h2>
          <div className="mt-4 max-h-[28rem] space-y-3 overflow-y-auto pr-1">
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
            {partialText && (
              <div className="flex gap-3 opacity-60">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold bg-paper-shade text-ink-soft">
                  ...
                </span>
                <p className="text-sm italic text-ink-soft">{partialText}</p>
              </div>
            )}
            {isRecording && turns.length === 0 && !partialText && (
              <p className="text-sm text-ink-soft">Listening...</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
