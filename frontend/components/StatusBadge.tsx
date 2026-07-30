import type { Job } from "@/lib/jobs";

// 1:1 semantic mapping onto the formal status tokens (kept separate from
// --accent, which is also red, so a failed badge never reads as a CTA).
const STATUS_STYLES: Record<Job["status"], string> = {
  queued: "text-status-info",
  processing: "text-status-warning",
  done: "text-status-success",
  failed: "text-status-error",
};

export default function StatusBadge({ job }: { job: Job }) {
  const label = job.status === "processing" && job.progress_stage ? job.progress_stage.replaceAll("_", " ") : job.status;
  return (
    <span className={`font-mono text-xs font-semibold uppercase tracking-wide ${STATUS_STYLES[job.status]}`}>
      {label}
    </span>
  );
}
