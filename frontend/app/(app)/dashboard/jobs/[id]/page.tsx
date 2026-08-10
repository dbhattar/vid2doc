"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Button, { buttonClassName } from "@/components/Button";
import Card from "@/components/Card";
import DocumentPreview from "@/components/DocumentPreview";
import FrameReviewPanel from "@/components/FrameReviewPanel";
import { ArchiveIcon, DriveIcon, JsonFileIcon, MarkdownFileIcon, MicrophoneIcon, PdfFileIcon, VideoCameraIcon, WordFileIcon } from "@/components/icons";
import ShareControl from "@/components/ShareControl";
import TranscriptViewer from "@/components/TranscriptViewer";
import { apiFetch, ApiError, downloadAuthenticated } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { formatCents } from "@/lib/billing";
import { displayTitle, formatDuration, formatElapsed, isActiveJob, type Job } from "@/lib/jobs";
import { useDriveStatus } from "@/lib/useDriveStatus";

const POLL_INTERVAL_MS = 3000;

export default function JobDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const driveConnected = useDriveStatus();
  const [savingToDrive, setSavingToDrive] = useState(false);
  const [driveError, setDriveError] = useState<string | null>(null);

  async function handleSaveToDrive() {
    if (!job) return;
    setSavingToDrive(true);
    setDriveError(null);
    try {
      const { folder_url, warnings } = await apiFetch<{ folder_url: string; warnings?: string[] }>(
        `/api/jobs/${job.job_id}/drive-upload`,
        { method: "POST" }
      );
      window.open(folder_url, "_blank");
      if (warnings?.length) setDriveError(`Saved, but some files failed: ${warnings.join(", ")}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setDriveError("Google Drive access was revoked -- please reconnect in Settings.");
      } else {
        setDriveError(err instanceof ApiError ? err.message : "Save to Drive failed.");
      }
    } finally {
      setSavingToDrive(false);
    }
  }

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
    <div className="w-full px-6 py-10">
      <div className="mx-auto max-w-2xl">
        <div className="flex items-center gap-4">
          <Link
            href={`/dashboard/${job?.job_type === "audio" ? "audio" : "video"}`}
            className="text-sm text-ink-soft hover:text-accent hover:underline"
          >
            ← Back to {job?.job_type === "audio" ? "Audio" : "Video"}
          </Link>
          {job && job.status === "done" && !job.retention_expired && (
            <Link href="/documents" className="text-sm text-ink-soft hover:text-accent hover:underline">
              All documents →
            </Link>
          )}
        </div>

        <div className="mt-4 flex items-center gap-2.5">
          {job && (
            <span
              className={`flex h-8 w-8 shrink-0 items-center justify-center ${
                job.job_type === "audio" ? "bg-paper-shade text-ink-soft" : "bg-accent-soft text-accent"
              }`}
              title={job.job_type === "audio" ? "Audio transcript" : "Video document"}
            >
              {job.job_type === "audio" ? <MicrophoneIcon className="h-4 w-4" /> : <VideoCameraIcon className="h-4 w-4" />}
            </span>
          )}
          <h1 className="truncate font-display text-2xl font-bold tracking-tight text-ink">
            {job ? displayTitle(job) : "Job detail"}
          </h1>
        </div>

        {error && <p className="mt-4 text-sm text-status-error">{error}</p>}

        {!error && !job && <p className="mt-4 text-sm text-ink-soft">Loading...</p>}

        {job && (
          <Card className="mt-6 p-6">
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-ink-soft">Status</dt>
              <dd className="font-medium text-ink">{job.status.replaceAll("_", " ")}</dd>
            </div>
            {job.status === "processing" && job.progress_stage && (
              <div className="flex justify-between">
                <dt className="text-ink-soft">Stage</dt>
                <dd className="font-medium text-ink">{job.progress_stage.replaceAll("_", " ")}</dd>
              </div>
            )}
            <div className="flex justify-between">
              <dt className="text-ink-soft">Created</dt>
              <dd className="font-medium text-ink">{new Date(job.created_at).toLocaleString()}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-soft">Type</dt>
              <dd className="font-medium text-ink capitalize">{job.job_type}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-soft">{job.job_type === "audio" ? "Audio length" : "Video length"}</dt>
              <dd className="font-medium text-ink">{formatDuration(job.duration_seconds)}</dd>
            </div>
            {(job.status === "done" || job.status === "failed") && (
              <div className="flex justify-between">
                <dt className="text-ink-soft">Took</dt>
                <dd className="font-medium text-ink">{formatElapsed(job)}</dd>
              </div>
            )}
            <div className="flex justify-between">
              <dt className="text-ink-soft">Cost</dt>
              <dd className="font-medium text-ink">{formatCents(job.billed_cents)}</dd>
            </div>
          </dl>

          {job.status === "failed" && job.error && (
            <p className="mt-4 bg-status-error-soft p-3 text-sm text-status-error">{job.error}</p>
          )}

          {job.status === "failed" && (
            <div className="mt-4">
              <Button onClick={handleRetry} disabled={retrying}>
                {retrying ? "Retrying..." : "Retry"}
              </Button>
              {retryError && <p className="mt-2 text-sm text-status-error">{retryError}</p>}
            </div>
          )}

          {job.status === "done" && job.retention_expired && (
            <p className="mt-4 bg-paper-shade p-3 text-sm text-ink-soft">
              This document was deleted per the 7-day retention policy and can no longer be downloaded.
            </p>
          )}

          {job.status === "done" && !job.retention_expired && (
            <div className="mt-6 flex flex-wrap gap-2">
              {job.document_url && (
                <Button onClick={() => downloadAuthenticated(job.document_url!, `${job.job_id}.md`)}>
                  <MarkdownFileIcon className="h-5 w-5" />
                  Download Markdown
                </Button>
              )}
              {job.document_bundle_url && (
                <Button variant="outline" onClick={() => downloadAuthenticated(job.document_bundle_url!, `${job.job_id}.zip`)}>
                  <ArchiveIcon className="h-5 w-5 text-amber-600" />
                  Download Markdown + images (.zip)
                </Button>
              )}
              {job.document_docx_url && (
                <Button variant="outline" onClick={() => downloadAuthenticated(job.document_docx_url!, `${job.job_id}.docx`)}>
                  <WordFileIcon className="h-5 w-5 text-blue-700" />
                  Download Word
                </Button>
              )}
              {job.document_pdf_url && (
                <Button variant="outline" onClick={() => downloadAuthenticated(job.document_pdf_url!, `${job.job_id}.pdf`)}>
                  <PdfFileIcon className="h-5 w-5 text-ink-soft" />
                  Download PDF
                </Button>
              )}
              {job.document_transcript_json_url && (
                <Button
                  variant="outline"
                  onClick={() => downloadAuthenticated(job.document_transcript_json_url!, `${job.job_id}.transcript.json`)}
                >
                  <JsonFileIcon className="h-5 w-5 text-emerald-600" />
                  Download Transcript JSON
                </Button>
              )}
              {driveConnected ? (
                <Button variant="outline" onClick={handleSaveToDrive} disabled={savingToDrive}>
                  <DriveIcon className="h-5 w-5" />
                  {savingToDrive ? "Saving..." : "Save to Drive"}
                </Button>
              ) : (
                <Link
                  href="/settings/integrations"
                  title="Connect Google Drive in Settings to enable this"
                  className={buttonClassName("outline", "text-ink-soft")}
                >
                  <DriveIcon className="h-5 w-5" />
                  Save to Drive
                </Link>
              )}
            </div>
          )}
          {driveError && <p className="mt-3 text-sm text-status-error">{driveError}</p>}

          {job.status === "done" && !job.retention_expired && <ShareControl job={job} onUpdated={setJob} />}

          {job.job_type === "audio" && job.status === "done" && job.document_transcript_json_url && (
            <TranscriptViewer jobId={job.job_id} />
          )}

          {job.status === "done" && !job.retention_expired && job.document_url && (
            <DocumentPreview markdownUrl={job.document_url} />
          )}
        </Card>
        )}
      </div>

      {job && job.status === "awaiting_review" && (
        <div className="mt-6">
          <FrameReviewPanel job={job} onSubmitted={setJob} />
        </div>
      )}
    </div>
  );
}
