"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import Button from "@/components/Button";
import JobRow from "@/components/JobRow";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { VIDEO_EXTENSIONS, displayTitle, isActiveJob, type Job } from "@/lib/jobs";

const POLL_INTERVAL_MS = 4000;
const ACCEPTED_EXTENSIONS = VIDEO_EXTENSIONS.join(",");

// Mirrors backend/app/billing.py's SECONDS_PER_CENT / SECONDS_PER_CENT_AUDIO
// -- a client-side estimate only, so the price difference is visible before
// submitting; the backend is the source of truth for the actual charge.
const SECONDS_PER_CENT_VIDEO = 36;
const SECONDS_PER_CENT_AUDIO = 90;

function estimatedCostCents(durationSeconds: number, withVisuals: boolean): number {
  return Math.ceil(durationSeconds / (withVisuals ? SECONDS_PER_CENT_VIDEO : SECONDS_PER_CENT_AUDIO));
}

// Video gets its own nav item (rather than sharing a generic upload form with
// audio) specifically so this page's flow -- upload, frame review, document --
// can keep evolving independently of audio's much simpler verbatim-transcript
// flow. See AudioPage for the parallel, deliberately separate implementation.
// Documents live on /documents and the unified /dashboard now, not here --
// this page is just the upload flow plus tracking what's in flight.
export default function VideoPage() {
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
  const [cancellingJobId, setCancellingJobId] = useState<string | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [source, setSource] = useState<"file" | "youtube">("file");
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [extractFrames, setExtractFrames] = useState(true);
  const [fileDurationSeconds, setFileDurationSeconds] = useState<number | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleFileSelected(file: File | null) {
    setSelectedFileName(file?.name ?? null);
    setFileDurationSeconds(null);
    if (!file) return;
    // Read the file's duration client-side (no upload needed yet) so the
    // cost estimate below can reflect the actual video, not just a flat rate.
    const url = URL.createObjectURL(file);
    const probe = document.createElement("video");
    probe.preload = "metadata";
    probe.onloadedmetadata = () => {
      setFileDurationSeconds(probe.duration);
      URL.revokeObjectURL(url);
    };
    probe.src = url;
  }

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
    apiFetch<{ jobs: Job[]; total: number }>("/api/jobs?job_type=video&limit=50")
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
      formData.append("video", file);
      formData.append("extract_frames", String(extractFrames));
      await apiFetch("/api/convert_to_doc", { method: "POST", body: formData });
      if (fileInputRef.current) fileInputRef.current.value = "";
      setSelectedFileName(null);
      setFileDurationSeconds(null);
      loadJobs();
    } catch (err) {
      if (handleAuthError(err)) return;
      setUploadError(err instanceof ApiError ? err.message : "Upload failed.");
      setUploadBlockedByBilling(err instanceof ApiError && err.status === 402);
    } finally {
      setUploading(false);
    }
  }

  async function handleYoutubeSubmit(e: React.FormEvent) {
    e.preventDefault();
    const url = youtubeUrl.trim();
    if (!url) return;

    setUploading(true);
    setUploadError(null);
    setUploadBlockedByBilling(false);
    try {
      await apiFetch("/api/convert_from_youtube", {
        method: "POST",
        body: JSON.stringify({ url, extract_frames: extractFrames }),
      });
      setYoutubeUrl("");
      loadJobs();
    } catch (err) {
      if (handleAuthError(err)) return;
      setUploadError(err instanceof ApiError ? err.message : "Import failed.");
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

  async function handleCancel(job: Job) {
    if (!confirm(`Cancel "${displayTitle(job)}"? Any charge for it will be refunded.`)) return;
    setCancellingJobId(job.job_id);
    setCancelError(null);
    try {
      await apiFetch(`/api/jobs/${job.job_id}/cancel`, { method: "POST" });
      loadJobs();
    } catch (err) {
      if (handleAuthError(err)) return;
      setCancelError(err instanceof ApiError ? err.message : "Cancel failed.");
    } finally {
      setCancellingJobId(null);
    }
  }

  const inProgress = jobs?.filter((j) => j.status !== "done") ?? null;

  return (
    <div className="w-full px-6 py-10">
      <p className="font-sans text-xs font-semibold text-accent">Video → Document</p>
      <h1 className="mt-2 font-display text-2xl font-bold tracking-tight text-ink">Never rewatch a recording again.</h1>
      <p className="mt-1 max-w-2xl text-sm text-ink-soft">
        Upload a video and Framewrite pulls the slides, diagrams, and tables out of it, then writes the whole thing up
        as one clean document -- you just pick which frames make the cut.
      </p>

      <div className="mt-8 max-w-xl">
        <form
          onSubmit={source === "file" ? handleUpload : handleYoutubeSubmit}
          className="w-full rounded-lg border border-line bg-paper p-6 shadow-sm"
        >
          <div className="flex gap-2 font-sans text-xs font-medium">
            <button
              type="button"
              onClick={() => setSource("file")}
              className={`rounded-md border px-3 py-1 transition-all duration-150 ease-[var(--ease-spring)] hover:-translate-y-0.5 ${
                source === "file" ? "border-ink bg-ink text-paper" : "border-line text-ink-soft hover:border-ink"
              }`}
            >
              Upload file
            </button>
            <button
              type="button"
              onClick={() => setSource("youtube")}
              className={`rounded-md border px-3 py-1 transition-all duration-150 ease-[var(--ease-spring)] hover:-translate-y-0.5 ${
                source === "youtube" ? "border-ink bg-ink text-paper" : "border-line text-ink-soft hover:border-ink"
              }`}
            >
              YouTube link
            </button>
          </div>

          <p className="mt-3 text-xs text-ink-soft">MP4, MOV, MKV, WebM, AVI, or M4V, up to 90 minutes.</p>

          {source === "file" ? (
            <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-stretch">
              <label className="flex flex-1 cursor-pointer items-center rounded-md border border-dashed border-line px-4 py-3 text-sm text-ink-soft transition-colors hover:border-accent hover:bg-accent-soft/40">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={ACCEPTED_EXTENSIONS}
                  onChange={(e) => handleFileSelected(e.target.files?.[0] ?? null)}
                  className="sr-only"
                />
                <span className="truncate">{selectedFileName ?? "Click to choose a video file..."}</span>
              </label>
              <Button type="submit" disabled={uploading || !selectedFileName} className="shrink-0 justify-center">
                {uploading ? "Uploading..." : "Upload"}
              </Button>
            </div>
          ) : (
            <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-stretch">
              <input
                type="url"
                value={youtubeUrl}
                onChange={(e) => setYoutubeUrl(e.target.value)}
                placeholder="https://www.youtube.com/watch?v=..."
                className="flex-1 rounded-md border border-line bg-paper px-3 py-2 text-sm text-ink outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft"
              />
              <Button type="submit" disabled={uploading || !youtubeUrl.trim()} className="shrink-0 justify-center">
                {uploading ? "Importing..." : "Import"}
              </Button>
            </div>
          )}

          <label className="mt-4 flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={extractFrames}
              onChange={(e) => setExtractFrames(e.target.checked)}
              className="h-4 w-4 rounded border-line accent-accent"
            />
            Extract frames (slides, diagrams, tables)
          </label>
          <p className="mt-1 text-xs text-ink-soft">
            {source === "file" && fileDurationSeconds != null
              ? extractFrames
                ? `$${(estimatedCostCents(fileDurationSeconds, true) / 100).toFixed(2)} with visuals`
                : `$${(estimatedCostCents(fileDurationSeconds, false) / 100).toFixed(2)} transcript-only`
              : extractFrames
                ? "$1.00/hour with visuals"
                : "$0.40/hour transcript-only -- no slides, diagrams, or tables"}
          </p>

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
          {cancelError && <p className="mt-2 text-sm text-status-error">{cancelError}</p>}

          <ul className="mt-2 divide-y divide-line overflow-hidden rounded-lg border border-line bg-paper shadow-sm">
            {inProgress.map((job) => (
              <JobRow
                key={job.job_id}
                job={job}
                onRetry={handleRetry}
                onDelete={handleDelete}
                onCancel={handleCancel}
                retryingJobId={retryingJobId}
                deletingJobId={deletingJobId}
                cancellingJobId={cancellingJobId}
              />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
