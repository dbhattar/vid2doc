"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Button from "@/components/Button";
import Card from "@/components/Card";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";

type SettingValue = number | boolean | string;

type Setting = {
  name: string;
  group: string;
  label: string;
  description: string;
  type: "int" | "float" | "bool" | "str" | "choice";
  min: number | null;
  max: number | null;
  choices: string[];
  max_length: number;
  unit: string;
  value: SettingValue;
  default: SettingValue;
  overridden: boolean;
  updated_at: string | null;
  updated_by: string | null;
};

// Changing these affects money or whether jobs run at all, so they ask first.
const CONFIRM_GROUPS = new Set(["Pricing", "AI models"]);

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.round(seconds % 60);
  return [h && `${h}h`, m && `${m}m`, (s || (!h && !m)) && `${s}s`].filter(Boolean).join(" ");
}

/** A plain-language reading of a raw number (a price per hour, a size, a
 * duration) so nobody has to do the arithmetic. */
function hint(setting: Setting, raw: string): string | null {
  const n = Number(raw);
  if (setting.type !== "int" && setting.type !== "float") return null;
  if (raw.trim() === "" || !Number.isFinite(n) || n <= 0) return null;
  if (setting.name.startsWith("SECONDS_PER_CENT_")) return `≈ $${(3600 / n / 100).toFixed(2)} per hour`;
  if (setting.unit === "bytes") return `≈ ${(n / 1024 ** 3).toFixed(2)} GB`;
  if (setting.unit === "seconds" && n >= 60) return `≈ ${formatDuration(n)}`;
  if (setting.unit === "cents") return `≈ $${(n / 100).toFixed(2)}`;
  return null;
}

function show(setting: Setting, value: SettingValue): string {
  if (setting.type === "bool") return value ? "on" : "off";
  return String(value);
}

function SettingRow({
  setting,
  onChange,
  onAuthError,
}: {
  setting: Setting;
  onChange: (next: Setting) => void;
  onAuthError: (err: unknown) => boolean;
}) {
  const initial: string | boolean = setting.type === "bool" ? Boolean(setting.value) : String(setting.value);
  const [draft, setDraft] = useState<string | boolean>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty = draft !== initial;

  function parsed(): SettingValue | null {
    if (setting.type === "bool" || setting.type === "str" || setting.type === "choice") return draft as SettingValue;
    const n = Number(draft);
    return String(draft).trim() === "" || Number.isNaN(n) ? null : n;
  }

  async function run(request: () => Promise<Setting>) {
    setBusy(true);
    setError(null);
    try {
      const next = await request();
      onChange(next);
      setDraft(next.type === "bool" ? Boolean(next.value) : String(next.value));
    } catch (err) {
      if (onAuthError(err)) return;
      setError(err instanceof ApiError ? err.message : "Couldn't save that setting.");
    } finally {
      setBusy(false);
    }
  }

  function save() {
    const value = parsed();
    if (value === null) {
      setError("Enter a number.");
      return;
    }
    if (
      CONFIRM_GROUPS.has(setting.group) &&
      !confirm(`Change "${setting.label}" from ${show(setting, setting.value)} to ${show(setting, value)}? This takes effect for everyone within seconds.`)
    ) {
      return;
    }
    run(() =>
      apiFetch<Setting>(`/api/admin/settings/${setting.name}`, { method: "PUT", body: JSON.stringify({ value }) }),
    );
  }

  function reset() {
    if (!confirm(`Reset "${setting.label}" to its default (${show(setting, setting.default)})?`)) return;
    run(() => apiFetch<Setting>(`/api/admin/settings/${setting.name}`, { method: "DELETE" }));
  }

  const inputClass =
    "rounded-md border border-line bg-paper px-3 py-1.5 text-sm text-ink outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft";
  const draftHint = typeof draft === "string" ? hint(setting, draft) : null;

  return (
    <li className="flex flex-col gap-3 px-4 py-4 md:flex-row md:items-start md:justify-between md:gap-8">
      <div className="min-w-0 md:max-w-xl">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium text-ink">{setting.label}</p>
          {setting.overridden && (
            <span
              className="rounded-full border border-accent bg-accent-soft px-2 py-0.5 text-[10px] font-semibold uppercase leading-none text-accent"
              title={
                setting.updated_at
                  ? `Changed ${new Date(setting.updated_at).toLocaleString()}${setting.updated_by ? ` by ${setting.updated_by}` : ""}`
                  : undefined
              }
            >
              Changed
            </span>
          )}
        </div>
        <p className="mt-0.5 text-xs text-ink-soft">{setting.description}</p>
        <p className="mt-1 text-xs text-ink-soft">
          Default: <span className="font-mono">{show(setting, setting.default)}</span>
          {setting.unit && setting.type !== "bool" && ` ${setting.unit}`}
          {setting.min !== null && setting.max !== null && ` · allowed ${setting.min}–${setting.max}`}
        </p>
        {error && <p className="mt-1 text-xs text-status-error">{error}</p>}
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-2">
        {setting.type === "bool" ? (
          <label className="flex items-center gap-2 text-sm text-ink">
            <input type="checkbox" checked={draft as boolean} onChange={(e) => setDraft(e.target.checked)} />
            {draft ? "On" : "Off"}
          </label>
        ) : setting.type === "choice" ? (
          <select value={draft as string} onChange={(e) => setDraft(e.target.value)} className={inputClass}>
            {setting.choices.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        ) : (
          <div className="flex flex-col items-end gap-0.5">
            <input
              type={setting.type === "str" ? "text" : "number"}
              value={draft as string}
              step={setting.type === "float" ? "any" : 1}
              maxLength={setting.type === "str" ? setting.max_length : undefined}
              onChange={(e) => setDraft(e.target.value)}
              aria-label={setting.label}
              className={`${inputClass} ${setting.type === "str" ? "w-56" : "w-36 text-right"}`}
            />
            {draftHint && <span className="text-[11px] text-ink-soft">{draftHint}</span>}
          </div>
        )}
        <Button onClick={save} disabled={!dirty || busy} className="!px-3 !py-1.5">
          {busy ? "Saving..." : "Save"}
        </Button>
        {setting.overridden && (
          <Button variant="secondary" onClick={reset} disabled={busy}>
            Reset
          </Button>
        )}
      </div>
    </li>
  );
}

/** Admin-only: tune the app's operational settings (prices, limits, feature
 * switches, models, timings) live, without environment variables or a
 * redeploy. The settings and their bounds are defined server-side in
 * backend/app/tunables.py; an unchanged setting uses the server's environment
 * value, and Reset returns to it. */
export default function AdminSettingsPage() {
  const router = useRouter();
  const [groups, setGroups] = useState<string[]>([]);
  const [settings, setSettings] = useState<Setting[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function handleAuthError(err: unknown): boolean {
    if (err instanceof ApiError && err.status === 401) {
      clearSession();
      router.replace("/login");
      return true;
    }
    if (err instanceof ApiError && err.status === 403) {
      router.replace("/dashboard");
      return true;
    }
    return false;
  }

  useEffect(() => {
    apiFetch<{ groups: string[]; settings: Setting[] }>("/api/admin/settings")
      .then((data) => {
        setGroups(data.groups);
        setSettings(data.settings);
      })
      .catch((err) => {
        if (handleAuthError(err)) return;
        setError(err instanceof ApiError ? err.message : "Failed to load settings.");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="w-full px-6 py-10">
      <Link href="/admin" className="text-sm text-ink-soft hover:underline">
        &larr; Back to Admin
      </Link>
      <h1 className="mt-2 font-display text-2xl font-bold tracking-tight text-ink">Settings</h1>
      <p className="mt-1 max-w-2xl text-sm text-ink-soft">
        Tune prices, limits and switches without touching environment variables. Changes apply to everyone within a
        few seconds, no restart. A setting you haven&apos;t changed uses the server&apos;s configured value, and Reset
        goes back to it.
      </p>

      {error && <p className="mt-4 text-sm text-status-error">{error}</p>}
      {!settings && !error && <p className="mt-6 text-sm text-ink-soft">Loading...</p>}

      {settings &&
        groups.map((group) => (
          <section key={group} className="mt-8">
            <h2 className="font-sans text-sm font-semibold text-ink-soft">{group}</h2>
            <Card className="mt-2 overflow-hidden p-0">
              <ul className="divide-y divide-line">
                {settings
                  .filter((s) => s.group === group)
                  .map((s) => (
                    <SettingRow
                      key={s.name}
                      setting={s}
                      onAuthError={handleAuthError}
                      onChange={(next) => setSettings((prev) => prev?.map((p) => (p.name === next.name ? next : p)) ?? null)}
                    />
                  ))}
              </ul>
            </Card>
          </section>
        ))}
    </div>
  );
}
