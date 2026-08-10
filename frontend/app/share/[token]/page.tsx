"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import Button from "@/components/Button";
import Card from "@/components/Card";
import DocumentPreview from "@/components/DocumentPreview";
import { ArchiveIcon, JsonFileIcon, MarkdownFileIcon, MicrophoneIcon, PdfFileIcon, VideoCameraIcon, WordFileIcon } from "@/components/icons";
import { apiFetch, ApiError, downloadAuthenticated } from "@/lib/api";
import { formatDuration, type PublicJobView } from "@/lib/jobs";

/** Public, unauthenticated view of a job someone chose to share (see
 * ShareControl). Lives outside the (app) route group on purpose -- no
 * Sidebar/TopBar/auth redirect, no billing/Retry/Delete/Drive actions, and a
 * 401/404 here must never bounce the visitor to /login. */
export default function SharedDocumentPage() {
  const params = useParams<{ token: string }>();
  const [job, setJob] = useState<PublicJobView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<PublicJobView>(`/api/share/${params.token}`)
      .then(setJob)
      .catch((err) => {
        setError(
          err instanceof ApiError && err.status === 404
            ? "This link is invalid or sharing has been turned off."
            : "Failed to load this document."
        );
      });
  }, [params.token]);

  return (
    <div className="min-h-screen bg-paper">
      <div className="w-full px-6 py-10">
        <div className="mx-auto max-w-2xl">
          <a href="https://framewrite.cc" className="font-display text-lg font-bold text-ink">
            Framewrite
          </a>

          {error && <p className="mt-6 text-sm text-status-error">{error}</p>}
          {!error && !job && <p className="mt-6 text-sm text-ink-soft">Loading...</p>}

          {job && (
            <>
              <div className="mt-4 flex items-center gap-2.5">
                <span
                  className={`flex h-8 w-8 shrink-0 items-center justify-center ${
                    job.job_type === "audio" ? "bg-paper-shade text-ink-soft" : "bg-accent-soft text-accent"
                  }`}
                >
                  {job.job_type === "audio" ? <MicrophoneIcon className="h-4 w-4" /> : <VideoCameraIcon className="h-4 w-4" />}
                </span>
                <h1 className="truncate font-display text-2xl font-bold tracking-tight text-ink">
                  {job.title?.trim() || "Shared document"}
                </h1>
              </div>
              <p className="mt-1 text-sm text-ink-soft">
                {formatDuration(job.duration_seconds)} &middot; shared from Framewrite
              </p>

              <Card className="mt-6 p-6">
                <div className="flex flex-wrap gap-2">
                  {job.document_url && (
                    <Button onClick={() => downloadAuthenticated(job.document_url!, "document.md")}>
                      <MarkdownFileIcon className="h-5 w-5" />
                      Download Markdown
                    </Button>
                  )}
                  {job.document_bundle_url && (
                    <Button variant="outline" onClick={() => downloadAuthenticated(job.document_bundle_url!, "document.zip")}>
                      <ArchiveIcon className="h-5 w-5 text-amber-600" />
                      Download Markdown + images (.zip)
                    </Button>
                  )}
                  {job.document_docx_url && (
                    <Button variant="outline" onClick={() => downloadAuthenticated(job.document_docx_url!, "document.docx")}>
                      <WordFileIcon className="h-5 w-5 text-blue-700" />
                      Download Word
                    </Button>
                  )}
                  {job.document_pdf_url && (
                    <Button variant="outline" onClick={() => downloadAuthenticated(job.document_pdf_url!, "document.pdf")}>
                      <PdfFileIcon className="h-5 w-5 text-ink-soft" />
                      Download PDF
                    </Button>
                  )}
                  {job.document_transcript_json_url && (
                    <Button
                      variant="outline"
                      onClick={() => downloadAuthenticated(job.document_transcript_json_url!, "transcript.json")}
                    >
                      <JsonFileIcon className="h-5 w-5 text-emerald-600" />
                      Download Transcript JSON
                    </Button>
                  )}
                </div>

                {job.document_url && <DocumentPreview markdownUrl={job.document_url} />}
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
