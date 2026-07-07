"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import AppHeader from "@/components/AppHeader";
import { apiFetch, ApiError, downloadAuthenticated } from "@/lib/api";
import { clearSession, getToken } from "@/lib/auth";
import { formatDuration, isActiveJob, type Job } from "@/lib/jobs";

const POLL_INTERVAL_MS = 3000;

export default function JobDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadJob = useCallback(() => {
    apiFetch<Job>(`/api/get_status?job_id=${params.id}`)
      .then(setJob)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        if (err instanceof ApiError && err.status === 404) {
          setError("Job not found.");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Failed to load job.");
      });
  }, [params.id, router]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    loadJob();
  }, [router, loadJob]);

  useEffect(() => {
    if (!job || !isActiveJob(job)) return;
    const id = setInterval(loadJob, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [job, loadJob]);

  return (
    <div className="flex flex-1 flex-col">
      <AppHeader />
      <div className="mx-auto w-full max-w-2xl flex-1 px-6 py-10">
        <Link href="/dashboard" className="text-sm text-muted hover:text-brand-amber-dark hover:underline">
          ← Back to dashboard
        </Link>

        <h1 className="mt-4 text-2xl font-bold tracking-tight text-brand-navy dark:text-foreground">Job detail</h1>

        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

        {!error && !job && <p className="mt-4 text-sm text-muted">Loading...</p>}

        {job && (
          <div className="mt-6 rounded-2xl border border-brand-border bg-surface p-6 shadow-soft">
            <dl className="space-y-3 text-sm">
              <div className="flex justify-between">
                <dt className="text-muted">Status</dt>
                <dd className="font-medium text-foreground">{job.status}</dd>
              </div>
              {job.status === "processing" && job.progress_stage && (
                <div className="flex justify-between">
                  <dt className="text-muted">Stage</dt>
                  <dd className="font-medium text-foreground">{job.progress_stage.replaceAll("_", " ")}</dd>
                </div>
              )}
              <div className="flex justify-between">
                <dt className="text-muted">Created</dt>
                <dd className="font-medium text-foreground">{new Date(job.created_at).toLocaleString()}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted">Video length</dt>
                <dd className="font-medium text-foreground">{formatDuration(job.duration_seconds)}</dd>
              </div>
            </dl>

            {job.status === "failed" && job.error && (
              <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
                {job.error}
              </p>
            )}

            {job.status === "done" && job.retention_expired && (
              <p className="mt-4 rounded-lg bg-brand-navy-soft p-3 text-sm text-muted">
                This document was deleted per the 7-day retention policy and can no longer be downloaded.
              </p>
            )}

            {job.status === "done" && !job.retention_expired && (
              <div className="mt-6 flex flex-wrap gap-2">
                {job.document_url && (
                  <button
                    onClick={() => downloadAuthenticated(job.document_url!, `${job.job_id}.md`)}
                    className="rounded-lg bg-brand-navy px-3 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-brand-navy-hover"
                  >
                    Download Markdown
                  </button>
                )}
                {job.document_bundle_url && (
                  <button
                    onClick={() => downloadAuthenticated(job.document_bundle_url!, `${job.job_id}.zip`)}
                    className="rounded-lg border border-brand-border px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-brand-navy-soft"
                  >
                    Download Markdown + images (.zip)
                  </button>
                )}
                {job.document_docx_url && (
                  <button
                    onClick={() => downloadAuthenticated(job.document_docx_url!, `${job.job_id}.docx`)}
                    className="rounded-lg border border-brand-border px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-brand-navy-soft"
                  >
                    Download Word
                  </button>
                )}
                {job.document_pdf_url && (
                  <button
                    onClick={() => downloadAuthenticated(job.document_pdf_url!, `${job.job_id}.pdf`)}
                    className="rounded-lg border border-brand-border px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-brand-navy-soft"
                  >
                    Download PDF
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
