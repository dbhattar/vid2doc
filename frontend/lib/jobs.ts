export type JobStatus = "queued" | "processing" | "done" | "failed";

export type Job = {
  job_id: string;
  status: JobStatus;
  progress_stage: string | null;
  created_at: string;
  duration_seconds: number | null;
  document_url?: string;
  document_bundle_url?: string;
  document_docx_url?: string;
  document_pdf_url?: string;
  error?: string;
};

export const ACTIVE_JOB_STATUSES = new Set<JobStatus>(["queued", "processing"]);

export function isActiveJob(job: Job): boolean {
  return ACTIVE_JOB_STATUSES.has(job.status);
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}
