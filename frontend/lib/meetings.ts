export type MeetingStatus = "scheduled" | "joining" | "recording" | "processing" | "done" | "failed" | "cancelled" | "awaiting_payment";
export type MeetingPlatform = "zoom" | "meet" | "teams";

/** One row of GET /api/meetings -- see backend/app/routes/meetings.py. `done`
 * means the recording was captured and handed to `job_id`, not that the job
 * itself has finished. */
export type Meeting = {
  id: string;
  platform: MeetingPlatform;
  title: string | null;
  /** ISO time the bot is due to join, for a meeting scheduled ahead. */
  scheduled_for: string | null;
  status: MeetingStatus;
  /** Planned length in minutes, if the user gave one. */
  duration_minutes: number | null;
  /** Email the owner when the notes are ready. */
  notify_when_ready: boolean;
  job_id: string | null;
  error: string | null;
  created_at: string;
};

export const PLATFORM_LABELS: Record<MeetingPlatform, string> = {
  zoom: "Zoom",
  meet: "Google Meet",
  teams: "Microsoft Teams",
};

export const MEETING_STATUS_LABELS: Record<MeetingStatus, string> = {
  scheduled: "Scheduled",
  joining: "Joining...",
  recording: "Recording",
  processing: "Processing",
  done: "Captured",
  failed: "Failed",
  cancelled: "Cancelled",
  awaiting_payment: "Needs funds",
};

/** Statuses where the meeting is still in flight and worth polling. */
export function isActiveMeeting(m: Meeting): boolean {
  return m.status === "scheduled" || m.status === "joining" || m.status === "recording" || m.status === "processing";
}

/** Local-time calendar day key, "YYYY-MM-DD" -- what the calendar groups by. */
export function dayKey(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The day a meeting sits on: when it is due to join, else when it was created. */
export function meetingDate(m: Meeting): Date {
  return new Date(m.scheduled_for ?? m.created_at);
}
