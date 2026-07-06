"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

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
    <div className="mx-auto w-full max-w-2xl flex-1 px-6 py-16">
      <Link href="/dashboard" className="text-sm text-zinc-500 hover:underline dark:text-zinc-400">
        ← Back to dashboard
      </Link>

      <h1 className="mt-4 text-lg font-semibold text-zinc-900 dark:text-zinc-50">Job detail</h1>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {!error && !job && <p className="mt-4 text-sm text-zinc-500 dark:text-zinc-400">Loading...</p>}

      {job && (
        <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-zinc-500 dark:text-zinc-400">Status</dt>
              <dd className="font-medium text-zinc-900 dark:text-zinc-50">{job.status}</dd>
            </div>
            {job.status === "processing" && job.progress_stage && (
              <div className="flex justify-between">
                <dt className="text-zinc-500 dark:text-zinc-400">Stage</dt>
                <dd className="font-medium text-zinc-900 dark:text-zinc-50">{job.progress_stage.replaceAll("_", " ")}</dd>
              </div>
            )}
            <div className="flex justify-between">
              <dt className="text-zinc-500 dark:text-zinc-400">Created</dt>
              <dd className="font-medium text-zinc-900 dark:text-zinc-50">{new Date(job.created_at).toLocaleString()}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-zinc-500 dark:text-zinc-400">Video length</dt>
              <dd className="font-medium text-zinc-900 dark:text-zinc-50">{formatDuration(job.duration_seconds)}</dd>
            </div>
          </dl>

          {job.status === "failed" && job.error && (
            <p className="mt-4 rounded-md bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
              {job.error}
            </p>
          )}

          {job.status === "done" && (
            <div className="mt-6 flex flex-wrap gap-2">
              {job.document_url && (
                <button
                  onClick={() => downloadAuthenticated(job.document_url!, `${job.job_id}.md`)}
                  className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-zinc-50 dark:text-zinc-900"
                >
                  Download Markdown
                </button>
              )}
              {job.document_bundle_url && (
                <button
                  onClick={() => downloadAuthenticated(job.document_bundle_url!, `${job.job_id}.zip`)}
                  className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm text-zinc-700 dark:border-zinc-700 dark:text-zinc-300"
                >
                  Download Markdown + images (.zip)
                </button>
              )}
              {job.document_docx_url && (
                <button
                  onClick={() => downloadAuthenticated(job.document_docx_url!, `${job.job_id}.docx`)}
                  className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm text-zinc-700 dark:border-zinc-700 dark:text-zinc-300"
                >
                  Download Word
                </button>
              )}
              {job.document_pdf_url && (
                <button
                  onClick={() => downloadAuthenticated(job.document_pdf_url!, `${job.job_id}.pdf`)}
                  className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm text-zinc-700 dark:border-zinc-700 dark:text-zinc-300"
                >
                  Download PDF
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
