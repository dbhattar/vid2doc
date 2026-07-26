"use client";

import { useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { formatTimestamp, type TranscriptData } from "@/lib/jobs";

const SPEAKER_COLORS = [
  { avatar: "bg-blue-100 text-blue-700", bar: "bg-blue-400" },
  { avatar: "bg-emerald-100 text-emerald-700", bar: "bg-emerald-400" },
  { avatar: "bg-amber-100 text-amber-700", bar: "bg-amber-400" },
  { avatar: "bg-purple-100 text-purple-700", bar: "bg-purple-400" },
  { avatar: "bg-rose-100 text-rose-700", bar: "bg-rose-400" },
  { avatar: "bg-teal-100 text-teal-700", bar: "bg-teal-400" },
];

function colorFor(index: number) {
  return SPEAKER_COLORS[index % SPEAKER_COLORS.length];
}

function initials(name: string): string {
  return name.trim().slice(0, 2).toUpperCase() || "?";
}

export default function TranscriptViewer({ jobId }: { jobId: string }) {
  const [data, setData] = useState<TranscriptData | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch<TranscriptData>(`/api/documents/${jobId}/transcript.json`)
      .then((d) => {
        setData(d);
        setNames(d.speaker_names);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "Failed to load transcript.");
      });
  }, [jobId]);

  async function handleSaveNames() {
    setSaving(true);
    setError(null);
    try {
      const updated = await apiFetch<TranscriptData>(`/api/jobs/${jobId}/speakers`, {
        method: "POST",
        body: JSON.stringify({ speaker_names: names }),
      });
      setData(updated);
      setNames(updated.speaker_names);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save speaker names.");
    } finally {
      setSaving(false);
    }
  }

  if (error) return <p className="mt-6 text-sm text-red-600">{error}</p>;
  if (!data) return <p className="mt-6 text-sm text-muted">Loading transcript...</p>;

  const displayName = (speaker: string) => names[speaker] || speaker;

  const totalsBySpeaker: Record<string, number> = {};
  for (const seg of data.segments) {
    totalsBySpeaker[seg.speaker] = (totalsBySpeaker[seg.speaker] ?? 0) + (seg.end_ts - seg.start_ts);
  }
  const totalTime = Object.values(totalsBySpeaker).reduce((a, b) => a + b, 0) || 1;

  return (
    <div className="mt-6 rounded-2xl border border-brand-border bg-surface p-6 shadow-soft">
      <h2 className="text-lg font-semibold text-brand-navy">Transcript</h2>

      {data.summary && (
        <div className="mt-3 rounded-lg bg-brand-navy-soft p-3 text-sm text-foreground">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Summary</p>
          <p>{data.summary}</p>
        </div>
      )}

      {data.speakers.length > 1 && (
        <div className="mt-4 flex h-2 overflow-hidden rounded-full bg-brand-navy-soft">
          {data.speakers.map((speaker, i) => {
            const pct = ((totalsBySpeaker[speaker] ?? 0) / totalTime) * 100;
            if (pct <= 0) return null;
            return (
              <div
                key={speaker}
                style={{ width: `${pct}%` }}
                className={colorFor(i).bar}
                title={`${displayName(speaker)}: ${Math.round(pct)}%`}
              />
            );
          })}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {data.speakers.map((speaker, i) => (
          <div key={speaker} className="flex items-center gap-2">
            <span
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${colorFor(i).avatar}`}
            >
              {initials(displayName(speaker))}
            </span>
            <input
              type="text"
              value={names[speaker] ?? ""}
              placeholder={speaker}
              onChange={(e) => setNames((prev) => ({ ...prev, [speaker]: e.target.value }))}
              className="w-32 rounded-lg border border-brand-border bg-surface px-2 py-1 text-sm outline-none transition-shadow focus:border-brand-amber-dark focus:ring-2 focus:ring-brand-amber-soft"
            />
          </div>
        ))}
        <button
          onClick={handleSaveNames}
          disabled={saving}
          className="rounded-lg bg-brand-navy px-3 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-brand-navy-hover disabled:cursor-default disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save names"}
        </button>
      </div>

      <div className="mt-4 max-h-[32rem] space-y-3 overflow-y-auto pr-1">
        {data.segments.map((seg, i) => {
          const speakerIndex = data.speakers.indexOf(seg.speaker);
          return (
            <div key={i} className="flex gap-3">
              <span
                className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${colorFor(speakerIndex).avatar}`}
              >
                {initials(displayName(seg.speaker))}
              </span>
              <div>
                <p className="text-xs font-medium text-muted">
                  {displayName(seg.speaker)} &middot; {formatTimestamp(seg.start_ts)}
                </p>
                <p className="text-sm text-foreground">{seg.text}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
