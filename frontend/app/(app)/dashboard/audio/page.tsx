"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import Button from "@/components/Button";
import JobRow from "@/components/JobRow";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { AUDIO_EXTENSIONS, displayTitle, isActiveJob, type Job } from "@/lib/jobs";

const POLL_INTERVAL_MS = 4000;
const ACCEPTED_EXTENSIONS = AUDIO_EXTENSIONS.join(",");

// Deliberately a separate implementation from VideoPage, not a shared
// parameterized component -- audio's flow (straight to a verbatim,
// speaker-tagged transcript, no frame review) is simple today but should be
// free to diverge from video's without the two dragging on each other.
// Documents live on /documents and the unified /dashboard now, not here --
// this page is just the upload flow plus tracking what's in flight.
export default function AudioPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadBlockedByBilling, setUploadBlockedByBilling] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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
    apiFetch<{ jobs: Job[]; total: number }>("/api/jobs?job_type=audio&limit=50")
      .then((data) => setJobs(data.jobs))
      .catch((err) => {
        if (handleAuthError(err)) return;
        setLoadError(err instanceof ApiError ? err.message : "Failed to load jobs.");
      });
  }, [handleAuthError]);

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  useEffect(() => {
    if (!jobs || !jobs.some(isActiveJob)) return;
    const id = setInterval(loadJobs, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [jobs, loadJobs]);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadError(null);
    setUploadBlockedByBilling(false);
    try {
      const formData = new FormData();
      formData.append("audio", file);
      await apiFetch("/api/transcribe_audio", { method: "POST", body: formData });
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

  async function handleDelete(job: Job) {
    if (!confirm(`Delete "${displayTitle(job)}"? This can't be undone.`)) return;
    setDeletingJobId(job.job_id);
    setDeleteError(null);
    try {
      await apiFetch(`/api/jobs/${job.job_id}`, { method: "DELETE" });
      loadJobs();
    } catch (err) {
      if (handleAuthError(err)) return;
      setDeleteError(err instanceof ApiError ? err.message : "Delete failed.");
    } finally {
      setDeletingJobId(null);
    }
  }

  const inProgress = jobs?.filter((j) => j.status !== "done") ?? null;

  return (
    <div className="w-full px-6 py-10">
      <div className="flex min-h-[65vh] flex-col items-center justify-center text-center">
        <p className="font-mono text-xs font-semibold uppercase tracking-wide text-accent">Audio → Transcript</p>
        <h1 className="mt-3 max-w-xl font-display text-4xl font-bold tracking-tight text-ink">
          Every word, perfectly on the record.
        </h1>
        <p className="mt-3 max-w-md text-sm text-ink-soft">
          Upload an audio file and get back a verbatim, speaker-tagged transcript -- no rewatching, no scrubbing
          through recordings to find who said what.
        </p>

        <form onSubmit={handleUpload} className="mt-8 w-full max-w-md border-2 border-line bg-paper p-6 text-left">
          <p className="text-xs text-ink-soft">MP3, WAV, M4A, AAC, FLAC, or OGG, up to 90 minutes.</p>

          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-stretch">
            <label className="flex flex-1 cursor-pointer items-center border-2 border-dashed border-line px-4 py-3 text-sm text-ink-soft transition-colors hover:border-accent hover:bg-accent-soft/40">
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_EXTENSIONS}
                onChange={(e) => setSelectedFileName(e.target.files?.[0]?.name ?? null)}
                className="sr-only"
              />
              <span className="truncate">{selectedFileName ?? "Click to choose an audio file..."}</span>
            </label>
            <Button type="submit" disabled={uploading || !selectedFileName} className="shrink-0 justify-center">
              {uploading ? "Uploading..." : "Upload"}
            </Button>
          </div>
          {uploadError && (
            <p className="mt-2 text-sm text-status-error">
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
      </div>

      {inProgress && inProgress.length > 0 && (
        <div className="mt-10">
          <h2 className="text-sm font-semibold text-ink">In progress</h2>
          {loadError && <p className="mt-2 text-sm text-status-error">{loadError}</p>}
          {retryError && <p className="mt-2 text-sm text-status-error">{retryError}</p>}
          {deleteError && <p className="mt-2 text-sm text-status-error">{deleteError}</p>}

          <ul className="mt-2 divide-y divide-line border-2 border-line bg-paper">
            {inProgress.map((job) => (
              <JobRow
                key={job.job_id}
                job={job}
                onRetry={handleRetry}
                onDelete={handleDelete}
                retryingJobId={retryingJobId}
                deletingJobId={deletingJobId}
              />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
