"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Button from "@/components/Button";
import Card from "@/components/Card";
import MeetingRow from "@/components/MeetingRow";
import MeetingDayPanel from "@/components/MeetingDayPanel";
import MeetingsCalendar from "@/components/MeetingsCalendar";
import MeetingsRequestAccess, { type MeetingsRequestStatus } from "@/components/MeetingsRequestAccess";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { dayKey, isActiveMeeting, type Meeting } from "@/lib/meetings";
import type { Preferences } from "@/lib/preferences";

const POLL_INTERVAL_MS = 5000;

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
    <div className="flex min-h-full w-full flex-col px-6 py-6">
      <p className="font-sans text-xs font-semibold text-accent">
        Meetings → Notes{" "}
        <span className="ml-1 rounded-full border border-line px-2 py-0.5 text-[10px] font-semibold uppercase text-ink-soft">
          Preview
        </span>
      </p>
      <h1 className="mt-1 font-display text-2xl font-bold tracking-tight text-ink">Meetings</h1>
      <p className="mt-1 max-w-2xl text-sm text-ink-soft">
        Pick a day, add the link, start time and length, and a notetaker joins, records, and sends you a speaker-labelled
        transcript with a summary, decisions, and action items.
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
  const [view, setView] = useState<"calendar" | "list">("calendar");
  const [month, setMonth] = useState(() => new Date());
  const [openDay, setOpenDay] = useState<string | null>(null);
  const [defaults, setDefaults] = useState({ botName: "", notify: true });
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
    // The calendar asks for the visible month (local midnight to midnight, as
    // UTC instants); the list view just takes the most recent meetings.
    let path = "/api/meetings";
    if (view === "calendar") {
      const start = new Date(month.getFullYear(), month.getMonth(), 1);
      const end = new Date(month.getFullYear(), month.getMonth() + 1, 1);
      path += `?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}`;
    }
    apiFetch<{ meetings: Meeting[] }>(path)
      .then((data) => setMeetings(data.meetings))
      .catch((err) => {
        if (handleAuthError(err)) return;
        setLoadError(err instanceof ApiError ? err.message : "Failed to load meetings.");
      });
  }, [handleAuthError, view, month]);

  useEffect(() => {
    loadMeetings();
  }, [loadMeetings]);

  // The bot name and notify box start from the defaults in Settings; the form
  // can still change them for one meeting.
  useEffect(() => {
    apiFetch<Preferences>("/api/me/preferences")
      .then((p) => setDefaults({ botName: p.default_bot_name, notify: p.notify_meeting_notes }))
      .catch(() => {
        // Defaults are a convenience; the form works without them.
      });
  }, []);

  useEffect(() => {
    if (!meetings || !meetings.some(isActiveMeeting)) return;
    const id = setInterval(loadMeetings, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [meetings, loadMeetings]);

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

  const cancelMeeting = (m: Meeting) =>
    runAction(m, () => apiFetch(`/api/meetings/${m.id}`, { method: "DELETE" }), "Couldn't stop the notetaker.");
  const processMeeting = (m: Meeting) =>
    runAction(m, () => apiFetch(`/api/meetings/${m.id}/process`, { method: "POST" }), "Couldn't process the meeting.");
  const toggleNotify = (m: Meeting, value: boolean) =>
    runAction(
      m,
      () => apiFetch(`/api/meetings/${m.id}`, { method: "PATCH", body: JSON.stringify({ notify_when_ready: value }) }),
      "Couldn't update the notification setting.",
    );

  return (
    <div className="mt-4 flex flex-1 flex-col">
      <div className="flex items-center justify-between gap-3">
        <div className="flex overflow-hidden rounded-md border border-line text-sm" role="group" aria-label="View">
          {(["calendar", "list"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              aria-pressed={view === v}
              className={`px-3 py-1 capitalize ${view === v ? "bg-accent-soft font-semibold text-accent" : "text-ink-soft hover:bg-paper-shade"}`}
            >
              {v}
            </button>
          ))}
        </div>
        <Button onClick={() => setOpenDay(dayKey(new Date()))}>New meeting</Button>
      </div>
      {loadError && <p className="mt-2 text-sm text-status-error">{loadError}</p>}
      {actionError && <p className="mt-2 text-sm text-status-error">{actionError}</p>}

      {view === "calendar" && (
        <div className="mt-3 flex flex-1 flex-col">
          <MeetingsCalendar
            month={month}
            onMonthChange={setMonth}
            meetings={meetings ?? []}
            selectedDay={openDay}
            onOpenDay={setOpenDay}
          />
        </div>
      )}

      {view === "list" && meetings && meetings.length === 0 && (
        <Card className="mt-3 p-6 text-sm text-ink-soft">No meetings yet -- click New meeting to add one.</Card>
      )}
      {view === "list" && meetings && meetings.length > 0 && (
        <ul className="mt-3 divide-y divide-line overflow-hidden rounded-lg border border-line bg-paper shadow-sm">
          {meetings.map((m) => (
            <MeetingRow
              key={m.id}
              meeting={m}
              busy={busyId === m.id}
              onCancel={cancelMeeting}
              onProcess={processMeeting}
              onToggleNotify={toggleNotify}
            />
          ))}
        </ul>
      )}

      {openDay && (
        <MeetingDayPanel
          // Remount per day so the form starts fresh (and the time default fits that day).
          key={openDay}
          day={openDay}
          meetings={meetings ?? []}
          defaults={defaults}
          busyId={busyId}
          onClose={() => setOpenDay(null)}
          onCreated={() => {
            loadMeetings();
          }}
          onCancel={cancelMeeting}
          onProcess={processMeeting}
          onToggleNotify={toggleNotify}
          onAuthError={handleAuthError}
        />
      )}
    </div>
  );
}
