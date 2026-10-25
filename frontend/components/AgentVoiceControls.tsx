"use client";

import { useSyncExternalStore } from "react";

import { SpeakerIcon } from "@/components/icons";
import { PHONON_VOICES } from "@/lib/phononVoices";
import { SERVER_SNAPSHOT, getSnapshot, loadSpeech, speak, stopSpeaking, subscribe } from "@/lib/phononSpeech";

const STORAGE_KEY = "framewrite.agentVoice";
const GROUPS = ["US", "UK", "Character"] as const;

export type VoiceSettings = { auto: boolean; voiceId: string };

const DEFAULT_SETTINGS: VoiceSettings = { auto: false, voiceId: "" };

const settingsListeners = new Set<() => void>();
// Cached by raw string so getSnapshot returns a stable object until storage
// actually changes -- same reasoning as lib/auth.ts's getStoredUser.
let cachedRaw: string | null | undefined;
let cachedSettings: VoiceSettings = DEFAULT_SETTINGS;

function readSettings(): VoiceSettings {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Unavailable storage just means settings don't persist.
  }
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      cachedSettings = raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : DEFAULT_SETTINGS;
    } catch {
      cachedSettings = DEFAULT_SETTINGS;
    }
  }
  return cachedSettings;
}

function subscribeSettings(listener: () => void): () => void {
  settingsListeners.add(listener);
  return () => settingsListeners.delete(listener);
}

/** Persisted per browser (not per agent): whether replies are read aloud
 * automatically and which voice to use. "" means the model's built-in voice. */
export function useVoiceSettings(): [VoiceSettings, (patch: Partial<VoiceSettings>) => void] {
  const settings = useSyncExternalStore(subscribeSettings, readSettings, () => DEFAULT_SETTINGS);

  function update(patch: Partial<VoiceSettings>) {
    const next = { ...readSettings(), ...patch };
    const json = JSON.stringify(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, json);
    } catch {}
    cachedRaw = json;
    cachedSettings = next;
    settingsListeners.forEach((l) => l());
  }
  return [settings, update];
}

export function useSpeech() {
  return useSyncExternalStore(subscribe, getSnapshot, () => SERVER_SNAPSHOT);
}

/** Voice picker + "read replies aloud" toggle for AgentChat. Phonon runs
 * entirely in the browser (see lib/phononSpeech.ts), so the first use downloads
 * the ~65MB model; after that it works offline. */
export default function AgentVoiceControls({
  settings,
  onChange,
}: {
  settings: VoiceSettings;
  onChange: (patch: Partial<VoiceSettings>) => void;
}) {
  const speech = useSpeech();

  function handleAutoChange(auto: boolean) {
    onChange({ auto });
    if (auto) void loadSpeech().catch(() => {});
    else stopSpeaking();
  }

  function handleVoiceChange(voiceId: string) {
    onChange({ voiceId });
    const voice = PHONON_VOICES.find((v) => v.id === voiceId);
    void speak("preview", voice ? `Hi, I'm ${voice.name}.` : "Hi, this is the default voice.", voiceId).catch(() => {});
  }

  const selected = PHONON_VOICES.find((v) => v.id === settings.voiceId);

  return (
    <div className="mb-3 rounded-lg border border-line bg-paper-shade px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <label className="flex items-center gap-2 text-ink">
          <input
            type="checkbox"
            checked={settings.auto}
            onChange={(e) => handleAutoChange(e.target.checked)}
            className="h-4 w-4 rounded border-line accent-accent"
          />
          <SpeakerIcon className="h-4 w-4" />
          Read replies aloud
        </label>
        <label className="flex items-center gap-2 text-ink-soft">
          Voice
          <select
            value={settings.voiceId}
            onChange={(e) => handleVoiceChange(e.target.value)}
            className="rounded-md border border-line bg-paper px-2 py-1 text-sm text-ink outline-none focus:border-accent"
          >
            <option value="">Default</option>
            {GROUPS.map((group) => (
              <optgroup key={group} label={group === "Character" ? "Characters" : `${group} English`}>
                {PHONON_VOICES.filter((v) => v.group === group).map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                    {v.gender ? ` (${v.gender === "female" ? "F" : "M"})` : ""}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
      </div>
      {selected && <p className="mt-1 text-xs text-ink-soft">{selected.description}</p>}
      {speech.status === "loading" && (
        <p className="mt-1 text-xs text-ink-soft">
          Downloading the voice model{speech.loadPercent != null ? ` (${speech.loadPercent}%)` : ""} -- one time only, then
          it works offline.
        </p>
      )}
      {speech.status === "error" && (
        <p className="mt-1 text-xs text-status-error">
          Couldn&apos;t start the voice: {speech.error}
        </p>
      )}
    </div>
  );
}
