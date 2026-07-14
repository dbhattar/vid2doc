"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ArchiveIcon, MarkdownFileIcon, MicrophoneIcon, PdfFileIcon, VideoCameraIcon, WordFileIcon } from "@/components/icons";
import { apiFetch, ApiError, downloadAuthenticated } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { formatCents } from "@/lib/billing";
import { displayTitle, formatDuration, formatElapsed, isActiveJob, type Job } from "@/lib/jobs";

const POLL_INTERVAL_MS = 3000;

export default function JobDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

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
    loadJob();
  }, [loadJob]);

  useEffect(() => {
    if (!job || !isActiveJob(job)) return;
    const id = setInterval(loadJob, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [job, loadJob]);

  async function handleRetry() {
    setRetrying(true);
    setRetryError(null);
    try {
      const retried = await apiFetch<Job>(`/api/jobs/${params.id}/retry`, { method: "POST" });
      router.push(`/dashboard/jobs/${retried.job_id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearSession();
        router.replace("/login");
        return;
      }
      setRetryError(err instanceof ApiError ? err.message : "Retry failed.");
      setRetrying(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl px-6 py-10">
      <div className="flex items-center gap-4">
        <Link href="/dashboard" className="text-sm text-muted hover:text-brand-amber-dark hover:underline">
          ← Back to dashboard
        </Link>
        {job && job.status === "done" && !job.retention_expired && (
          <Link href="/documents" className="text-sm text-muted hover:text-brand-amber-dark hover:underline">
            All documents →
          </Link>
        )}
      </div>

      <div className="mt-4 flex items-center gap-2.5">
        {job && (
          <span
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
              job.job_type === "audio" ? "bg-brand-navy-soft text-brand-navy" : "bg-brand-amber-soft text-brand-amber-dark"
            }`}
            title={job.job_type === "audio" ? "Audio transcript" : "Video document"}
          >
            {job.job_type === "audio" ? <MicrophoneIcon className="h-4 w-4" /> : <VideoCameraIcon className="h-4 w-4" />}
          </span>
        )}
        <h1 className="truncate text-2xl font-bold tracking-tight text-brand-navy">
          {job ? displayTitle(job) : "Job detail"}
        </h1>
      </div>

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
              <dt className="text-muted">Type</dt>
              <dd className="font-medium text-foreground capitalize">{job.job_type}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">{job.job_type === "audio" ? "Audio length" : "Video length"}</dt>
              <dd className="font-medium text-foreground">{formatDuration(job.duration_seconds)}</dd>
            </div>
            {(job.status === "done" || job.status === "failed") && (
              <div className="flex justify-between">
                <dt className="text-muted">Took</dt>
                <dd className="font-medium text-foreground">{formatElapsed(job)}</dd>
              </div>
            )}
            <div className="flex justify-between">
              <dt className="text-muted">Cost</dt>
              <dd className="font-medium text-foreground">{formatCents(job.billed_cents)}</dd>
            </div>
          </dl>

          {job.status === "failed" && job.error && (
            <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">
              {job.error}
            </p>
          )}

          {job.status === "failed" && (
            <div className="mt-4">
              <button
                onClick={handleRetry}
                disabled={retrying}
                className="rounded-lg bg-brand-navy px-3 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-brand-navy-hover disabled:cursor-default disabled:opacity-50"
              >
                {retrying ? "Retrying..." : "Retry"}
              </button>
              {retryError && <p className="mt-2 text-sm text-red-600">{retryError}</p>}
            </div>
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
                  className="flex items-center gap-2 rounded-lg bg-brand-navy px-3 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-brand-navy-hover"
                >
                  <MarkdownFileIcon className="h-5 w-5" />
                  Download Markdown
                </button>
              )}
              {job.document_bundle_url && (
                <button
                  onClick={() => downloadAuthenticated(job.document_bundle_url!, `${job.job_id}.zip`)}
                  className="flex items-center gap-2 rounded-lg border border-brand-border px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-brand-navy-soft"
                >
                  <ArchiveIcon className="h-5 w-5" />
                  Download Markdown + images (.zip)
                </button>
              )}
              {job.document_docx_url && (
                <button
                  onClick={() => downloadAuthenticated(job.document_docx_url!, `${job.job_id}.docx`)}
                  className="flex items-center gap-2 rounded-lg border border-brand-border px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-brand-navy-soft"
                >
                  <WordFileIcon className="h-5 w-5" />
                  Download Word
                </button>
              )}
              {job.document_pdf_url && (
                <button
                  onClick={() => downloadAuthenticated(job.document_pdf_url!, `${job.job_id}.pdf`)}
                  className="flex items-center gap-2 rounded-lg border border-brand-border px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-brand-navy-soft"
                >
                  <PdfFileIcon className="h-5 w-5" />
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
