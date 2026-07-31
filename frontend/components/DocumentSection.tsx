"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import DocumentCard from "@/components/DocumentCard";
import Pagination from "@/components/Pagination";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import type { Job, JobType } from "@/lib/jobs";

const PAGE_SIZE = 12;

/** A paginated grid of finished documents for one job type -- the building
 * block behind the documents page's two type sections. */
export default function DocumentSection({
  jobType,
  title,
  Icon,
  pageSize = PAGE_SIZE,
}: {
  jobType: JobType;
  title: string;
  Icon: (props: { className?: string }) => React.ReactElement;
  pageSize?: number;
}) {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    (p: number) => {
      const offset = (p - 1) * pageSize;
      apiFetch<{ jobs: Job[]; total: number }>(
        `/api/jobs?status=done&job_type=${jobType}&limit=${pageSize}&offset=${offset}`,
      )
        .then((data) => {
          setJobs(data.jobs);
          setTotal(data.total);
        })
        .catch((err) => {
          if (err instanceof ApiError && err.status === 401) {
            clearSession();
            router.replace("/login");
            return;
          }
          setError(err instanceof ApiError ? err.message : `Failed to load ${title.toLowerCase()}.`);
        });
    },
    [jobType, pageSize, router, title],
  );

  useEffect(() => {
    load(page);
  }, [page, load]);

  return (
    <div className="mt-10">
      <div className="flex items-center gap-2.5">
        <span
          className={`flex h-8 w-8 shrink-0 items-center justify-center ${
            jobType === "audio" ? "bg-paper-shade text-ink-soft" : "bg-accent-soft text-accent"
          }`}
        >
          <Icon className="h-4 w-4" />
        </span>
        <h2 className="text-sm font-semibold text-ink">
          {title} <span className="font-normal text-ink-soft">({total})</span>
        </h2>
      </div>

      {error && <p className="mt-2 text-sm text-status-error">{error}</p>}

      {jobs === null ? (
        <p className="mt-3 text-sm text-ink-soft">Loading...</p>
      ) : jobs.length === 0 ? (
        <p className="mt-3 border-2 border-dashed border-line p-6 text-center text-sm text-ink-soft">
          No {title.toLowerCase()} yet.
        </p>
      ) : (
        <>
          <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {jobs.map((job) => (
              <DocumentCard key={job.job_id} job={job} />
            ))}
          </div>
          <Pagination page={page} pageSize={pageSize} total={total} onPageChange={setPage} />
        </>
      )}
    </div>
  );
}
