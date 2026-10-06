"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { buttonClassName } from "@/components/Button";
import Card from "@/components/Card";
import DocumentPreview from "@/components/DocumentPreview";
import { JsonFileIcon, MarkdownFileIcon, PdfFileIcon, VideoCameraIcon, WordFileIcon } from "@/components/icons";
import { apiFetch, ApiError } from "@/lib/api";
import { formatDuration, type PublicShowcaseItem } from "@/lib/jobs";

/** Public, unauthenticated view of one public-showcase item (see
 * PublicConsentControl, backend's app/public_jobs.py). Lives outside the
 * (app) route group on purpose -- no Sidebar/TopBar/auth redirect, no
 * owner-only actions, and a 404 here must never bounce the visitor to
 * /login -- same reasoning as frontend/app/share/[token]/page.tsx, which
 * this closely mirrors.
 *
 * Download links are plain `<a href download>` tags, not this app's usual
 * downloadAuthenticated -- the document lives on an external S3/CDN domain
 * (app/config.py's PUBLIC_ARCHIVE_BASE_URL), and downloadAuthenticated's
 * fetch-as-blob technique would both attach a Bearer token that domain has
 * no reason to receive and require it to have CORS configured just to let
 * JS read the response body. A native download link needs neither: the
 * browser downloads it directly. See DocumentPreview's `external` prop for
 * the same reasoning applied to inline preview instead of download. The
 * video player is a plain `<video src>` for the same reason -- it's a
 * public S3 object, so the browser can stream it directly with no auth. */
export default function ShowcaseItemPage() {
  const params = useParams<{ job_id: string }>();
  const [item, setItem] = useState<PublicShowcaseItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<PublicShowcaseItem>(`/api/public/showcase/${params.job_id}`)
      .then(setItem)
      .catch((err) => {
        setError(
          err instanceof ApiError && err.status === 404
            ? "This document isn't part of the public showcase."
            : "Failed to load this document."
        );
      });
  }, [params.job_id]);

  return (
    <div className="min-h-screen bg-paper">
      <div className="w-full px-6 py-10">
        <div className="mx-auto max-w-2xl">
          <a href="https://framewrite.cc" className="font-display text-lg font-bold text-ink">
            Framewrite
          </a>

          {error && <p className="mt-6 text-sm text-status-error">{error}</p>}
          {!error && !item && <p className="mt-6 text-sm text-ink-soft">Loading...</p>}

          {item && (
            <>
              <div className="mt-4 flex items-center gap-2.5">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center bg-accent-soft text-accent">
                  <VideoCameraIcon className="h-4 w-4" />
                </span>
                <h1 className="truncate font-display text-2xl font-bold tracking-tight text-ink">
                  {item.title?.trim() || "Public showcase document"}
                </h1>
              </div>
              <p className="mt-1 text-sm text-ink-soft">
                {formatDuration(item.duration_seconds)} &middot; featured on Framewrite
              </p>

              {item.video_url && (
                <Card className="mt-6 overflow-hidden p-0">
                  <video controls className="w-full" src={item.video_url} />
                </Card>
              )}

              <Card className="mt-6 p-6">
                <div className="flex flex-wrap gap-2">
                  {item.document_url && (
                    <a href={item.document_url} download className={buttonClassName("primary")}>
                      <MarkdownFileIcon className="h-5 w-5" />
                      Download Markdown
                    </a>
                  )}
                  {item.document_docx_url && (
                    <a href={item.document_docx_url} download className={buttonClassName("outline")}>
                      <WordFileIcon className="h-5 w-5 text-blue-700" />
                      Download Word
                    </a>
                  )}
                  {item.document_pdf_url && (
                    <a href={item.document_pdf_url} download className={buttonClassName("outline")}>
                      <PdfFileIcon className="h-5 w-5 text-ink-soft" />
                      Download PDF
                    </a>
                  )}
                  {item.document_transcript_json_url && (
                    <a href={item.document_transcript_json_url} download className={buttonClassName("outline")}>
                      <JsonFileIcon className="h-5 w-5 text-emerald-600" />
                      Download Transcript JSON
                    </a>
                  )}
                </div>

                {item.document_url && <DocumentPreview markdownUrl={item.document_url} external />}
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
