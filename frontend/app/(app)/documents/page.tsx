"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import DocumentCard from "@/components/DocumentCard";
import { MicrophoneIcon, VideoCameraIcon } from "@/components/icons";
import Pagination from "@/components/Pagination";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import type { Job, JobType } from "@/lib/jobs";

const PAGE_SIZE = 9;

function DocumentSection({ jobType, title, Icon }: { jobType: JobType; title: string; Icon: typeof VideoCameraIcon }) {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    (p: number) => {
      const offset = (p - 1) * PAGE_SIZE;
      apiFetch<{ jobs: Job[]; total: number }>(
        `/api/jobs?status=done&job_type=${jobType}&limit=${PAGE_SIZE}&offset=${offset}`,
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
    [jobType, router, title],
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
          <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {jobs.map((job) => (
              <DocumentCard key={job.job_id} job={job} />
            ))}
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </>
      )}
    </div>
  );
}

export default function DocumentsPage() {
  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-10">
      <h1 className="font-display text-2xl font-bold tracking-tight text-ink">Documents</h1>
      <p className="mt-1 text-sm text-ink-soft">Every document Framewrite has finished generating for you.</p>

      <DocumentSection jobType="video" title="Video documents" Icon={VideoCameraIcon} />
      <DocumentSection jobType="audio" title="Audio transcripts" Icon={MicrophoneIcon} />

      <p className="mt-10 text-center text-sm text-ink-soft">
        Nothing here yet? Convert a video or audio file from the{" "}
        <Link href="/dashboard" className="underline hover:text-accent">
          dashboard
        </Link>
        .
      </p>
    </div>
  );
}
