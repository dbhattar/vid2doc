"use client";

import Link from "next/link";

import StatusBadge from "@/components/StatusBadge";
import { displayTitle, formatDuration, type Job } from "@/lib/jobs";

/** One row in an "in progress" job list -- shared by the video and audio
 * dashboards, since a job's row (title, status, retry/delete/review
 * affordances) doesn't differ by job type, only the page around it does. */
export default function JobRow({
  job,
  onRetry,
  onDelete,
  retryingJobId,
  deletingJobId,
}: {
  job: Job;
  onRetry: (jobId: string) => void;
  onDelete: (job: Job) => void;
  retryingJobId: string | null;
  deletingJobId: string | null;
}) {
  return (
    <li className="flex items-center justify-between px-4 py-3">
      <div className="min-w-0">
        <Link
          href={`/dashboard/jobs/${job.job_id}`}
          className="block truncate text-sm font-medium text-ink hover:text-accent hover:underline"
        >
          {displayTitle(job)}
        </Link>
        <p className="text-xs text-ink-soft">
          {new Date(job.created_at).toLocaleDateString()} &middot; {formatDuration(job.duration_seconds)}
        </p>
        {job.status === "failed" && job.error && (
          <p className="mt-0.5 max-w-sm truncate text-xs text-status-error" title={job.error}>
            {job.error}
          </p>
        )}
      </div>
      <div className="flex items-center gap-3">
        <StatusBadge job={job} />
        {job.status === "awaiting_review" && (
          <Link href={`/dashboard/jobs/${job.job_id}`} className="text-sm text-accent hover:underline">
            {job.job_type === "video_gen" ? "Review scenes →" : "Review frames →"}
          </Link>
        )}
        {(job.status === "failed" || job.status === "awaiting_review") && (
          <>
            {job.status === "failed" && (
              <button
                onClick={() => onRetry(job.job_id)}
                disabled={retryingJobId === job.job_id || deletingJobId === job.job_id}
                className="text-sm text-ink hover:text-accent hover:underline disabled:cursor-default disabled:opacity-50"
              >
                {retryingJobId === job.job_id ? "Retrying..." : "Retry"}
              </button>
            )}
            <button
              onClick={() => onDelete(job)}
              disabled={retryingJobId === job.job_id || deletingJobId === job.job_id}
              className="text-sm text-status-error hover:underline disabled:cursor-default disabled:opacity-50"
            >
              {deletingJobId === job.job_id ? "Deleting..." : "Delete"}
            </button>
          </>
        )}
      </div>
    </li>
  );
}
