"use client";

import Link from "next/link";

import { ArchiveIcon, MarkdownFileIcon, MicrophoneIcon, PdfFileIcon, VideoCameraIcon, WordFileIcon } from "@/components/icons";
import { downloadAuthenticated } from "@/lib/api";
import { displayTitle, formatDuration, type Job } from "@/lib/jobs";

export default function DocumentCard({ job }: { job: Job }) {
  const TypeIcon = job.job_type === "audio" ? MicrophoneIcon : VideoCameraIcon;

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
        <div className="mt-3 flex flex-wrap items-center gap-1 border-t border-brand-border pt-3 text-muted">
          {job.document_url && (
            <button
              onClick={() => downloadAuthenticated(job.document_url!, `${job.job_id}.md`)}
              title="Download Markdown"
              className="rounded-md p-2 transition-colors hover:bg-brand-navy-soft hover:text-brand-amber-dark"
            >
              <MarkdownFileIcon className="h-6 w-6" />
            </button>
          )}
          {job.document_bundle_url && (
            <button
              onClick={() => downloadAuthenticated(job.document_bundle_url!, `${job.job_id}.zip`)}
              title="Download Markdown + images (.zip)"
              className="rounded-md p-2 transition-colors hover:bg-brand-navy-soft hover:text-brand-amber-dark"
            >
              <ArchiveIcon className="h-6 w-6" />
            </button>
          )}
          {job.document_docx_url && (
            <button
              onClick={() => downloadAuthenticated(job.document_docx_url!, `${job.job_id}.docx`)}
              title="Download Word"
              className="rounded-md p-2 transition-colors hover:bg-brand-navy-soft hover:text-brand-amber-dark"
            >
              <WordFileIcon className="h-6 w-6" />
            </button>
          )}
          {job.document_pdf_url && (
            <button
              onClick={() => downloadAuthenticated(job.document_pdf_url!, `${job.job_id}.pdf`)}
              title="Download PDF"
              className="rounded-md p-2 transition-colors hover:bg-brand-navy-soft hover:text-brand-amber-dark"
            >
              <PdfFileIcon className="h-6 w-6" />
            </button>
          )}
        </div>
      )}
    </div>
  );
}
