"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { apiFetch, ApiError, downloadAuthenticated } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import {
  ACCEPTED_UPLOAD_EXTENSIONS,
  displayTitle,
  formatDuration,
  isActiveJob,
  jobTypeForFilename,
  type Job,
} from "@/lib/jobs";

const POLL_INTERVAL_MS = 4000;

function StatusBadge({ job }: { job: Job }) {
  const styles: Record<Job["status"], string> = {
    queued: "bg-brand-navy-soft text-brand-navy",
    processing: "bg-blue-100 text-blue-700",
    done: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
  };
  const label = job.status === "processing" && job.progress_stage ? job.progress_stage.replaceAll("_", " ") : job.status;
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles[job.status]}`}>{label}</span>;
}

export default function DashboardPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadBlockedByBilling, setUploadBlockedByBilling] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleAuthError = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) {
        clearSession();
        router.replace("/login");
        return true;
      }
      return false;
    },
    [router],
  );

  const loadJobs = useCallback(() => {
    apiFetch<{ jobs: Job[]; total: number }>("/api/jobs?limit=50")
      .then((data) => setJobs(data.jobs))
      .catch((err) => {
        if (handleAuthError(err)) return;
        setLoadError(err instanceof ApiError ? err.message : "Failed to load jobs.");
      });
  }, [handleAuthError]);

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  // Poll while at least one job is still queued/processing; stop otherwise.
  useEffect(() => {
    if (!jobs || !jobs.some(isActiveJob)) return;
    const id = setInterval(loadJobs, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [jobs, loadJobs]);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;

    const jobType = jobTypeForFilename(file.name);
    if (!jobType) {
      setUploadError("Unsupported file type.");
      return;
    }

    setUploading(true);
    setUploadError(null);
    setUploadBlockedByBilling(false);
    try {
      const formData = new FormData();
      formData.append(jobType === "audio" ? "audio" : "video", file);
      const endpoint = jobType === "audio" ? "/api/transcribe_audio" : "/api/convert_to_doc";
      await apiFetch(endpoint, { method: "POST", body: formData });
      if (fileInputRef.current) fileInputRef.current.value = "";
      setSelectedFileName(null);
      loadJobs();
    } catch (err) {
      if (handleAuthError(err)) return;
      setUploadError(err instanceof ApiError ? err.message : "Upload failed.");
      setUploadBlockedByBilling(err instanceof ApiError && err.status === 402);
    } finally {
      setUploading(false);
    }
  }

  async function handleRetry(jobId: string) {
    setRetryingJobId(jobId);
    setRetryError(null);
    try {
      await apiFetch(`/api/jobs/${jobId}/retry`, { method: "POST" });
      loadJobs();
    } catch (err) {
      if (handleAuthError(err)) return;
      setRetryError(err instanceof ApiError ? err.message : "Retry failed.");
    } finally {
      setRetryingJobId(null);
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-brand-navy">Dashboard</h1>
      <p className="mt-1 text-sm text-muted">Submit a video or audio file and track it through to a finished result.</p>

      <form
        onSubmit={handleUpload}
        className="mt-8 rounded-2xl border border-brand-border bg-surface p-6 shadow-soft"
      >
        <h2 className="text-sm font-semibold text-foreground">Convert a video or audio file</h2>
        <p className="mt-1 text-xs text-muted">
          Video (MP4, MOV, MKV, WebM, AVI, M4V) gets a full document. Audio (MP3, WAV, M4A, AAC, FLAC, OGG) gets a
          verbatim, speaker-tagged transcript. Either way, up to 90 minutes.
        </p>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-stretch">
          <label className="flex flex-1 cursor-pointer items-center rounded-lg border border-dashed border-brand-border px-4 py-3 text-sm text-muted transition-colors hover:border-brand-amber hover:bg-brand-amber-soft/40">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_UPLOAD_EXTENSIONS}
              onChange={(e) => setSelectedFileName(e.target.files?.[0]?.name ?? null)}
              className="sr-only"
            />
            <span className="truncate">{selectedFileName ?? "Click to choose a video or audio file..."}</span>
          </label>
          <button
            type="submit"
            disabled={uploading || !selectedFileName}
            className="shrink-0 rounded-lg bg-brand-navy px-5 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-navy-hover disabled:cursor-default disabled:opacity-50"
          >
            {uploading ? "Uploading..." : "Upload"}
          </button>
        </div>
        {uploadError && (
          <p className="mt-2 text-sm text-red-600">
            {uploadError}
            {uploadBlockedByBilling && (
              <>
                {" "}
                <Link href="/settings/billing" className="underline">
                  Manage billing
                </Link>
              </>
            )}
          </p>
        )}
      </form>

      <div className="mt-10">
        <h2 className="text-sm font-semibold text-foreground">Your jobs</h2>
        {loadError && <p className="mt-2 text-sm text-red-600">{loadError}</p>}
        {retryError && <p className="mt-2 text-sm text-red-600">{retryError}</p>}
        {jobs === null ? (
          <p className="mt-3 text-sm text-muted">Loading...</p>
        ) : jobs.length === 0 ? (
          <p className="mt-3 rounded-2xl border border-dashed border-brand-border p-6 text-center text-sm text-muted">
            No jobs yet -- upload a video or audio file above to get started.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-brand-border overflow-hidden rounded-2xl border border-brand-border bg-surface shadow-soft">
            {jobs.map((job) => (
              <li key={job.job_id} className="flex items-center justify-between px-4 py-3">
                <div className="min-w-0">
                  <Link
                    href={`/dashboard/jobs/${job.job_id}`}
                    className="block truncate text-sm font-medium text-foreground hover:text-brand-amber-dark hover:underline"
                  >
                    {displayTitle(job)}
                  </Link>
                  <p className="text-xs text-muted">
                    {new Date(job.created_at).toLocaleDateString()} &middot; {formatDuration(job.duration_seconds)}{" "}
                    {job.job_type}
                  </p>
                  {job.status === "failed" && job.error && (
                    <p className="mt-0.5 max-w-sm truncate text-xs text-red-600" title={job.error}>
                      {job.error}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <StatusBadge job={job} />
                  {job.status === "failed" && (
                    <button
                      onClick={() => handleRetry(job.job_id)}
                      disabled={retryingJobId === job.job_id}
                      className="text-sm text-brand-navy hover:text-brand-amber-dark hover:underline disabled:cursor-default disabled:opacity-50"
                    >
                      {retryingJobId === job.job_id ? "Retrying..." : "Retry"}
                    </button>
                  )}
                  {job.status === "done" && job.retention_expired && (
                    <span className="text-xs text-muted" title="Documents aren't guaranteed past 7 days">
                      Expired
                    </span>
                  )}
                  {job.status === "done" && !job.retention_expired && (
                    <div className="flex items-center gap-2 text-sm text-muted">
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
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
