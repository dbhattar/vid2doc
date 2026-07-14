"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import DocumentCard from "@/components/DocumentCard";
import { MicrophoneIcon, VideoCameraIcon } from "@/components/icons";
import Pagination from "@/components/Pagination";
import { apiFetch, ApiError } from "@/lib/api";
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
const DOCUMENTS_PAGE_SIZE = 12;

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

function JobRow({
  job,
  onRetry,
  onDelete,
  retryingJobId,
  deletingJobId,
}: {
  job: Job;
  onRetry: (jobId: string) => void;
  onDelete: (job: Job) => void;
  retryingJobId: string | null;
  deletingJobId: string | null;
}) {
  return (
    <li className="flex items-center justify-between px-4 py-3">
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
        {job.status === "failed" && job.error && (
          <p className="mt-0.5 max-w-sm truncate text-xs text-red-600" title={job.error}>
            {job.error}
          </p>
        )}
      </div>
      <div className="flex items-center gap-3">
        <StatusBadge job={job} />
        {job.status === "failed" && (
          <>
            <button
              onClick={() => onRetry(job.job_id)}
              disabled={retryingJobId === job.job_id || deletingJobId === job.job_id}
              className="text-sm text-brand-navy hover:text-brand-amber-dark hover:underline disabled:cursor-default disabled:opacity-50"
            >
              {retryingJobId === job.job_id ? "Retrying..." : "Retry"}
            </button>
            <button
              onClick={() => onDelete(job)}
              disabled={retryingJobId === job.job_id || deletingJobId === job.job_id}
              className="text-sm text-red-600 hover:underline disabled:cursor-default disabled:opacity-50"
            >
              {deletingJobId === job.job_id ? "Deleting..." : "Delete"}
            </button>
          </>
        )}
      </div>
    </li>
  );
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
  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const [videoCount, setVideoCount] = useState<number | null>(null);
  const [audioCount, setAudioCount] = useState<number | null>(null);

  const [documentsPage, setDocumentsPage] = useState(1);
  const [documents, setDocuments] = useState<Job[] | null>(null);
  const [documentsTotal, setDocumentsTotal] = useState(0);
  const [documentsError, setDocumentsError] = useState<string | null>(null);

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

  const loadStats = useCallback(() => {
    Promise.all([
      apiFetch<{ total: number }>("/api/jobs?status=done&job_type=video&limit=1"),
      apiFetch<{ total: number }>("/api/jobs?status=done&job_type=audio&limit=1"),
    ])
      .then(([video, audio]) => {
        setVideoCount(video.total);
        setAudioCount(audio.total);
      })
      .catch((err) => {
        handleAuthError(err);
      });
  }, [handleAuthError]);

  const loadDocuments = useCallback(
    (page: number) => {
      const offset = (page - 1) * DOCUMENTS_PAGE_SIZE;
      apiFetch<{ jobs: Job[]; total: number }>(`/api/jobs?status=done&limit=${DOCUMENTS_PAGE_SIZE}&offset=${offset}`)
        .then((data) => {
          setDocuments(data.jobs);
          setDocumentsTotal(data.total);
        })
        .catch((err) => {
          if (handleAuthError(err)) return;
          setDocumentsError(err instanceof ApiError ? err.message : "Failed to load documents.");
        });
    },
    [handleAuthError],
  );

  useEffect(() => {
    loadJobs();
    loadStats();
    loadDocuments(1);
  }, [loadJobs, loadStats, loadDocuments]);

  useEffect(() => {
    loadDocuments(documentsPage);
  }, [documentsPage, loadDocuments]);

  // Poll while at least one job is still queued/processing; also refreshes
  // stats/the document grid so a job finishing mid-session shows up without
  // a manual reload.
  useEffect(() => {
    if (!jobs || !jobs.some(isActiveJob)) return;
    const id = setInterval(() => {
      loadJobs();
      loadStats();
      loadDocuments(documentsPage);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [jobs, loadJobs, loadStats, loadDocuments, documentsPage]);

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

  const videoInProgress = jobs?.filter((j) => j.status !== "done" && j.job_type === "video") ?? null;
  const audioInProgress = jobs?.filter((j) => j.status !== "done" && j.job_type === "audio") ?? null;

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-10">
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

      <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="flex items-center gap-4 rounded-2xl border border-brand-border bg-surface p-5 shadow-soft">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-brand-amber-soft text-brand-amber-dark">
            <VideoCameraIcon className="h-5 w-5" />
          </span>
          <div>
            <p className="text-2xl font-bold tracking-tight text-brand-navy">{videoCount ?? "—"}</p>
            <p className="text-sm text-muted">Video documents</p>
          </div>
        </div>
        <div className="flex items-center gap-4 rounded-2xl border border-brand-border bg-surface p-5 shadow-soft">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-brand-navy-soft text-brand-navy">
            <MicrophoneIcon className="h-5 w-5" />
          </span>
          <div>
            <p className="text-2xl font-bold tracking-tight text-brand-navy">{audioCount ?? "—"}</p>
            <p className="text-sm text-muted">Audio transcripts</p>
          </div>
        </div>
      </div>

      {((videoInProgress && videoInProgress.length > 0) || (audioInProgress && audioInProgress.length > 0)) && (
        <div className="mt-10">
          <h2 className="text-sm font-semibold text-foreground">In progress</h2>
          {loadError && <p className="mt-2 text-sm text-red-600">{loadError}</p>}
          {retryError && <p className="mt-2 text-sm text-red-600">{retryError}</p>}
          {deleteError && <p className="mt-2 text-sm text-red-600">{deleteError}</p>}

          {videoInProgress && videoInProgress.length > 0 && (
            <div className="mt-3">
              <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted">
                <VideoCameraIcon className="h-3.5 w-3.5" /> Video
              </div>
              <ul className="mt-2 divide-y divide-brand-border overflow-hidden rounded-2xl border border-brand-border bg-surface shadow-soft">
                {videoInProgress.map((job) => (
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

          {audioInProgress && audioInProgress.length > 0 && (
            <div className="mt-6">
              <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted">
                <MicrophoneIcon className="h-3.5 w-3.5" /> Audio
              </div>
              <ul className="mt-2 divide-y divide-brand-border overflow-hidden rounded-2xl border border-brand-border bg-surface shadow-soft">
                {audioInProgress.map((job) => (
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
      )}

      <div className="mt-10">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-foreground">Documents</h2>
          <Link href="/documents" className="text-sm text-muted hover:text-brand-amber-dark hover:underline">
            View all →
          </Link>
        </div>
        {documentsError && <p className="mt-2 text-sm text-red-600">{documentsError}</p>}
        {documents === null ? (
          <p className="mt-3 text-sm text-muted">Loading...</p>
        ) : documents.length === 0 ? (
          <p className="mt-3 rounded-2xl border border-dashed border-brand-border p-6 text-center text-sm text-muted">
            No documents yet -- upload a video or audio file above to get started.
          </p>
        ) : (
          <>
            <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {documents.map((job) => (
                <DocumentCard key={job.job_id} job={job} />
              ))}
            </div>
            <Pagination page={documentsPage} pageSize={DOCUMENTS_PAGE_SIZE} total={documentsTotal} onPageChange={setDocumentsPage} />
          </>
        )}
      </div>
    </div>
  );
}
