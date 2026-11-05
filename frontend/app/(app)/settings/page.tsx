"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import AgentVoiceControls, { useVoiceSettings } from "@/components/AgentVoiceControls";
import Button from "@/components/Button";
import Card from "@/components/Card";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession, type CurrentUser } from "@/lib/auth";
import type { Preferences } from "@/lib/preferences";
import { applyTheme, loadThemePreference, saveThemePreference, type ThemePreference } from "@/lib/theme";

const DEFAULT_BOT_NAME = "Framewrite Notetaker";

type ToggleKey = Exclude<keyof Preferences, "default_bot_name">;

const NOTIFICATIONS: { key: ToggleKey; label: string; hint: string }[] = [
  {
    key: "notify_job_done",
    label: "Document ready",
    hint: "Email me when a video, audio or live recording has finished processing. Failures are always emailed.",
  },
  {
    key: "notify_meeting_notes",
    label: "Meeting notes ready",
    hint: "Default for new meetings: email me when the notetaker's analysis is ready. You can change it per meeting.",
  },
  {
    key: "notify_review_reminder",
    label: "Review reminders",
    hint: "Remind me if a job has been waiting for my review for a day.",
  },
  {
    key: "product_announcements",
    label: "Product announcements",
    hint: "Occasional news about new features. Receipts and account emails are not affected.",
  },
];

const THEMES: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export default function SettingsPage() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [botName, setBotName] = useState("");
  const [savedNote, setSavedNote] = useState<string | null>(null);
  // Only rendered once the settings have loaded (client-side), so reading
  // localStorage during init can't cause a hydration mismatch.
  const [theme, setTheme] = useState<ThemePreference>(() => loadThemePreference());
  const [voice, updateVoice] = useVoiceSettings();

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

  useEffect(() => {
    Promise.all([apiFetch<CurrentUser>("/api/auth/me"), apiFetch<Preferences>("/api/me/preferences")])
      .then(([me, p]) => {
        setUser(me);
        setPrefs(p);
        setBotName(p.default_bot_name);
      })
      .catch((err) => {
        if (handleAuthError(err)) return;
        setLoadError(err instanceof ApiError ? err.message : "Failed to load your settings.");
      });
  }, [handleAuthError]);

  async function save(patch: Partial<Preferences>, key: string) {
    setSaving(key);
    setError(null);
    setSavedNote(null);
    try {
      const updated = await apiFetch<Preferences>("/api/me/preferences", {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setPrefs(updated);
      setBotName(updated.default_bot_name);
      return true;
    } catch (err) {
      if (handleAuthError(err)) return false;
      setError(err instanceof ApiError ? err.message : "Couldn't save that setting.");
      return false;
    } finally {
      setSaving(null);
    }
  }

  function chooseTheme(next: ThemePreference) {
    setTheme(next);
    applyTheme(next);
    saveThemePreference(next);
  }

  const botNameChanged = prefs !== null && botName.trim() !== prefs.default_bot_name;

  return (
    <div className="w-full max-w-3xl px-6 py-10">
      <h1 className="font-display text-2xl font-bold tracking-tight text-ink">Profile &amp; preferences</h1>
      <p className="mt-1 text-sm text-ink-soft">
        Your account details and how Framewrite contacts you. API keys, integrations and billing are in the tabs above.
      </p>

      {loadError && <p className="mt-6 text-sm text-status-error">{loadError}</p>}
      {!prefs && !loadError && <p className="mt-6 text-sm text-ink-soft">Loading...</p>}
      {error && <p className="mt-4 text-sm text-status-error">{error}</p>}

      {user && prefs && (
        <div className="mt-8 flex flex-col gap-6">
          <Card className="p-6">
            <h2 className="text-sm font-semibold text-ink">Profile</h2>
            <div className="mt-4 flex items-center gap-4">
              {user.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element -- Google's avatar CDN, one small image
                <img src={user.avatar_url} alt="" width={48} height={48} className="h-12 w-12 rounded-full" referrerPolicy="no-referrer" />
              ) : (
                <span className="flex h-12 w-12 items-center justify-center rounded-full bg-ink text-lg font-semibold text-paper">
                  {(user.display_name || user.email).charAt(0).toUpperCase()}
                </span>
              )}
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-ink">{user.display_name || "No name set"}</p>
                <p className="truncate text-sm text-ink-soft">{user.email}</p>
              </div>
            </div>
            <p className="mt-4 text-xs text-ink-soft">
              Your name, email and photo come from your Google account, so change them there.
            </p>
          </Card>

          <Card className="p-6">
            <h2 className="text-sm font-semibold text-ink">Email notifications</h2>
            <ul className="mt-4 divide-y divide-line">
              {NOTIFICATIONS.map((n) => (
                <li key={n.key} className="py-3 first:pt-0 last:pb-0">
                  <label className="flex cursor-pointer items-start gap-3">
                    <input
                      type="checkbox"
                      checked={prefs[n.key]}
                      disabled={saving === n.key}
                      onChange={(e) => save({ [n.key]: e.target.checked }, n.key)}
                      className="mt-1 h-4 w-4 rounded border-line accent-accent"
                    />
                    <span>
                      <span className="block text-sm font-medium text-ink">{n.label}</span>
                      <span className="block text-xs text-ink-soft">{n.hint}</span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </Card>

          {user.features?.meetings && (
            <Card className="p-6">
              <h2 className="text-sm font-semibold text-ink">Meetings</h2>
              <form
                className="mt-4"
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (await save({ default_bot_name: botName.trim() }, "bot")) setSavedNote("Saved.");
                }}
              >
                <label htmlFor="bot-name" className="block text-sm font-medium text-ink">
                  Default notetaker name
                </label>
                <p className="text-xs text-ink-soft">
                  What attendees see the bot called. You can still change it for each meeting.
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <input
                    id="bot-name"
                    type="text"
                    value={botName}
                    maxLength={50}
                    onChange={(e) => {
                      setBotName(e.target.value);
                      setSavedNote(null);
                    }}
                    placeholder={DEFAULT_BOT_NAME}
                    className="w-72 rounded-md border border-line bg-paper px-3 py-2 text-sm text-ink outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft"
                  />
                  <Button type="submit" disabled={!botNameChanged || saving === "bot"}>
                    {saving === "bot" ? "Saving..." : "Save"}
                  </Button>
                  {savedNote && <span className="text-sm text-status-success">{savedNote}</span>}
                </div>
              </form>
            </Card>
          )}

          <Card className="p-6">
            <h2 className="text-sm font-semibold text-ink">Appearance</h2>
            <p className="text-xs text-ink-soft">Saved in this browser.</p>
            <div className="mt-3 inline-flex overflow-hidden rounded-md border border-line text-sm" role="group" aria-label="Theme">
              {THEMES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => chooseTheme(t.value)}
                  aria-pressed={theme === t.value}
                  className={`px-4 py-1.5 ${theme === t.value ? "bg-accent-soft font-semibold text-accent" : "text-ink-soft hover:bg-paper-shade"}`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </Card>

          <Card className="p-6">
            <h2 className="text-sm font-semibold text-ink">Agent voice</h2>
            <p className="mb-3 text-xs text-ink-soft">Read agent replies aloud. Saved in this browser.</p>
            <AgentVoiceControls settings={voice} onChange={updateVoice} />
          </Card>
        </div>
      )}
    </div>
  );
}
