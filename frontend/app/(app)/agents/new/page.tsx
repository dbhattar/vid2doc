"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Button from "@/components/Button";
import Card from "@/components/Card";
import { ApiError, apiFetch } from "@/lib/api";
import { fetchCatalog, type Agent, type AgentCatalog, type CatalogItem } from "@/lib/agents";
import { displayTitle, type Job } from "@/lib/jobs";

function toggle(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

function CheckboxList({
  items,
  selected,
  onToggle,
}: {
  items: CatalogItem[];
  selected: string[];
  onToggle: (id: string) => void;
}) {
  return (
    <div className="space-y-2">
      {items.map((item) => (
        <label key={item.id} className="flex cursor-pointer items-start gap-2.5 text-sm">
          <input
            type="checkbox"
            checked={selected.includes(item.id)}
            onChange={() => onToggle(item.id)}
            className="mt-1"
          />
          <span>
            <span className="font-medium text-ink">{item.name}</span>
            <span className="block text-xs text-ink-soft">{item.description}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

export default function NewAgentPage() {
  const router = useRouter();
  const [catalog, setCatalog] = useState<AgentCatalog | null>(null);
  const [docs, setDocs] = useState<Job[] | null>(null);
  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");
  const [toolIds, setToolIds] = useState<string[]>(["search_documents"]);
  const [skillIds, setSkillIds] = useState<string[]>([]);
  const [jobIds, setJobIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCatalog().then(setCatalog).catch(() => setError("Failed to load tools and skills."));
    // Video and audio are fetched separately -- the endpoint filters on one job_type at a time.
    Promise.all(
      (["video", "audio"] as const).map((type) =>
        apiFetch<{ jobs: Job[] }>(`/api/jobs?status=done&job_type=${type}&limit=100`).then((r) => r.jobs),
      ),
    )
      .then(([video, audio]) => setDocs([...video, ...audio].filter((j) => !j.retention_expired)))
      .catch(() => setError("Failed to load your documents."));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const agent = await apiFetch<Agent>("/api/agents", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          instructions,
          tool_ids: toolIds,
          skill_ids: skillIds,
          job_ids: jobIds,
        }),
      });
      router.push(`/agents/${agent.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create the agent.");
      setBusy(false);
    }
  }

  return (
    <div className="w-full max-w-3xl px-6 py-10">
      <h1 className="font-display text-2xl font-bold tracking-tight text-ink">New agent</h1>
      <p className="mt-1 text-sm text-ink-soft">Pick what your agent knows, which tools it can use, and its skills.</p>

      <form onSubmit={handleSubmit} className="mt-6 space-y-6">
        <Card className="space-y-4 p-6">
          <label className="block text-sm font-semibold text-ink">
            Name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={100}
              required
              className="mt-1 w-full rounded-lg border border-line bg-paper px-3 py-2 text-sm font-normal text-ink outline-none focus:border-accent"
            />
          </label>
          <label className="block text-sm font-semibold text-ink">
            Instructions <span className="font-normal text-ink-soft">(optional)</span>
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              maxLength={4000}
              rows={3}
              placeholder="e.g. Answer like a friendly project manager. Keep it short."
              className="mt-1 w-full rounded-lg border border-line bg-paper px-3 py-2 text-sm font-normal text-ink outline-none focus:border-accent"
            />
          </label>
        </Card>

        <Card className="p-6">
          <h2 className="text-sm font-semibold text-ink">Knowledge base</h2>
          <p className="mb-3 text-xs text-ink-soft">
            Documents are copied into the agent when you add them, so it keeps working after they expire.
          </p>
          {docs === null ? (
            <p className="text-sm text-ink-soft">Loading...</p>
          ) : docs.length === 0 ? (
            <p className="text-sm text-ink-soft">No finished documents yet -- convert a video or audio file first.</p>
          ) : (
            <div className="max-h-64 space-y-2 overflow-y-auto">
              {docs.map((job) => (
                <label key={job.job_id} className="flex cursor-pointer items-center gap-2.5 text-sm text-ink">
                  <input
                    type="checkbox"
                    checked={jobIds.includes(job.job_id)}
                    onChange={() => setJobIds((prev) => toggle(prev, job.job_id))}
                  />
                  <span className="truncate">{displayTitle(job)}</span>
                  <span className="shrink-0 text-xs text-ink-soft">{job.job_type}</span>
                </label>
              ))}
            </div>
          )}
        </Card>

        {catalog && (
          <>
            <Card className="p-6">
              <h2 className="mb-3 text-sm font-semibold text-ink">Tools</h2>
              <CheckboxList items={catalog.tools} selected={toolIds} onToggle={(id) => setToolIds((p) => toggle(p, id))} />
            </Card>
            <Card className="p-6">
              <h2 className="mb-3 text-sm font-semibold text-ink">Skills</h2>
              <CheckboxList items={catalog.skills} selected={skillIds} onToggle={(id) => setSkillIds((p) => toggle(p, id))} />
            </Card>
          </>
        )}

        {error && <p className="text-sm text-status-error">{error}</p>}
        <Button type="submit" disabled={busy || !name.trim()}>
          {busy ? "Creating..." : "Create agent"}
        </Button>
      </form>
    </div>
  );
}
