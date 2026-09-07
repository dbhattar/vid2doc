"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { ClapperboardIcon, MicrophoneIcon, VideoCameraIcon } from "@/components/icons";
import Pagination from "@/components/Pagination";
import { STATUS_LABELS, STATUS_STYLES } from "@/components/StatusBadge";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { formatCents } from "@/lib/billing";
import { formatBytes, formatDuration, formatElapsed } from "@/lib/jobs";
import { getStagesForJobType } from "@/lib/jobStages";

const PAGE_SIZE = 20;

type AdminJob = {
  id: string;
  user_id: string | null;
  email: string | null;
  display_name: string | null;
  status: "queued" | "processing" | "awaiting_review" | "done" | "failed" | "cancelled";
  progress_stage: string | null;
  job_type: "video" | "audio" | "video_gen";
  title: string | null;
  source_url: string | null;
  source_size_bytes: number | null;
  duration_seconds: number | null;
  billed_cents: number;
  extract_frames: boolean;
  aspect_ratio: string;
  video_template: string | null;
  stock_media_provider: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

const JOB_TYPE_ICONS = { video: VideoCameraIcon, audio: MicrophoneIcon, video_gen: ClapperboardIcon };
const JOB_TYPE_LABELS = { video: "Video", audio: "Audio", video_gen: "Video Gen" };

function stageLabel(job: AdminJob): string | null {
  if (!job.progress_stage) return null;
  const stage = getStagesForJobType(job.job_type).find((s) => s.key === job.progress_stage);
  return stage?.label ?? job.progress_stage;
}

/** Narrows the raw `?job_type=` query value to a real job type, or null for
 * anything else (missing, or an unrecognized value) -- falls back to
 * showing every job rather than erroring on a bad/stale link. */
function parseJobTypeFilter(raw: string | null): keyof typeof JOB_TYPE_LABELS | null {
  return raw === "video" || raw === "audio" || raw === "video_gen" ? raw : null;
}

function AdminJobsPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const jobTypeFilter = parseJobTypeFilter(searchParams.get("job_type"));
  const [jobList, setJobList] = useState<AdminJob[] | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);

  // A tile linking here with a different job_type doesn't remount this
  // component (same route) -- reset back to page 1 so switching filters
  // never leaves the user stranded on a now out-of-range page.
  useEffect(() => {
    setPage(1);
  }, [jobTypeFilter]);

  useEffect(() => {
    const offset = (page - 1) * PAGE_SIZE;
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (jobTypeFilter) params.set("job_type", jobTypeFilter);
    apiFetch<{ jobs: AdminJob[]; total: number }>(`/api/admin/jobs?${params}`)
      .then((data) => {
        setJobList(data.jobs);
        setTotal(data.total);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/admin");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Failed to load jobs.");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, jobTypeFilter]);

  return (
    <div className="w-full px-6 py-10">
      <Link href="/admin" className="text-sm text-ink-soft hover:underline">
        &larr; Back to Admin
      </Link>

      <h1 className="mt-2 font-display text-2xl font-bold tracking-tight text-ink">All jobs</h1>
      <p className="mt-1 text-sm text-ink-soft">Every job submitted across every user.</p>

      {jobTypeFilter && (
        <p className="mt-2 text-sm text-ink-soft">
          Filtering to <strong className="text-ink">{JOB_TYPE_LABELS[jobTypeFilter]}</strong> jobs &middot;{" "}
          <Link href="/admin/jobs" className="text-accent hover:underline">
            Clear filter
          </Link>
        </p>
      )}

      {error && <p className="mt-4 text-sm text-status-error">{error}</p>}

      {jobList === null ? (
        <p className="mt-6 text-sm text-ink-soft">Loading...</p>
      ) : jobList.length === 0 ? (
        <p className="mt-6 text-sm text-ink-soft">No jobs yet.</p>
      ) : (
        <>
          <div className="mt-6 overflow-x-auto rounded-lg border border-line bg-paper shadow-sm">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-line font-sans text-xs text-ink-soft">
                  <th className="px-4 py-3 font-semibold">User</th>
                  <th className="px-4 py-3 font-semibold">Title</th>
                  <th className="px-4 py-3 font-semibold">Type</th>
                  <th className="px-4 py-3 font-semibold">Status</th>
                  <th className="px-4 py-3 font-semibold">Source</th>
                  <th className="px-4 py-3 font-semibold">Duration</th>
                  <th className="px-4 py-3 font-semibold">Total time</th>
                  <th className="px-4 py-3 font-semibold">Billed</th>
                  <th className="px-4 py-3 font-semibold">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {jobList.map((job) => {
                  const Icon = JOB_TYPE_ICONS[job.job_type];
                  const stage = stageLabel(job);
                  return (
                    <tr key={job.id}>
                      <td className="whitespace-nowrap px-4 py-3">
                        {job.user_id ? (
                          <Link href={`/admin/users/${job.user_id}`} className="font-medium text-ink hover:underline">
                            {job.display_name || job.email}
                          </Link>
                        ) : (
                          <span className="text-ink-soft">—</span>
                        )}
                      </td>
                      <td className="max-w-xs px-4 py-3">
                        <p className="truncate text-ink" title={job.title ?? undefined}>
                          {job.title || "Untitled"}
                        </p>
                        {job.status === "failed" && job.error_message && (
                          <p className="mt-0.5 truncate text-xs text-status-error" title={job.error_message}>
                            {job.error_message}
                          </p>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <div className="flex items-center gap-1.5 text-ink-soft">
                          <Icon className="h-3.5 w-3.5" />
                          {JOB_TYPE_LABELS[job.job_type]}
                          {job.job_type === "video" && !job.extract_frames && " (transcript only)"}
                        </div>
                        {job.job_type === "video_gen" && (
                          <p className="mt-0.5 text-xs text-ink-soft">
                            {job.aspect_ratio} &middot; {job.video_template} &middot; {job.stock_media_provider}
                          </p>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <span className={`text-xs font-semibold ${STATUS_STYLES[job.status]}`}>
                          {STATUS_LABELS[job.status] ?? job.status}
                        </span>
                        {stage && <p className="mt-0.5 text-xs text-ink-soft">{stage}</p>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-ink-soft">
                        {job.source_url ? (
                          <a href={job.source_url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                            YouTube link
                          </a>
                        ) : (
                          `Uploaded${job.source_size_bytes ? ` · ${formatBytes(job.source_size_bytes)}` : ""}`
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-ink-soft">{formatDuration(job.duration_seconds)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-ink-soft">{formatElapsed(job)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-ink-soft">{formatCents(job.billed_cents)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-ink-soft">{new Date(job.created_at).toLocaleString()}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </>
      )}
    </div>
  );
}

export default function AdminJobsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-ink-soft">Loading...</p>
        </div>
      }
    >
      <AdminJobsPageContent />
    </Suspense>
  );
}
