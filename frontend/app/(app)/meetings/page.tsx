"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Button from "@/components/Button";
import Card from "@/components/Card";
import MeetingsRequestAccess, { type MeetingsRequestStatus } from "@/components/MeetingsRequestAccess";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { isActiveMeeting, MEETING_STATUS_LABELS, PLATFORM_LABELS, type Meeting } from "@/lib/meetings";

const POLL_INTERVAL_MS = 5000;
const BOT_NAME_KEY = "framewrite_meeting_bot_name";
const DEFAULT_BOT_NAME = "Framewrite Notetaker";

const STATUS_COLORS: Record<Meeting["status"], string> = {
  scheduled: "text-accent",
  joining: "text-status-info",
  recording: "text-status-error",
  processing: "text-status-info",
  done: "text-status-success",
  failed: "text-status-error",
  cancelled: "text-ink-soft",
  awaiting_payment: "text-accent",
};

export default function MeetingsPage() {
  const router = useRouter();
  const [access, setAccess] = useState<{ hasAccess: boolean; requestStatus: MeetingsRequestStatus } | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);

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
    apiFetch<{ has_access: boolean; request_status: MeetingsRequestStatus }>("/api/features/meetings/request")
      .then((data) => setAccess({ hasAccess: data.has_access, requestStatus: data.request_status }))
      .catch((err) => {
        if (handleAuthError(err)) return;
        setAccessError(err instanceof ApiError ? err.message : "Failed to load Meetings.");
      });
  }, [handleAuthError]);

  return (
    <div className="w-full px-6 py-10">
      <p className="font-sans text-xs font-semibold text-accent">
        Meetings → Notes{" "}
        <span className="ml-1 rounded-full border border-line px-2 py-0.5 text-[10px] font-semibold uppercase text-ink-soft">
          Preview
        </span>
      </p>
      <h1 className="mt-2 font-display text-2xl font-bold tracking-tight text-ink">
        Send a notetaker to your next meeting.
      </h1>
      <p className="mt-1 max-w-2xl text-sm text-ink-soft">
        Paste a Zoom, Google Meet, or Microsoft Teams link. A bot joins, records the audio, and when the meeting ends
        you get a speaker-labelled transcript with a summary, decisions, and action items -- we&apos;ll email you when
        it&apos;s ready.
      </p>

      {accessError && <p className="mt-6 text-sm text-status-error">{accessError}</p>}
      {!access && !accessError && <p className="mt-6 text-sm text-ink-soft">Loading...</p>}
      {access && !access.hasAccess && (
        <MeetingsRequestAccess initialStatus={access.requestStatus} onAuthError={handleAuthError} />
      )}
      {access?.hasAccess && <MeetingsApp />}
    </div>
  );
}

function MeetingsApp() {
  const router = useRouter();
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [botName, setBotName] = useState(() => {
    // Remembered from the last meeting so it doesn't have to be retyped.
    try {
      return window.localStorage.getItem(BOT_NAME_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [when, setWhen] = useState<"now" | "later">("now");
  const [startAt, setStartAt] = useState(""); // <input type="datetime-local"> value, browser-local time
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [needsFunds, setNeedsFunds] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

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

  const loadMeetings = useCallback(() => {
    apiFetch<{ meetings: Meeting[] }>("/api/meetings")
      .then((data) => setMeetings(data.meetings))
      .catch((err) => {
        if (handleAuthError(err)) return;
        setLoadError(err instanceof ApiError ? err.message : "Failed to load meetings.");
      });
  }, [handleAuthError]);

  useEffect(() => {
    loadMeetings();
  }, [loadMeetings]);

  useEffect(() => {
    if (!meetings || !meetings.some(isActiveMeeting)) return;
    const id = setInterval(loadMeetings, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [meetings, loadMeetings]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) return;
    // datetime-local has no timezone; the Date constructor reads it as local
    // time, and toISOString() turns that into the UTC instant the API wants.
    const startTime = when === "later" && startAt ? new Date(startAt) : null;
    if (when === "later" && (!startTime || Number.isNaN(startTime.getTime()))) {
      setSubmitError("Pick a date and time for the meeting.");
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    setNeedsFunds(false);
    try {
      await apiFetch("/api/meetings", {
        method: "POST",
        body: JSON.stringify({
          url: trimmed,
          title: title.trim() || undefined,
          bot_name: botName.trim() || undefined,
          start_time: startTime ? startTime.toISOString() : undefined,
        }),
      });
      try {
        window.localStorage.setItem(BOT_NAME_KEY, botName.trim());
      } catch {
        // Storage can be blocked; the name just won't be remembered.
      }
      setUrl("");
      setTitle("");
      setWhen("now");
      setStartAt("");
      loadMeetings();
    } catch (err) {
      if (handleAuthError(err)) return;
      setSubmitError(err instanceof ApiError ? err.message : "Couldn't send the notetaker.");
      setNeedsFunds(err instanceof ApiError && err.status === 402);
    } finally {
      setSubmitting(false);
    }
  }

  async function runAction(meeting: Meeting, request: () => Promise<unknown>, fallback: string) {
    setBusyId(meeting.id);
    setActionError(null);
    try {
      await request();
      loadMeetings();
    } catch (err) {
      if (handleAuthError(err)) return;
      setActionError(err instanceof ApiError ? err.message : fallback);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <form onSubmit={handleSubmit} className="mt-8 w-full rounded-lg border border-line bg-paper p-6 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-stretch">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://zoom.us/j/... or https://meet.google.com/..."
            required
            className="flex-1 rounded-md border border-line bg-paper px-3 py-2 text-sm text-ink outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft"
          />
          <input
            type="text"
            value={title}
            maxLength={200}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title (optional)"
            className="rounded-md border border-line bg-paper px-3 py-2 text-sm text-ink outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft sm:w-56"
          />
          <input
            type="text"
            value={botName}
            maxLength={50}
            onChange={(e) => setBotName(e.target.value)}
            placeholder={`Bot name (${DEFAULT_BOT_NAME})`}
            aria-label="Name of the notetaker bot"
            className="rounded-md border border-line bg-paper px-3 py-2 text-sm text-ink outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft sm:w-56"
          />
          <Button type="submit" disabled={submitting || !url.trim()} className="shrink-0 justify-center">
            {submitting ? "Sending..." : when === "later" ? "Schedule notetaker" : "Send notetaker"}
          </Button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-ink">
          <label className="flex items-center gap-2">
            <input type="radio" name="when" checked={when === "now"} onChange={() => setWhen("now")} />
            Join now
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" name="when" checked={when === "later"} onChange={() => setWhen("later")} />
            Schedule for later
          </label>
          {when === "later" && (
            <input
              type="datetime-local"
              value={startAt}
              onChange={(e) => setStartAt(e.target.value)}
              required
              aria-label="Meeting start time"
              className="rounded-md border border-line bg-paper px-3 py-1.5 text-sm text-ink outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft"
            />
          )}
        </div>
        <p className="mt-3 text-xs text-ink-soft">
          $1.00 per hour of meeting, charged when it ends.
          {when === "later" && " The notetaker joins at the start time you pick (in your local time)."} The bot appears as a participant named &ldquo;{botName.trim() || DEFAULT_BOT_NAME}&rdquo;
          &mdash; pick a name attendees will recognise as a notetaker &mdash; and you may need to admit it from the waiting room. You&apos;re responsible for telling
          attendees the meeting is being recorded.
        </p>
        {submitError && (
          <p className="mt-3 text-sm text-status-error">
            {submitError}
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
      </form>

      <div className="mt-10">
        <h2 className="text-sm font-semibold text-ink">Your meetings</h2>
        {loadError && <p className="mt-2 text-sm text-status-error">{loadError}</p>}
        {actionError && <p className="mt-2 text-sm text-status-error">{actionError}</p>}

        {meetings && meetings.length === 0 && (
          <Card className="mt-2 p-6 text-sm text-ink-soft">No meetings yet -- paste a link above to get started.</Card>
        )}

        {meetings && meetings.length > 0 && (
          <ul className="mt-2 divide-y divide-line overflow-hidden rounded-lg border border-line bg-paper shadow-sm">
            {meetings.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink">{m.title ?? "Meeting"}</p>
                  <p className="text-xs text-ink-soft">
                    {PLATFORM_LABELS[m.platform]} &middot;{" "}
                    {m.status === "scheduled" && m.scheduled_for
                      ? `Joins ${new Date(m.scheduled_for).toLocaleString()}`
                      : new Date(m.created_at).toLocaleString()}
                  </p>
                  {m.error && (m.status === "failed" || m.status === "awaiting_payment") && (
                    <p className="mt-0.5 max-w-md text-xs text-status-error">{m.error}</p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <span className={`text-sm font-medium ${STATUS_COLORS[m.status]}`}>
                    {MEETING_STATUS_LABELS[m.status]}
                  </span>
                  {m.job_id && (
                    <Link href={`/dashboard/jobs/${m.job_id}`} className="text-sm text-accent hover:underline">
                      View notes →
                    </Link>
                  )}
                  {(m.status === "scheduled" || m.status === "joining" || m.status === "recording") && (
                    <button
                      onClick={() =>
                        runAction(m, () => apiFetch(`/api/meetings/${m.id}`, { method: "DELETE" }), "Couldn't stop the notetaker.")
                      }
                      disabled={busyId === m.id}
                      className="text-sm text-ink-soft hover:text-status-error hover:underline disabled:cursor-default disabled:opacity-50"
                    >
                      {busyId === m.id ? "Stopping..." : m.status === "recording" ? "Stop" : "Cancel"}
                    </button>
                  )}
                  {!m.job_id && (m.status === "awaiting_payment" || m.status === "failed") && (
                    <>
                      {m.status === "awaiting_payment" && (
                        <Link href="/settings/billing" className="text-sm text-accent hover:underline">
                          Add funds
                        </Link>
                      )}
                      <button
                        onClick={() =>
                          runAction(m, () => apiFetch(`/api/meetings/${m.id}/process`, { method: "POST" }), "Couldn't process the meeting.")
                        }
                        disabled={busyId === m.id}
                        className="text-sm text-ink hover:text-accent hover:underline disabled:cursor-default disabled:opacity-50"
                      >
                        {busyId === m.id ? "Processing..." : "Process"}
                      </button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
