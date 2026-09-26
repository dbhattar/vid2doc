import Link from "next/link";

import { ClapperboardIcon, FeedbackIcon, MicrophoneIcon, VideoCameraIcon, WalletIcon } from "@/components/icons";
import { STATUS_LABELS, STATUS_STYLES } from "@/components/StatusBadge";
import { formatCents } from "@/lib/billing";
import type { JobStatus, JobType } from "@/lib/jobs";

type BaseEvent = {
  id: string;
  user_id: string;
  email: string;
  display_name: string | null;
  created_at: string;
};

export type AdminActivityEvent =
  | (BaseEvent & { type: "job"; job_id: string; job_type: JobType; status: JobStatus; title: string | null })
  | (BaseEvent & {
      type: "wallet";
      entry_type: "topup" | "usage_charge" | "usage_refund" | "signup_bonus";
      amount_cents: number;
      // Only set for usage_charge/usage_refund -- a topup/signup_bonus has no related job.
      // job_id/job_type can still be null even then if the related job no longer exists
      // (related_job_id is deliberately not a DB foreign key, see backend/app/models.py).
      job_id: string | null;
      job_type: JobType | null;
      job_title: string | null;
    })
  | (BaseEvent & { type: "feedback"; message: string });

const JOB_TYPE_ICONS: Record<JobType, (props: { className?: string }) => React.ReactElement> = {
  video: VideoCameraIcon,
  audio: MicrophoneIcon,
  video_gen: ClapperboardIcon,
};

const JOB_TYPE_LABELS: Record<JobType, string> = {
  video: "a video",
  audio: "an audio",
  video_gen: "a video gen",
};

function eventIcon(event: AdminActivityEvent) {
  if (event.type === "job") return JOB_TYPE_ICONS[event.job_type];
  if (event.type === "wallet") return WalletIcon;
  return FeedbackIcon;
}

function eventText(event: AdminActivityEvent): React.ReactNode {
  if (event.type === "job") {
    return (
      <>
        Submitted {JOB_TYPE_LABELS[event.job_type]} job{event.title && <>: &ldquo;{event.title}&rdquo;</>}
      </>
    );
  }
  if (event.type === "wallet") {
    const amount = formatCents(Math.abs(event.amount_cents));
    if (event.entry_type === "topup") return `Added ${amount} to wallet`;
    if (event.entry_type === "signup_bonus") return `Received ${amount} signup bonus`;
    // usage_charge/usage_refund: job_type is null if the related job no longer exists
    // (related_job_id isn't a DB foreign key, see backend/app/models.py) -- falls back to
    // the old job-agnostic phrasing only in that edge case.
    const jobDescription = event.job_type ? (
      <>
        {JOB_TYPE_LABELS[event.job_type]} job{event.job_title && <>: &ldquo;{event.job_title}&rdquo;</>}
      </>
    ) : (
      "a job"
    );
    if (event.entry_type === "usage_refund") return <>Refunded {amount} for {jobDescription}</>;
    return <>Charged {amount} for {jobDescription}</>;
  }
  return (
    <>
      Left feedback: <span className="text-ink-soft">&ldquo;{event.message.slice(0, 120)}{event.message.length > 120 ? "…" : ""}&rdquo;</span>
    </>
  );
}

/** One row per synthesized activity event (job submitted, wallet ledger
 * entry, feedback left) -- shared between the admin dashboard's global feed
 * and the per-user drill-down page. `showUser` is off on the drill-down
 * page since every row there is already scoped to one user. */
export default function AdminActivityFeed({
  events,
  showUser = true,
}: {
  events: AdminActivityEvent[];
  showUser?: boolean;
}) {
  if (events.length === 0) {
    return <p className="mt-2 text-sm text-ink-soft">No activity yet.</p>;
  }

  return (
    <ul className="mt-2 divide-y divide-line overflow-hidden rounded-lg border border-line bg-paper shadow-sm">
      {events.map((event) => {
        const Icon = eventIcon(event);
        return (
          <li key={event.id} className="flex items-start gap-3 px-4 py-3">
            <Icon className="mt-0.5 h-4 w-4 shrink-0 text-ink-soft" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-3">
                {showUser ? (
                  <Link href={`/admin/users/${event.user_id}`} className="truncate text-sm font-medium text-ink hover:underline">
                    {event.display_name || event.email}
                  </Link>
                ) : (
                  <span />
                )}
                <span className="shrink-0 text-xs text-ink-soft">{new Date(event.created_at).toLocaleString()}</span>
              </div>
              <p className="mt-0.5 text-sm text-ink-soft">
                {eventText(event)}
                {event.type === "job" && (
                  <span className={`ml-2 text-xs font-semibold ${STATUS_STYLES[event.status]}`}>
                    {STATUS_LABELS[event.status] ?? event.status}
                  </span>
                )}
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
