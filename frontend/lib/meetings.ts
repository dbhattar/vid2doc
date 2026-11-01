export type MeetingStatus = "joining" | "recording" | "processing" | "done" | "failed" | "cancelled" | "awaiting_payment";
export type MeetingPlatform = "zoom" | "meet" | "teams";

/** One row of GET /api/meetings -- see backend/app/routes/meetings.py. `done`
 * means the recording was captured and handed to `job_id`, not that the job
 * itself has finished. */
export type Meeting = {
  id: string;
  platform: MeetingPlatform;
  title: string | null;
  status: MeetingStatus;
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
  return m.status === "joining" || m.status === "recording" || m.status === "processing";
}
