"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import Button from "@/components/Button";
import Card from "@/components/Card";
import StatusBadge from "@/components/StatusBadge";
import { apiFetch, ApiError } from "@/lib/api";
import {
  TRANSFORMATION_DESCRIPTIONS,
  TRANSFORMATION_LABELS,
  type DerivedDocuments,
  type DerivedOption,
  type Job,
} from "@/lib/jobs";

const POLL_MS = 3000;

function priceLabel(option: DerivedOption): string {
  if (option.cost_cents === 0) return "Free";
  const price = `$${(option.cost_cents / 100).toFixed(2)}`;
  return option.transformation === "research"
    ? `${price} -- includes web search`
    : price;
}

/** Notes, a study guide or research made from a finished video's or audio's transcript
 * (backend/app/routes/derived.py). Each one is its own job, so it has its own
 * progress and its own page; this panel starts them and tracks them. */
export default function MoreDocuments({ jobId }: { jobId: string }) {
  const [data, setData] = useState<DerivedDocuments | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [balanceShort, setBalanceShort] = useState(false);
  const [reviewTopics, setReviewTopics] = useState(false);

  const refresh = useCallback(
    () =>
      apiFetch<DerivedDocuments>(`/api/jobs/${jobId}/derived`)
        .then(setData)
        .catch((err) =>
          setLoadError(
            err instanceof ApiError
              ? err.message
              : "Couldn't load the documents made from this.",
          ),
        ),
    [jobId],
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Keep watching while anything is still being made.
  const anyActive =
    data?.documents.some(
      (d) => d.status === "queued" || d.status === "processing",
    ) ?? false;
  useEffect(() => {
    if (!anyActive) return;
    const timer = setTimeout(refresh, POLL_MS);
    return () => clearTimeout(timer);
  }, [anyActive, data, refresh]);

  function handleCreate(option: DerivedOption) {
    setCreating(option.transformation);
    setCreateError(null);
    setBalanceShort(false);
    apiFetch(`/api/jobs/${jobId}/derive`, {
      method: "POST",
      body: JSON.stringify({
        transformation: option.transformation,
        review_topics: option.transformation === "research" && reviewTopics,
      }),
    })
      .then(() => refresh())
      .catch((err) => {
        setCreateError(
          err instanceof ApiError
            ? err.message
            : "Couldn't start that document.",
        );
        setBalanceShort(err instanceof ApiError && err.status === 402);
      })
      .finally(() => setCreating(null));
  }

  if (loadError)
    return <p className="text-sm text-status-error">{loadError}</p>;
  if (!data) return <p className="text-sm text-ink-soft">Loading...</p>;

  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-soft">
        Make other documents from this video&apos;s transcript. They don&apos;t
        reprocess the video.
      </p>
      {!data.can_create && data.reason && (
        <p className="rounded-md bg-paper-shade p-3 text-sm text-ink-soft">
          {data.reason}
        </p>
      )}
      {createError && (
        <p className="text-sm text-status-error">
          {createError}{" "}
          {balanceShort && (
            <Link href="/settings/billing" className="underline">
              Add funds
            </Link>
          )}
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        {data.options.map((option) => {
          // The latest attempt of this type that isn't a dead end.
          const docs = data.documents.filter(
            (d) => d.transformation === option.transformation,
          );
          const live: Job | undefined = [...docs]
            .reverse()
            .find((d) => d.status !== "failed" && d.status !== "cancelled");
          const failed = !live
            ? [...docs].reverse().find((d) => d.status === "failed")
            : undefined;
          return (
            <Card key={option.transformation} className="flex flex-col p-4">
              <h3 className="font-display text-base font-bold text-ink">
                {TRANSFORMATION_LABELS[option.transformation]}
              </h3>
              <p className="mt-1 flex-1 text-sm text-ink-soft">
                {TRANSFORMATION_DESCRIPTIONS[option.transformation]}
              </p>
              {live ? (
                <div className="mt-4 flex items-center justify-between gap-2">
                  <StatusBadge job={live} />
                  <Link
                    href={`/dashboard/jobs/${live.job_id}`}
                    className="text-sm font-semibold text-accent hover:underline"
                  >
                    {live.status === "awaiting_review"
                      ? "Review topics"
                      : "Open"}
                  </Link>
                </div>
              ) : (
                <div className="mt-4">
                  {failed && (
                    <p className="mb-2 text-xs text-status-error">
                      {failed.error ?? "The last attempt failed."}
                    </p>
                  )}
                  {option.transformation === "research" && (
                    <label className="mb-2 flex items-start gap-2 text-xs text-ink">
                      <input
                        type="checkbox"
                        checked={reviewTopics}
                        onChange={(e) => setReviewTopics(e.target.checked)}
                        className="mt-0.5 h-3.5 w-3.5 rounded border-line accent-accent"
                      />
                      Let me choose the topics before research starts
                    </label>
                  )}
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs text-ink-soft">
                      {priceLabel(option)}
                    </span>
                    <Button
                      onClick={() => handleCreate(option)}
                      disabled={!data.can_create || creating !== null}
                    >
                      {creating === option.transformation
                        ? "Starting..."
                        : failed
                          ? "Try again"
                          : "Create"}
                    </Button>
                  </div>
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
