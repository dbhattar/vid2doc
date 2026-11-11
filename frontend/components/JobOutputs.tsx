"use client";

import { useEffect, useState } from "react";

import AuthenticatedImage from "@/components/AuthenticatedImage";
import Button from "@/components/Button";
import Card from "@/components/Card";
import DocumentPreview from "@/components/DocumentPreview";
import MoreDocuments from "@/components/MoreDocuments";
import TranscriptViewer from "@/components/TranscriptViewer";
import { apiFetch, ApiError, downloadAuthenticated } from "@/lib/api";
import type { Job } from "@/lib/jobs";

type Tab = "document" | "transcript" | "images" | "more";

const TABS: { key: Tab; label: string }[] = [
  { key: "document", label: "Document" },
  { key: "transcript", label: "Transcript" },
  { key: "images", label: "Images" },
  { key: "more", label: "More documents" },
];

type ImageList = { images: { name: string; url: string }[] };

function Images({ job }: { job: Job }) {
  const [images, setImages] = useState<ImageList["images"] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<ImageList>(`/api/jobs/${job.job_id}/images`)
      .then((d) => setImages(d.images))
      .catch((err) =>
        setError(
          err instanceof ApiError ? err.message : "Couldn't load the images.",
        ),
      );
  }, [job.job_id]);

  if (error) return <p className="text-sm text-status-error">{error}</p>;
  if (!images) return <p className="text-sm text-ink-soft">Loading...</p>;
  if (images.length === 0) {
    return (
      <p className="text-sm text-ink-soft">
        {job.extract_frames === false
          ? "Frame extraction was skipped for this video, so there are no images."
          : "No slides, diagrams or tables were found in this video."}
      </p>
    );
  }
  const zipUrl = job.document_bundle_url?.replace(/bundle\.zip$/, "images.zip");
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-ink-soft">
          {images.length} captured from the video.
        </p>
        {zipUrl && (
          <Button
            variant="outline"
            onClick={() =>
              downloadAuthenticated(zipUrl, `${job.job_id}-images.zip`)
            }
          >
            Download images (.zip)
          </Button>
        )}
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {images.map((image) => (
          <AuthenticatedImage
            key={image.name}
            src={image.url}
            alt={image.name}
            className="w-full rounded-md border border-line"
          />
        ))}
      </div>
    </div>
  );
}

/** A finished video's initial set -- the formatted document, the transcript
 * and the images -- plus the documents that can be made from it. */
export default function JobOutputs({ job }: { job: Job }) {
  const [tab, setTab] = useState<Tab>("document");
  const transcriptJson = job.document_transcript_json_url;
  const transcriptTxt = transcriptJson?.replace(
    /transcript\.json$/,
    "transcript.txt",
  );

  return (
    <Card className="p-6">
      <div role="tablist" className="flex flex-wrap gap-1 border-b border-line">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-semibold transition-colors ${
              tab === key
                ? "border-accent text-ink"
                : "border-transparent text-ink-soft hover:text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mt-4">
        {tab === "document" && job.document_url && (
          <DocumentPreview markdownUrl={job.document_url} bordered={false} />
        )}

        {tab === "transcript" &&
          (transcriptJson ? (
            <div>
              <div className="flex flex-wrap gap-2">
                {transcriptTxt && (
                  <Button
                    variant="outline"
                    onClick={() =>
                      downloadAuthenticated(
                        transcriptTxt,
                        `${job.job_id}-transcript.txt`,
                      )
                    }
                  >
                    Download text
                  </Button>
                )}
                <Button
                  variant="outline"
                  onClick={() =>
                    downloadAuthenticated(
                      transcriptJson,
                      `${job.job_id}.transcript.json`,
                    )
                  }
                >
                  Download JSON
                </Button>
              </div>
              <TranscriptViewer jobId={job.job_id} readOnly />
            </div>
          ) : (
            <p className="text-sm text-ink-soft">
              No transcript is available for this video.
            </p>
          ))}

        {tab === "images" && <Images job={job} />}

        {tab === "more" && <MoreDocuments jobId={job.job_id} />}
      </div>
    </Card>
  );
}
