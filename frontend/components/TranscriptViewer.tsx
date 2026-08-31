"use client";

import { useEffect, useState } from "react";

import Button from "@/components/Button";
import { apiFetch, ApiError } from "@/lib/api";
import { formatTimestamp, type TranscriptData } from "@/lib/jobs";
import { speakerColorFor as colorFor, speakerInitials as initials } from "@/lib/speakerColors";

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

  if (error) return <p className="mt-6 text-sm text-status-error">{error}</p>;
  if (!data) return <p className="mt-6 text-sm text-ink-soft">Loading transcript...</p>;

  const displayName = (speaker: string) => names[speaker] || speaker;

  const totalsBySpeaker: Record<string, number> = {};
  for (const seg of data.segments) {
    totalsBySpeaker[seg.speaker] = (totalsBySpeaker[seg.speaker] ?? 0) + (seg.end_ts - seg.start_ts);
  }
  const totalTime = Object.values(totalsBySpeaker).reduce((a, b) => a + b, 0) || 1;

  return (
    <div className="mt-6 rounded-lg border border-line bg-paper p-6 shadow-sm">
      <h2 className="font-display text-lg font-bold text-ink">Transcript</h2>

      {data.summary && (
        <div className="mt-3 rounded-md bg-paper-shade p-3 text-sm text-ink">
          <p className="mb-1 text-xs font-semibold text-ink-soft">Summary</p>
          <p>{data.summary}</p>
        </div>
      )}

      {data.speakers.length > 1 && (
        <div className="mt-4 flex h-2 overflow-hidden rounded-full bg-paper-shade">
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
              className="w-32 rounded-md border border-line bg-paper px-2 py-1 text-sm outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft"
            />
          </div>
        ))}
        <Button onClick={handleSaveNames} disabled={saving}>
          {saving ? "Saving..." : "Save names"}
        </Button>
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
                <p className="text-xs font-medium text-ink-soft">
                  {displayName(seg.speaker)} &middot; {formatTimestamp(seg.start_ts)}
                </p>
                <p className="text-sm text-ink">{seg.text}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
