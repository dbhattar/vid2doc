"use client";

import Link from "next/link";

import { MEETING_STATUS_LABELS, PLATFORM_LABELS, type Meeting } from "@/lib/meetings";

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

export { STATUS_COLORS };

/** One meeting with its actions -- shared by the calendar's day panel and the list view. */
export default function MeetingRow({
  meeting: m,
  busy,
  onCancel,
  onProcess,
  onToggleNotify,
}: {
  meeting: Meeting;
  busy: boolean;
  onCancel: (m: Meeting) => void;
  onProcess: (m: Meeting) => void;
  onToggleNotify: (m: Meeting, value: boolean) => void;
}) {
  // A failed, cancelled or unfunded meeting has no notes coming to be told about.
  const showNotify = m.status !== "failed" && m.status !== "cancelled" && m.status !== "awaiting_payment";
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-ink">{m.title ?? "Meeting"}</p>
        <p className="text-xs text-ink-soft">
          {PLATFORM_LABELS[m.platform]} &middot;{" "}
          {m.status === "scheduled" && m.scheduled_for
            ? `Joins ${new Date(m.scheduled_for).toLocaleString()}`
            : new Date(m.scheduled_for ?? m.created_at).toLocaleString()}
          {m.duration_minutes ? ` \u00b7 ${m.duration_minutes} min` : ""}
        </p>
        {m.error && (m.status === "failed" || m.status === "awaiting_payment") && (
          <p className="mt-0.5 max-w-md text-xs text-status-error">{m.error}</p>
        )}
        {showNotify && (
          <label className="mt-1 flex items-center gap-1.5 text-xs text-ink-soft">
            <input
              type="checkbox"
              checked={m.notify_when_ready}
              onChange={(e) => onToggleNotify(m, e.target.checked)}
              disabled={busy}
            />
            Email me when the notes are ready
          </label>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className={`text-sm font-medium ${STATUS_COLORS[m.status]}`}>{MEETING_STATUS_LABELS[m.status]}</span>
        {m.job_id && (
          <Link href={`/dashboard/jobs/${m.job_id}`} className="text-sm text-accent hover:underline">
            View notes →
          </Link>
        )}
        {(m.status === "scheduled" || m.status === "joining" || m.status === "recording") && (
          <button
            onClick={() => onCancel(m)}
            disabled={busy}
            className="text-sm text-ink-soft hover:text-status-error hover:underline disabled:cursor-default disabled:opacity-50"
          >
            {busy ? "Stopping..." : m.status === "recording" ? "Stop" : "Cancel"}
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
              onClick={() => onProcess(m)}
              disabled={busy}
              className="text-sm text-ink hover:text-accent hover:underline disabled:cursor-default disabled:opacity-50"
            >
              {busy ? "Processing..." : "Process"}
            </button>
          </>
        )}
      </div>
    </li>
  );
}
