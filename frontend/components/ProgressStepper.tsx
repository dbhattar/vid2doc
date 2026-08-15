"use client";

import { AlertIcon, CheckIcon, CloseIcon } from "@/components/icons";
import { getStageStatuses, type StageStatus } from "@/lib/jobStages";
import { formatTimestamp, type Job } from "@/lib/jobs";
import { useElapsedSeconds } from "@/lib/useElapsedSeconds";

function Indicator({ status }: { status: StageStatus }) {
  if (status === "done") {
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center bg-status-success text-paper">
        <CheckIcon className="h-3.5 w-3.5" />
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center text-status-error">
        <AlertIcon className="h-5 w-5" />
      </span>
    );
  }
  if (status === "cancelled") {
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center text-ink-soft">
        <CloseIcon className="h-4 w-4" />
      </span>
    );
  }
  if (status === "current") {
    return <span className="h-2.5 w-2.5 shrink-0 bg-status-warning stage-pulse" />;
  }
  if (status === "awaiting-input") {
    // Deliberately not animated -- a pulse reads as "the system is working,"
    // which is wrong when it's actually idle waiting on the user.
    return <span className="h-2.5 w-2.5 shrink-0 bg-accent" />;
  }
  return <span className="h-2.5 w-2.5 shrink-0 border border-line" />;
}

const LABEL_CLASSES: Record<StageStatus, string> = {
  done: "text-ink-soft line-through decoration-1",
  current: "text-ink font-semibold",
  "awaiting-input": "text-accent font-semibold",
  failed: "text-status-error font-semibold",
  cancelled: "text-ink-soft font-semibold",
  pending: "text-ink-soft",
};

/** Full vertical stage checklist for the job detail page -- same underlying
 * stage data as ProgressBar, but every row visible with flavor text and a
 * live elapsed-time ticker on whichever row is actually current. */
export default function ProgressStepper({ job, className = "" }: { job: Job; className?: string }) {
  const statuses = getStageStatuses(job);
  const elapsed = useElapsedSeconds(job.updated_at, job.status === "processing");

  return (
    <ol className={`space-y-3 ${className}`}>
      {statuses.map(({ stage, status }) => {
        const isActiveRow =
          status === "current" || status === "awaiting-input" || status === "failed" || status === "cancelled";
        return (
          <li
            key={stage.key}
            className={`flex items-start gap-3 ${
              status === "awaiting-input" ? "border-2 border-accent bg-accent-soft p-3" : ""
            } ${status === "failed" ? "bg-status-error-soft p-3" : ""} ${
              status === "cancelled" ? "bg-paper-shade p-3" : ""
            }`}
          >
            <Indicator status={status} />
            <div className="min-w-0">
              <p className={`text-sm ${LABEL_CLASSES[status]}`}>
                {stage.label}
                {status === "current" && job.status === "processing" && (
                  <span className="ml-2 font-mono text-xs text-ink-soft">{formatTimestamp(elapsed)}</span>
                )}
              </p>
              {isActiveRow && (
                <p key={stage.key} className="stage-flavor-enter mt-0.5 text-sm text-ink-soft">
                  {status === "cancelled" ? "You cancelled this job here." : stage.flavor}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
