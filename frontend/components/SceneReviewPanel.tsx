"use client";

import { useEffect, useState } from "react";

import Button from "@/components/Button";
import Card from "@/components/Card";
import { API_BASE_URL, apiFetch, ApiError } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { formatTimestamp, type Job, type SceneReviewItem } from "@/lib/jobs";

/** Fetches one scene's chosen candidate asset as an authenticated blob and
 * renders it -- same auth-fetch-blob technique as AuthenticatedImage,
 * generalized here to also handle video candidates and the "none" (gradient
 * card, nothing to preview) media kind. */
function ScenePreview({ jobId, scene }: { jobId: string; scene: SceneReviewItem }) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const hasMedia = scene.media_kind !== "none" && scene.candidate_count > 0;

  useEffect(() => {
    if (!hasMedia) {
      setObjectUrl(null);
      return;
    }
    let cancelled = false;
    let url: string | null = null;
    setObjectUrl(null);
    setFailed(false);

    const token = getToken();
    const src = `${API_BASE_URL}/api/jobs/${jobId}/scene-review/media/${scene.id}?candidate_index=${scene.chosen_index}`;
    fetch(src, { headers: token ? { Authorization: `Bearer ${token}` } : undefined })
      .then((res) => {
        if (!res.ok) throw new Error(res.statusText);
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setObjectUrl(url);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [jobId, scene.id, scene.chosen_index, hasMedia]);

  if (!hasMedia) {
    return (
      <div className="flex h-40 w-full items-center justify-center bg-paper-shade px-3 text-center text-xs text-ink-soft">
        No stock match -- plain gradient card
      </div>
    );
  }
  if (failed) {
    return <div className="flex h-40 w-full items-center justify-center bg-paper-shade text-xs text-ink-soft">Failed to load</div>;
  }
  if (!objectUrl) {
    return <div className="h-40 w-full animate-pulse bg-paper-shade" />;
  }
  return scene.media_kind === "video" ? (
    <video src={objectUrl} className="h-40 w-full object-cover" muted loop autoPlay playsInline />
  ) : (
    <img src={objectUrl} alt={`Scene ${scene.id} visual`} className="h-40 w-full object-cover" />
  );
}

export default function SceneReviewPanel({ job, onSubmitted }: { job: Job; onSubmitted: (job: Job) => void }) {
  const [scenes, setScenes] = useState<SceneReviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<{ scenes: SceneReviewItem[] }>(`/api/jobs/${job.job_id}/scene-review`)
      .then((data) => setScenes(data.scenes.sort((a, b) => a.start_ts - b.start_ts)))
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "Failed to load scenes for review.");
      });
  }, [job.job_id]);

  function setHeadline(id: number, headline: string) {
    setScenes((prev) => prev && prev.map((s) => (s.id === id ? { ...s, headline } : s)));
  }

  function cycleCandidate(id: number) {
    setScenes(
      (prev) =>
        prev &&
        prev.map((s) =>
          s.id === id && s.candidate_count > 0 ? { ...s, chosen_index: (s.chosen_index + 1) % s.candidate_count } : s,
        ),
    );
  }

  async function handleContinue() {
    if (!scenes) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const updated = await apiFetch<Job>(`/api/jobs/${job.job_id}/scene-review`, {
        method: "POST",
        body: JSON.stringify({
          items: scenes.map((s) => ({ id: s.id, headline: s.headline, chosen_index: s.chosen_index })),
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
  if (!scenes) return <p className="mt-6 text-sm text-ink-soft">Loading scenes...</p>;

  return (
    <div className="mt-6">
      <div>
        <h2 className="font-display text-lg font-bold text-ink">Review scenes</h2>
        <p className="mt-1 text-sm text-ink-soft">
          Edit any on-screen headline, or cycle to a different stock visual, before the final video is rendered.
        </p>
      </div>

      {scenes.length === 0 ? (
        <p className="mt-4 text-sm text-ink-soft">No scenes were generated.</p>
      ) : (
        <>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {scenes.map((scene) => (
              <Card key={scene.id} className="overflow-hidden">
                <ScenePreview jobId={job.job_id} scene={scene} />
                <div className="space-y-2 p-3">
                  <div className="flex items-center justify-between text-xs text-ink-soft">
                    <span className="font-mono">
                      {formatTimestamp(scene.start_ts)}–{formatTimestamp(scene.end_ts)}
                    </span>
                    {scene.candidate_count > 1 && (
                      <button
                        onClick={() => cycleCandidate(scene.id)}
                        className="text-xs text-ink-soft hover:text-accent hover:underline"
                      >
                        Swap visual ({scene.chosen_index + 1}/{scene.candidate_count})
                      </button>
                    )}
                  </div>
                  <input
                    type="text"
                    value={scene.headline}
                    onChange={(e) => setHeadline(scene.id, e.target.value)}
                    className="w-full border-2 border-line bg-paper px-2 py-1 text-sm text-ink"
                  />
                </div>
              </Card>
            ))}
          </div>

          <div className="mt-6 flex items-center gap-4">
            <Button onClick={handleContinue} disabled={submitting}>
              {submitting ? "Continuing..." : "Continue"}
            </Button>
            <p className="text-sm text-ink-soft">{scenes.length} scenes</p>
          </div>
          {submitError && <p className="mt-2 text-sm text-status-error">{submitError}</p>}
        </>
      )}
    </div>
  );
}
