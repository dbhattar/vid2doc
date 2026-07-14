export type JobStatus = "queued" | "processing" | "done" | "failed";
export type JobType = "video" | "audio";

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
  retention_expired?: boolean;
  error?: string;
};

// Video: frame capture + composed document (POST /api/convert_to_doc).
// Audio: verbatim speaker-tagged transcript only (POST /api/transcribe_audio).
export const VIDEO_EXTENSIONS = [".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"];
export const AUDIO_EXTENSIONS = [".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"];
export const ACCEPTED_UPLOAD_EXTENSIONS = [...VIDEO_EXTENSIONS, ...AUDIO_EXTENSIONS].join(",");

/** Which upload endpoint a file should go to, based on its extension --
 * null for anything neither list recognizes. */
export function jobTypeForFilename(filename: string): JobType | null {
  const dot = filename.lastIndexOf(".");
  if (dot === -1) return null;
  const ext = filename.slice(dot).toLowerCase();
  if (VIDEO_EXTENSIONS.includes(ext)) return "video";
  if (AUDIO_EXTENSIONS.includes(ext)) return "audio";
  return null;
}

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
