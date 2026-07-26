"use client";

import Link from "next/link";
import { useState } from "react";

import { ArchiveIcon, DriveIcon, MarkdownFileIcon, MicrophoneIcon, PdfFileIcon, VideoCameraIcon, WordFileIcon } from "@/components/icons";
import { apiFetch, ApiError, downloadAuthenticated } from "@/lib/api";
import { displayTitle, formatDuration, type Job } from "@/lib/jobs";
import { useDriveStatus } from "@/lib/useDriveStatus";

export default function DocumentCard({ job }: { job: Job }) {
  const TypeIcon = job.job_type === "audio" ? MicrophoneIcon : VideoCameraIcon;
  const driveConnected = useDriveStatus();
  const [savingToDrive, setSavingToDrive] = useState(false);
  const [driveError, setDriveError] = useState<string | null>(null);

  async function handleSaveToDrive() {
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

  return (
    <div className="flex flex-col rounded-2xl border border-brand-border bg-surface p-4 shadow-soft transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-2">
        <span
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
            job.job_type === "audio" ? "bg-brand-navy-soft text-brand-navy" : "bg-brand-amber-soft text-brand-amber-dark"
          }`}
          title={job.job_type === "audio" ? "Audio transcript" : "Video document"}
        >
          <TypeIcon className="h-4 w-4" />
        </span>
        {job.retention_expired && (
          <span className="shrink-0 text-xs text-muted" title="Documents aren't guaranteed past 7 days">
            Expired
          </span>
        )}
      </div>

      <Link
        href={`/dashboard/jobs/${job.job_id}`}
        className="mt-3 line-clamp-2 text-sm font-medium text-foreground hover:text-brand-amber-dark hover:underline"
      >
        {displayTitle(job)}
      </Link>
      <p className="mt-1 text-xs text-muted">
        {new Date(job.created_at).toLocaleDateString()} &middot; {formatDuration(job.duration_seconds)}
      </p>

      {!job.retention_expired && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-brand-border pt-3 text-muted">
          {job.document_url && (
            <button
              onClick={() => downloadAuthenticated(job.document_url!, `${job.job_id}.md`)}
              title="Download Markdown"
              className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors hover:bg-brand-navy-soft hover:text-brand-amber-dark"
            >
              <MarkdownFileIcon className="h-4 w-4 text-foreground" />
              Markdown
            </button>
          )}
          {job.document_bundle_url && (
            <button
              onClick={() => downloadAuthenticated(job.document_bundle_url!, `${job.job_id}.zip`)}
              title="Download Markdown + images (.zip)"
              className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors hover:bg-brand-navy-soft hover:text-brand-amber-dark"
            >
              <ArchiveIcon className="h-4 w-4 text-amber-600" />
              ZIP
            </button>
          )}
          {job.document_docx_url && (
            <button
              onClick={() => downloadAuthenticated(job.document_docx_url!, `${job.job_id}.docx`)}
              title="Download Word"
              className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors hover:bg-brand-navy-soft hover:text-brand-amber-dark"
            >
              <WordFileIcon className="h-4 w-4 text-blue-700" />
              Word
            </button>
          )}
          {job.document_pdf_url && (
            <button
              onClick={() => downloadAuthenticated(job.document_pdf_url!, `${job.job_id}.pdf`)}
              title="Download PDF"
              className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors hover:bg-brand-navy-soft hover:text-brand-amber-dark"
            >
              <PdfFileIcon className="h-4 w-4 text-red-600" />
              PDF
            </button>
          )}
          {driveConnected ? (
            <button
              onClick={handleSaveToDrive}
              disabled={savingToDrive}
              title="Save to Google Drive"
              className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors hover:bg-brand-navy-soft hover:text-brand-amber-dark disabled:cursor-default disabled:opacity-50"
            >
              <DriveIcon className="h-4 w-4" />
              {savingToDrive ? "Saving..." : "Drive"}
            </button>
          ) : (
            <Link
              href="/settings/integrations"
              title="Connect Google Drive in Settings to enable this"
              className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-muted/40 transition-colors hover:bg-brand-navy-soft"
            >
              <DriveIcon className="h-4 w-4" />
              Drive
            </Link>
          )}
        </div>
      )}
      {driveError && <p className="mt-2 text-xs text-red-600">{driveError}</p>}
    </div>
  );
}
