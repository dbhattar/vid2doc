"use client";

import { useEffect, useMemo, useState } from "react";

import AuthenticatedImage from "@/components/AuthenticatedImage";
import Button from "@/components/Button";
import Card from "@/components/Card";
import { API_BASE_URL, apiFetch, ApiError, downloadAuthenticated } from "@/lib/api";
import { formatTimestamp, type Job, type ReviewItem } from "@/lib/jobs";

const CONTENT_TYPE_LABELS: Record<string, string> = {
  slide: "Slides",
  diagram: "Diagrams",
  whiteboard: "Whiteboards",
  code: "Code",
  photo: "Photos",
  chart: "Charts",
  table: "Tables",
};

/** A table item has no `content_type` of its own (see ReviewItem) --
 * treat "table" as its content type for grouping/filtering purposes. */
function contentTypeOf(item: ReviewItem): string {
  return item.kind === "table" ? "table" : item.content_type ?? "other";
}

export default function FrameReviewPanel({ job, onSubmitted }: { job: Job; onSubmitted: (job: Job) => void }) {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [savingTableId, setSavingTableId] = useState<number | null>(null);

  useEffect(() => {
    apiFetch<{ items: ReviewItem[] }>(`/api/jobs/${job.job_id}/review`)
      .then((data) => setItems(data.items.sort((a, b) => a.timestamp - b.timestamp)))
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "Failed to load frames for review.");
      });
  }, [job.job_id]);

  const contentTypes = useMemo(() => {
    if (!items) return [];
    return Array.from(new Set(items.map(contentTypeOf)));
  }, [items]);

  const visibleItems = useMemo(() => {
    if (!items) return [];
    return filter === "all" ? items : items.filter((item) => contentTypeOf(item) === filter);
  }, [items, filter]);

  function setIncluded(id: number, included: boolean) {
    setItems((prev) => prev && prev.map((item) => (item.id === id ? { ...item, included } : item)));
  }

  // Select/deselect all applies to the currently visible (filtered) set --
  // switching filters and hitting "Select all" shouldn't silently re-include
  // frames the user already ruled out under a different filter.
  function setAllVisibleIncluded(included: boolean) {
    const visibleIds = new Set(visibleItems.map((item) => item.id));
    setItems((prev) => prev && prev.map((item) => (visibleIds.has(item.id) ? { ...item, included } : item)));
  }

  async function handleSaveTableMarkdown(item: ReviewItem) {
    setSavingTableId(item.id);
    setSubmitError(null);
    try {
      await downloadAuthenticated(
        `${API_BASE_URL}/api/jobs/${job.job_id}/review/tables/${item.id}/markdown`,
        `table-${item.id}.md`
      );
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Failed to save table.");
    } finally {
      setSavingTableId(null);
    }
  }

  async function handleContinue() {
    if (!items) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const updated = await apiFetch<Job>(`/api/jobs/${job.job_id}/review`, {
        method: "POST",
        body: JSON.stringify({
          items: items.map((item) => ({ id: item.id, included: item.included })),
        }),
      });
      onSubmitted(updated);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Failed to submit review.");
    } finally {
      setSubmitting(false);
    }
  }

  if (error) return <p className="mt-6 text-sm text-status-error">{error}</p>;
  if (!items) return <p className="mt-6 text-sm text-ink-soft">Loading frames...</p>;

  const includedCount = items.filter((item) => item.included).length;

  return (
    <div className="mt-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="font-display text-lg font-bold text-ink">Review frames</h2>
          <p className="mt-1 text-sm text-ink-soft">
            All {items.length} frame{items.length === 1 ? "" : "s"} are included by default -- uncheck any you'd rather
            skip before they're placed in the document.
          </p>
        </div>
      </div>

      {items.length === 0 ? (
        <p className="mt-4 text-sm text-ink-soft">No candidate frames were found.</p>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            {contentTypes.length > 1 ? (
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => setFilter("all")}
                  className={`border-2 px-3 py-1 font-mono text-xs font-medium uppercase tracking-wide ${
                    filter === "all" ? "border-ink bg-ink text-paper" : "border-line text-ink-soft hover:border-ink"
                  }`}
                >
                  All
                </button>
                {contentTypes.map((type) => (
                  <button
                    key={type}
                    onClick={() => setFilter(type)}
                    className={`border-2 px-3 py-1 font-mono text-xs font-medium uppercase tracking-wide ${
                      filter === type ? "border-ink bg-ink text-paper" : "border-line text-ink-soft hover:border-ink"
                    }`}
                  >
                    {CONTENT_TYPE_LABELS[type] ?? type}
                  </button>
                ))}
              </div>
            ) : (
              <div />
            )}

            <div className="flex gap-3 text-sm">
              <button onClick={() => setAllVisibleIncluded(true)} className="text-ink-soft hover:text-accent hover:underline">
                Select all
              </button>
              <button onClick={() => setAllVisibleIncluded(false)} className="text-ink-soft hover:text-accent hover:underline">
                Deselect all
              </button>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
            {visibleItems.map((item) => (
              <Card key={item.id} className={`overflow-hidden ${item.included ? "" : "opacity-50"}`}>
                <AuthenticatedImage
                  src={`${API_BASE_URL}/api/jobs/${job.job_id}/review/frames/${item.id}`}
                  alt={`${CONTENT_TYPE_LABELS[contentTypeOf(item)] ?? item.kind} frame at ${formatTimestamp(item.timestamp)}`}
                  className="h-40 w-full object-cover"
                />
                <div className="space-y-2 p-3">
                  <div className="flex items-center justify-between text-xs text-ink-soft">
                    <span className="font-mono">{formatTimestamp(item.timestamp)}</span>
                    <span className="font-mono uppercase tracking-wide">{CONTENT_TYPE_LABELS[contentTypeOf(item)] ?? item.kind}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2 text-sm text-ink">
                      <input
                        type="checkbox"
                        checked={item.included}
                        onChange={(e) => setIncluded(item.id, e.target.checked)}
                      />
                      Include
                    </label>
                    {item.kind === "table" && (
                      <button
                        onClick={() => handleSaveTableMarkdown(item)}
                        disabled={savingTableId === item.id}
                        className="text-xs text-ink-soft hover:text-accent hover:underline disabled:cursor-default disabled:opacity-50"
                      >
                        {savingTableId === item.id ? "Saving..." : "Save as Markdown"}
                      </button>
                    )}
                  </div>
                </div>
              </Card>
            ))}
          </div>

          <div className="mt-6 flex items-center gap-4">
            <Button onClick={handleContinue} disabled={submitting}>
              {submitting ? "Continuing..." : "Continue"}
            </Button>
            <p className="text-sm text-ink-soft">
              {includedCount} of {items.length} included
            </p>
          </div>
          {submitError && <p className="mt-2 text-sm text-status-error">{submitError}</p>}
        </>
      )}
    </div>
  );
}
