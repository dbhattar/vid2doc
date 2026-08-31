import { getStageStatuses } from "@/lib/jobStages";
import type { Job } from "@/lib/jobs";

/** Compact segmented progress bar for list views (JobRow) -- rounded pill
 * segments matching the app's soft/rounded aesthetic. Flavor text surfaces
 * as a native title tooltip rather than a second visible line: a dense list
 * row shouldn't grow a permanent line of prose per processing job -- the
 * full always-visible flavor treatment lives in ProgressStepper instead. */
export default function ProgressBar({ job, className = "" }: { job: Job; className?: string }) {
  const statuses = getStageStatuses(job);
  const current = statuses.find((s) => s.status === "current" || s.status === "awaiting-input");

  return (
    <div className={className}>
      <div className="flex gap-0.5" title={current?.stage.flavor}>
        {statuses.map(({ stage, status }) => (
          <div
            key={stage.key}
            className={`h-1.5 flex-1 rounded-full ${
              status === "done" || status === "current" || status === "awaiting-input"
                ? "bg-status-warning"
                : status === "failed"
                  ? "bg-status-error"
                  : "bg-line"
            } ${status === "current" ? "stage-pulse" : ""}`}
          />
        ))}
      </div>
      {current && (
        <p className="mt-1 font-sans text-xs font-semibold text-status-warning">
          {current.stage.label}
        </p>
      )}
    </div>
  );
}
