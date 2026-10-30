"use client";

import { useEffect, useState } from "react";

import Button from "@/components/Button";
import { apiFetch, ApiError } from "@/lib/api";
import type { Job, ResearchTopic } from "@/lib/jobs";

type EditableTopic = ResearchTopic & { included: boolean };

export default function TopicReviewPanel({ job, onSubmitted }: { job: Job; onSubmitted: (job: Job) => void }) {
  const [topics, setTopics] = useState<EditableTopic[] | null>(null);
  const [maxTopics, setMaxTopics] = useState(8);
  const [error, setError] = useState<string | null>(null);
  const [newTopic, setNewTopic] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<{ topics: ResearchTopic[]; max_topics: number }>(`/api/jobs/${job.job_id}/topics`)
      .then((data) => {
        setTopics(data.topics.map((t) => ({ ...t, included: true })));
        setMaxTopics(data.max_topics);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load topics."));
  }, [job.job_id]);

  function update(index: number, patch: Partial<EditableTopic>) {
    setTopics((prev) => prev && prev.map((t, i) => (i === index ? { ...t, ...patch } : t)));
  }

  function addTopic() {
    const text = newTopic.trim();
    if (!text) return;
    setTopics((prev) => prev && [...prev, { topic: text, context: "", included: true }]);
    setNewTopic("");
  }

  async function handleContinue() {
    if (!topics) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const updated = await apiFetch<Job>(`/api/jobs/${job.job_id}/topics`, {
        method: "POST",
        body: JSON.stringify({
          topics: topics.filter((t) => t.included && t.topic.trim()).map(({ topic, context }) => ({ topic, context })),
        }),
      });
      onSubmitted(updated);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Failed to submit topics.");
    } finally {
      setSubmitting(false);
    }
  }

  if (error) return <p className="mt-6 text-sm text-status-error">{error}</p>;
  if (!topics) return <p className="mt-6 text-sm text-ink-soft">Loading topics...</p>;

  const selectedCount = topics.filter((t) => t.included && t.topic.trim()).length;
  const overLimit = selectedCount > maxTopics;

  return (
    <div className="mt-6">
      <h2 className="font-display text-lg font-bold text-ink">Choose what to research</h2>
      <p className="mt-1 text-sm text-ink-soft">
        These are topics from your video that web research could add to. Edit the wording, untick any you don&apos;t
        need, or add your own -- up to {maxTopics}. Research starts when you continue.
      </p>

      <ul className="mt-4 space-y-3">
        {topics.map((t, i) => (
          <li
            key={i}
            className={`rounded-lg border p-3 transition-colors ${
              t.included ? "border-line bg-paper" : "border-line bg-paper opacity-60"
            }`}
          >
            <div className="flex items-start gap-3">
              <input
                type="checkbox"
                checked={t.included}
                onChange={(e) => update(i, { included: e.target.checked })}
                aria-label={`Research "${t.topic}"`}
                className="mt-2 h-4 w-4 shrink-0 accent-[var(--accent)]"
              />
              <div className="min-w-0 flex-1">
                <input
                  type="text"
                  value={t.topic}
                  maxLength={200}
                  onChange={(e) => update(i, { topic: e.target.value })}
                  className="w-full rounded-md border border-line bg-paper px-2 py-1 text-sm font-medium text-ink outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft"
                />
                <p className="mt-1 text-xs text-ink-soft">
                  {t.context ? `From the video: ${t.context}` : "Added by you"}
                </p>
              </div>
            </div>
          </li>
        ))}
      </ul>

      <div className="mt-4 flex gap-2">
        <input
          type="text"
          value={newTopic}
          maxLength={200}
          onChange={(e) => setNewTopic(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addTopic();
            }
          }}
          placeholder="Add your own topic or question..."
          className="flex-1 rounded-md border border-line bg-paper px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft"
        />
        <Button type="button" onClick={addTopic} disabled={!newTopic.trim()}>
          Add
        </Button>
      </div>

      <div className="mt-6 flex items-center justify-between gap-4">
        <p className={`text-sm ${overLimit ? "text-status-error" : "text-ink-soft"}`}>
          {selectedCount} of {maxTopics} topic{selectedCount === 1 ? "" : "s"} selected
        </p>
        <Button onClick={handleContinue} disabled={submitting || selectedCount === 0 || overLimit}>
          {submitting ? "Starting..." : "Continue"}
        </Button>
      </div>
      {submitError && <p className="mt-3 text-sm text-status-error">{submitError}</p>}
    </div>
  );
}
