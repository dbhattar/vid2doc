"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import Button from "@/components/Button";
import MeetingRow from "@/components/MeetingRow";
import { apiFetch, ApiError } from "@/lib/api";
import { dayKey, meetingDate, type Meeting } from "@/lib/meetings";

const DEFAULT_BOT_NAME = "Framewrite Notetaker";
const MAX_SCHEDULE_AHEAD_DAYS = 30; // matches the API's limit
const DURATION_PRESETS = [15, 30, 45, 60, 90, 120, 180];
const CUSTOM = "custom";

function durationLabel(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  if (minutes === 60) return "1 hour";
  return minutes % 60 === 0 ? `${minutes / 60} hours` : `${Math.floor(minutes / 60)} hr ${minutes % 60} min`;
}

/** A sensible start time to prefill: the next half hour for today, else 9:00. */
function defaultTime(day: string): string {
  if (day !== dayKey(new Date())) return "09:00";
  const d = new Date(Date.now() + 5 * 60_000);
  d.setMinutes(d.getMinutes() <= 30 ? 30 : 60, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Side sheet opened by clicking a calendar day: that day's meetings, and the
 * form to add one -- link, start time, how long it will run, and the options. */
export default function MeetingDayPanel({
  day,
  meetings,
  defaults,
  busyId,
  onClose,
  onCreated,
  onCancel,
  onProcess,
  onToggleNotify,
  onAuthError,
}: {
  day: string; // YYYY-MM-DD, local
  meetings: Meeting[];
  defaults: { botName: string; notify: boolean };
  busyId: string | null;
  onClose: () => void;
  onCreated: () => void;
  onCancel: (m: Meeting) => void;
  onProcess: (m: Meeting) => void;
  onToggleNotify: (m: Meeting, value: boolean) => void;
  onAuthError: (err: unknown) => boolean;
}) {
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [time, setTime] = useState(() => defaultTime(day));
  const [durationChoice, setDurationChoice] = useState("60");
  const [customMinutes, setCustomMinutes] = useState("45");
  const [botName, setBotName] = useState(defaults.botName);
  const [notify, setNotify] = useState(defaults.notify);
  const [submitting, setSubmitting] = useState<"schedule" | "now" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsFunds, setNeedsFunds] = useState(false);

  const todayKey = dayKey(new Date());
  const lastBookable = (() => {
    const d = new Date();
    d.setDate(d.getDate() + MAX_SCHEDULE_AHEAD_DAYS);
    return dayKey(d);
  })();
  const isToday = day === todayKey;
  const canSchedule = day >= todayKey && day <= lastBookable;
  const dayMeetings = meetings
    .filter((m) => dayKey(meetingDate(m)) === day)
    .sort((a, b) => meetingDate(a).getTime() - meetingDate(b).getTime());
  const label = new Date(`${day}T00:00`).toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  // Escape closes the sheet.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const durationMinutes = durationChoice === CUSTOM ? Number.parseInt(customMinutes, 10) : Number(durationChoice);
  const endsAt = (() => {
    const start = new Date(`${day}T${time}`);
    return Number.isNaN(start.getTime()) || !durationMinutes
      ? null
      : new Date(start.getTime() + durationMinutes * 60_000);
  })();

  async function submit(mode: "schedule" | "now") {
    if (!url.trim()) {
      setError("Paste the meeting link.");
      return;
    }
    if (!Number.isInteger(durationMinutes) || durationMinutes < 5 || durationMinutes > 480) {
      setError("Duration must be between 5 minutes and 8 hours.");
      return;
    }
    let startTime: Date | null = null;
    if (mode === "schedule") {
      startTime = new Date(`${day}T${time}`);
      if (!time || Number.isNaN(startTime.getTime())) {
        setError("Pick a start time.");
        return;
      }
    }
    setSubmitting(mode);
    setError(null);
    setNeedsFunds(false);
    try {
      await apiFetch("/api/meetings", {
        method: "POST",
        body: JSON.stringify({
          url: url.trim(),
          title: title.trim() || undefined,
          bot_name: botName.trim() || undefined,
          // datetime parsed as local time; toISOString() is the UTC instant the API wants.
          start_time: startTime ? startTime.toISOString() : undefined,
          duration_minutes: durationMinutes,
          notify_when_ready: notify,
        }),
      });
      setUrl("");
      setTitle("");
      onCreated();
    } catch (err) {
      if (onAuthError(err)) return;
      setError(err instanceof ApiError ? err.message : "Couldn't send the notetaker.");
      setNeedsFunds(err instanceof ApiError && err.status === 402);
    } finally {
      setSubmitting(null);
    }
  }

  const inputClass =
    "w-full rounded-md border border-line bg-paper px-3 py-2 text-sm text-ink outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft";

  return (
    <>
      <div className="fixed inset-0 z-40 bg-ink/40" onClick={onClose} aria-hidden="true" />
      <aside
        role="dialog"
        aria-label={`Meetings on ${label}`}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col overflow-y-auto border-l border-line bg-paper shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="font-display text-lg font-bold text-ink">{label}</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-md px-2 py-1 text-ink-soft hover:bg-paper-shade hover:text-ink"
          >
            ✕
          </button>
        </div>

        {dayMeetings.length > 0 && (
          <section className="border-b border-line">
            <h3 className="px-5 pt-4 text-xs font-semibold uppercase text-ink-soft">On this day</h3>
            <ul className="divide-y divide-line">
              {dayMeetings.map((m) => (
                <MeetingRow
                  key={m.id}
                  meeting={m}
                  busy={busyId === m.id}
                  onCancel={onCancel}
                  onProcess={onProcess}
                  onToggleNotify={onToggleNotify}
                />
              ))}
            </ul>
          </section>
        )}

        <form
          className="flex flex-col gap-4 px-5 py-5"
          onSubmit={(e) => {
            e.preventDefault();
            void submit("schedule");
          }}
        >
          <h3 className="text-sm font-semibold text-ink">Add a meeting</h3>

          {!canSchedule ? (
            <p className="text-sm text-ink-soft">
              {day < todayKey
                ? "Meetings can't be added in the past."
                : `Meetings can be scheduled up to ${MAX_SCHEDULE_AHEAD_DAYS} days ahead.`}
            </p>
          ) : (
            <>
              <label className="block text-sm font-medium text-ink">
                Meeting link
                <input
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://zoom.us/j/... or https://meet.google.com/..."
                  required
                  className={`mt-1 ${inputClass}`}
                />
              </label>
              <label className="block text-sm font-medium text-ink">
                Title <span className="font-normal text-ink-soft">(optional)</span>
                <input
                  type="text"
                  value={title}
                  maxLength={200}
                  onChange={(e) => setTitle(e.target.value)}
                  className={`mt-1 ${inputClass}`}
                />
              </label>

              <div className="grid grid-cols-2 gap-3">
                <label className="block text-sm font-medium text-ink">
                  Start time
                  <input
                    type="time"
                    value={time}
                    onChange={(e) => setTime(e.target.value)}
                    className={`mt-1 ${inputClass}`}
                  />
                </label>
                <label className="block text-sm font-medium text-ink">
                  Duration
                  <select
                    value={durationChoice}
                    onChange={(e) => setDurationChoice(e.target.value)}
                    className={`mt-1 ${inputClass}`}
                  >
                    {DURATION_PRESETS.map((m) => (
                      <option key={m} value={m}>
                        {durationLabel(m)}
                      </option>
                    ))}
                    <option value={CUSTOM}>Custom...</option>
                  </select>
                </label>
              </div>
              {durationChoice === CUSTOM && (
                <label className="block text-sm font-medium text-ink">
                  Minutes
                  <input
                    type="number"
                    min={5}
                    max={480}
                    value={customMinutes}
                    onChange={(e) => setCustomMinutes(e.target.value)}
                    className={`mt-1 ${inputClass}`}
                  />
                </label>
              )}
              {endsAt && (
                <p className="-mt-2 text-xs text-ink-soft">
                  Ends about {endsAt.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}. The
                  notetaker stays up to 15 minutes past that if the meeting runs over, then leaves.
                </p>
              )}

              <label className="block text-sm font-medium text-ink">
                Notetaker name <span className="font-normal text-ink-soft">(optional)</span>
                <input
                  type="text"
                  value={botName}
                  maxLength={50}
                  onChange={(e) => setBotName(e.target.value)}
                  placeholder={DEFAULT_BOT_NAME}
                  className={`mt-1 ${inputClass}`}
                />
              </label>
              <label className="flex items-center gap-2 text-sm text-ink">
                <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} />
                Email me when the notes are ready
                <Link href="/settings" className="text-xs text-ink-soft underline">
                  Defaults in Settings
                </Link>
              </label>

              {error && (
                <p className="text-sm text-status-error">
                  {error}
                  {needsFunds && (
                    <>
                      {" "}
                      <Link href="/settings/billing" className="underline">
                        Manage billing
                      </Link>
                    </>
                  )}
                </p>
              )}

              <div className="flex flex-wrap gap-3">
                <Button type="submit" disabled={submitting !== null} className="justify-center">
                  {submitting === "schedule" ? "Scheduling..." : "Schedule notetaker"}
                </Button>
                {isToday && (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={submitting !== null}
                    onClick={() => void submit("now")}
                    className="justify-center"
                  >
                    {submitting === "now" ? "Sending..." : "Join now instead"}
                  </Button>
                )}
              </div>

              <p className="text-xs text-ink-soft">
                $1.00 per hour of meeting, charged when it ends. The bot appears as a participant named &ldquo;
                {botName.trim() || DEFAULT_BOT_NAME}&rdquo; &mdash; pick a name attendees will recognise as a
                notetaker &mdash; and you may need to admit it from the waiting room. You&apos;re responsible for
                telling attendees the meeting is being recorded.
              </p>
            </>
          )}
        </form>
      </aside>
    </>
  );
}
