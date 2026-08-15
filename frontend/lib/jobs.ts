export type JobStatus = "queued" | "processing" | "awaiting_review" | "done" | "failed" | "cancelled";
export type JobType = "video" | "audio" | "video_gen";

export type Job = {
  job_id: string;
  status: JobStatus;
  progress_stage: string | null;
  job_type: JobType;
  title: string | null;
  created_at: string;
  updated_at: string;
  duration_seconds: number | null;
  billed_cents: number;
  document_url?: string;
  document_bundle_url?: string;
  document_docx_url?: string;
  document_pdf_url?: string;
  document_transcript_json_url?: string;
  // job_type === "video_gen" only, once status === "done" -- see
  // backend/app/routes/video_output.py.
  video_url?: string;
  thumbnail_url?: string;
  retention_expired?: boolean;
  error?: string;
  share_url?: string | null;
};

/** Shape of GET /api/share/{token} -- the anonymous, read-only counterpart
 * to Job for a shared document. Deliberately excludes anything owner-only:
 * no status/billed_cents/error, no job_id (the token itself is the only
 * identifier a visitor needs). */
export type PublicJobView = {
  title: string | null;
  job_type: JobType;
  duration_seconds: number | null;
  created_at: string;
  document_url?: string;
  document_bundle_url?: string;
  document_docx_url?: string;
  document_pdf_url?: string;
  document_transcript_json_url?: string;
};

/** One candidate frame surfaced during a video job's "awaiting_review" pause
 * -- see backend/app/routes/review.py. `content_type` is only present on
 * `kind: "image"` items ("table" items are their own content type). No
 * caption yet at this point -- captioning is deferred until after the user
 * submits which frames to keep (see pipeline.resume_after_review), so it's
 * never spent on a frame the user ends up skipping. */
export type ReviewItem = {
  id: number;
  kind: "image" | "table";
  timestamp: number;
  content_type?: string;
  headers?: string[];
  rows?: string[][];
  included: boolean;
};

/** One scene surfaced during a video_gen job's "awaiting_review" pause --
 * see backend/app/routes/scene_review.py. `candidate_count` stock media
 * candidates were downloaded for this scene (never the raw file paths --
 * the frontend fetches each one by index via the dedicated media route). */
export type SceneReviewItem = {
  id: number;
  start_ts: number;
  end_ts: number;
  headline: string;
  media_kind: "video" | "photo" | "none";
  candidate_count: number;
  chosen_index: number;
};

export type TranscriptSegment = { speaker: string; text: string; start_ts: number; end_ts: number };

export type TranscriptData = {
  speakers: string[];
  speaker_names: Record<string, string>;
  summary: string;
  segments: TranscriptSegment[];
};

// Video: frame capture + composed document (POST /api/convert_to_doc).
// Audio: verbatim speaker-tagged transcript only (POST /api/transcribe_audio).
export const VIDEO_EXTENSIONS = [".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"];
export const AUDIO_EXTENSIONS = [".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"];

export const ACTIVE_JOB_STATUSES = new Set<JobStatus>(["queued", "processing"]);

export function isActiveJob(job: Job): boolean {
  return ACTIVE_JOB_STATUSES.has(job.status);
}

/** Jobs created before the title feature (or where filename/LLM titling
 * both came up empty) have no title -- fall back to the timestamp so every
 * row still shows something meaningful. */
export function displayTitle(job: Job): string {
  return job.title?.trim() || new Date(job.created_at).toLocaleString();
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

/** How long a finished job actually took, submission to completion --
 * distinct from duration_seconds (the length of the video/audio itself).
 * Only meaningful once a job has stopped changing (done/failed). */
export function formatElapsed(job: Job): string {
  const elapsedSeconds = (new Date(job.updated_at).getTime() - new Date(job.created_at).getTime()) / 1000;
  if (!Number.isFinite(elapsedSeconds) || elapsedSeconds < 0) return "—";
  if (elapsedSeconds < 60) return `${Math.round(elapsedSeconds)}s`;
  const totalMinutes = Math.round(elapsedSeconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

/** Mirrors pipeline.py's _format_timestamp (h:mm:ss / m:ss) -- used for
 * per-segment timestamps in the transcript viewer. */
export function formatTimestamp(seconds: number): string {
  const totalSeconds = Math.floor(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;
  const paddedSecs = secs.toString().padStart(2, "0");
  return hours > 0 ? `${hours}:${minutes.toString().padStart(2, "0")}:${paddedSecs}` : `${minutes}:${paddedSecs}`;
}

export function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  return `${exponent === 0 ? value : value.toFixed(1)} ${units[exponent]}`;
}
