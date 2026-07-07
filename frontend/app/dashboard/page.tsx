"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { apiFetch, ApiError, downloadAuthenticated } from "@/lib/api";
import { clearSession, getToken, type CurrentUser } from "@/lib/auth";
import { formatDuration, isActiveJob, type Job } from "@/lib/jobs";

const POLL_INTERVAL_MS = 4000;
const ACCEPTED_EXTENSIONS = ".mp4,.mov,.mkv,.webm,.avi,.m4v";

function StatusBadge({ job }: { job: Job }) {
  const styles: Record<Job["status"], string> = {
    queued: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
    processing: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
    done: "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300",
    failed: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
  };
  const label = job.status === "processing" && job.progress_stage ? job.progress_stage.replaceAll("_", " ") : job.status;
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles[job.status]}`}>{label}</span>;
}

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadBlockedByBilling, setUploadBlockedByBilling] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
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
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    apiFetch<CurrentUser>("/api/auth/me").then(setUser).catch(handleAuthError);
    loadJobs();
  }, [router, loadJobs, handleAuthError]);

  // Poll while at least one job is still queued/processing; stop otherwise.
  useEffect(() => {
    if (!jobs || !jobs.some(isActiveJob)) return;
    const id = setInterval(loadJobs, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [jobs, loadJobs]);

  function handleLogout() {
    clearSession();
    router.replace("/login");
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadError(null);
    setUploadBlockedByBilling(false);
    try {
      const formData = new FormData();
      formData.append("video", file);
      await apiFetch("/api/convert_to_doc", { method: "POST", body: formData });
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

  return (
    <div className="mx-auto w-full max-w-3xl flex-1 px-6 py-16">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Dashboard</h1>
        <div className="flex items-center gap-4">
          <Link href="/settings/billing" className="text-sm text-zinc-600 hover:underline dark:text-zinc-400">
            Billing
          </Link>
          <Link href="/settings/api-keys" className="text-sm text-zinc-600 hover:underline dark:text-zinc-400">
            API keys
          </Link>
          <button
            onClick={handleLogout}
            className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
          >
            Log out
          </button>
        </div>
      </div>

      {user && (
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">Signed in as {user.email}</p>
      )}

      <form onSubmit={handleUpload} className="mt-8 rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Convert a video</h2>
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
          MP4, MOV, MKV, WebM, AVI, or M4V, up to 90 minutes.
        </p>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-stretch">
          <label className="flex flex-1 cursor-pointer items-center rounded-md border border-dashed border-zinc-300 px-4 py-3 text-sm text-zinc-600 hover:border-zinc-400 dark:border-zinc-700 dark:text-zinc-400 dark:hover:border-zinc-600">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_EXTENSIONS}
              onChange={(e) => setSelectedFileName(e.target.files?.[0]?.name ?? null)}
              className="sr-only"
            />
            <span className="truncate">{selectedFileName ?? "Click to choose a video file..."}</span>
          </label>
          <button
            type="submit"
            disabled={uploading || !selectedFileName}
            className="shrink-0 rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
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

      <div className="mt-8">
        <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Your jobs</h2>
        {loadError && <p className="mt-2 text-sm text-red-600">{loadError}</p>}
        {jobs === null ? (
          <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">Loading...</p>
        ) : jobs.length === 0 ? (
          <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">No jobs yet -- upload a video to get started.</p>
        ) : (
          <ul className="mt-3 divide-y divide-zinc-200 rounded-xl border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
            {jobs.map((job) => (
              <li key={job.job_id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <Link href={`/dashboard/jobs/${job.job_id}`} className="text-sm font-medium text-zinc-900 hover:underline dark:text-zinc-50">
                    {new Date(job.created_at).toLocaleString()}
                  </Link>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">{formatDuration(job.duration_seconds)} video</p>
                </div>
                <div className="flex items-center gap-3">
                  <StatusBadge job={job} />
                  {job.status === "done" && job.retention_expired && (
                    <span className="text-xs text-zinc-400" title="Documents aren't guaranteed past 7 days">
                      Expired
                    </span>
                  )}
                  {job.status === "done" && !job.retention_expired && (
                    <div className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
                      {job.document_url && (
                        <button onClick={() => downloadAuthenticated(job.document_url!, `${job.job_id}.md`)} className="hover:underline">
                          MD
                        </button>
                      )}
                      {job.document_bundle_url && (
                        <button onClick={() => downloadAuthenticated(job.document_bundle_url!, `${job.job_id}.zip`)} className="hover:underline">
                          MD+images
                        </button>
                      )}
                      {job.document_docx_url && (
                        <button onClick={() => downloadAuthenticated(job.document_docx_url!, `${job.job_id}.docx`)} className="hover:underline">
                          DOCX
                        </button>
                      )}
                      {job.document_pdf_url && (
                        <button onClick={() => downloadAuthenticated(job.document_pdf_url!, `${job.job_id}.pdf`)} className="hover:underline">
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
