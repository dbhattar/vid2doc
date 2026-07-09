"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch, ApiError, downloadAuthenticated } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { displayTitle, formatDuration, type Job } from "@/lib/jobs";

export default function DocumentsPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<{ jobs: Job[]; total: number }>("/api/jobs?status=done&limit=100")
      .then((data) => setJobs(data.jobs))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        setLoadError(err instanceof ApiError ? err.message : "Failed to load documents.");
      });
  }, [router]);

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-brand-navy">Documents</h1>
      <p className="mt-1 text-sm text-muted">Every document Framewrite has finished generating for you.</p>

      {loadError && <p className="mt-4 text-sm text-red-600">{loadError}</p>}

      {jobs === null ? (
        <p className="mt-4 text-sm text-muted">Loading...</p>
      ) : jobs.length === 0 ? (
        <p className="mt-4 rounded-2xl border border-dashed border-brand-border p-6 text-center text-sm text-muted">
          No documents yet -- convert a video from the{" "}
          <Link href="/dashboard" className="underline hover:text-brand-amber-dark">
            dashboard
          </Link>{" "}
          to get started.
        </p>
      ) : (
        <ul className="mt-4 divide-y divide-brand-border overflow-hidden rounded-2xl border border-brand-border bg-surface shadow-soft">
          {jobs.map((job) => (
            <li key={job.job_id} className="flex items-center justify-between gap-4 px-4 py-3">
              <div className="min-w-0">
                <Link
                  href={`/dashboard/jobs/${job.job_id}`}
                  className="block truncate text-sm font-medium text-foreground hover:text-brand-amber-dark hover:underline"
                >
                  {displayTitle(job)}
                </Link>
                <p className="text-xs text-muted">
                  {new Date(job.created_at).toLocaleDateString()} &middot; {formatDuration(job.duration_seconds)}
                </p>
              </div>

              {job.retention_expired ? (
                <span className="shrink-0 text-xs text-muted" title="Documents aren't guaranteed past 7 days">
                  Expired
                </span>
              ) : (
                <div className="flex shrink-0 items-center gap-2 text-sm text-muted">
                  {job.document_url && (
                    <button onClick={() => downloadAuthenticated(job.document_url!, `${job.job_id}.md`)} className="hover:text-brand-amber-dark hover:underline">
                      MD
                    </button>
                  )}
                  {job.document_bundle_url && (
                    <button onClick={() => downloadAuthenticated(job.document_bundle_url!, `${job.job_id}.zip`)} className="hover:text-brand-amber-dark hover:underline">
                      MD+images
                    </button>
                  )}
                  {job.document_docx_url && (
                    <button onClick={() => downloadAuthenticated(job.document_docx_url!, `${job.job_id}.docx`)} className="hover:text-brand-amber-dark hover:underline">
                      DOCX
                    </button>
                  )}
                  {job.document_pdf_url && (
                    <button onClick={() => downloadAuthenticated(job.document_pdf_url!, `${job.job_id}.pdf`)} className="hover:text-brand-amber-dark hover:underline">
                      PDF
                    </button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
