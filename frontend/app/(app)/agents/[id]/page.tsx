"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import AgentChat from "@/components/AgentChat";
import Button from "@/components/Button";
import Card from "@/components/Card";
import { ApiError, apiFetch } from "@/lib/api";
import { fetchAgent, fetchCatalog, type AgentCatalog, type AgentConversation, type AgentDetail } from "@/lib/agents";
import { displayTitle, type Job } from "@/lib/jobs";

export default function AgentDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const agentId = params.id;

  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [catalog, setCatalog] = useState<AgentCatalog | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [addableDocs, setAddableDocs] = useState<Job[]>([]);
  const [docToAdd, setDocToAdd] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reloadAgent = useCallback(() => fetchAgent(agentId).then(setAgent), [agentId]);

  useEffect(() => {
    fetchCatalog().then(setCatalog).catch(() => {});
    reloadAgent()
      .then(async () => {
        // Resume the latest conversation, or start the first one.
        const { conversations } = await apiFetch<{ conversations: AgentConversation[] }>(
          `/api/agents/${agentId}/conversations`,
        );
        if (conversations.length > 0) {
          setConversationId(conversations[0].id);
        } else {
          const created = await apiFetch<AgentConversation>(`/api/agents/${agentId}/conversations`, { method: "POST" });
          setConversationId(created.id);
        }
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) router.replace("/agents");
        else setError(err instanceof ApiError ? err.message : "Failed to load the agent.");
      });
  }, [agentId, reloadAgent, router]);

  // Finished documents not already attached, for the "add document" picker.
  useEffect(() => {
    if (!agent) return;
    Promise.all(
      (["video", "audio"] as const).map((type) =>
        apiFetch<{ jobs: Job[] }>(`/api/jobs?status=done&job_type=${type}&limit=100`).then((r) => r.jobs),
      ),
    )
      .then(([video, audio]) => {
        const attached = new Set(agent.documents.map((d) => d.job_id));
        setAddableDocs([...video, ...audio].filter((j) => !j.retention_expired && !attached.has(j.job_id)));
      })
      .catch(() => {});
  }, [agent]);

  async function run(action: () => Promise<unknown>, failure: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : failure);
    } finally {
      setBusy(false);
    }
  }

  const handleNewConversation = () =>
    run(async () => {
      // Starting a conversation folds the previous one into memory first.
      const created = await apiFetch<AgentConversation>(`/api/agents/${agentId}/conversations`, { method: "POST" });
      setConversationId(created.id);
      await reloadAgent();
    }, "Failed to start a new conversation.");

  const handleAddDocument = () =>
    run(async () => {
      await apiFetch(`/api/agents/${agentId}/documents`, { method: "POST", body: JSON.stringify({ job_id: docToAdd }) });
      setDocToAdd("");
      await reloadAgent();
    }, "Failed to add the document.");

  const handleRemoveDocument = (docId: string) =>
    run(async () => {
      await apiFetch(`/api/agents/${agentId}/documents/${docId}`, { method: "DELETE" });
      await reloadAgent();
    }, "Failed to remove the document.");

  const handleClearMemory = () =>
    run(async () => {
      await apiFetch(`/api/agents/${agentId}/memory`, { method: "DELETE" });
      await reloadAgent();
    }, "Failed to clear memory.");

  const handleDelete = () => {
    if (!window.confirm("Delete this agent and all its conversations?")) return;
    return run(async () => {
      await apiFetch(`/api/agents/${agentId}`, { method: "DELETE" });
      router.push("/agents");
    }, "Failed to delete the agent.");
  };

  if (!agent) {
    return (
      <div className="w-full px-6 py-10">
        {error ? <p className="text-sm text-status-error">{error}</p> : <p className="text-sm text-ink-soft">Loading...</p>}
      </div>
    );
  }

  const toolNames = agent.tool_ids.map((id) => catalog?.tools.find((t) => t.id === id)?.name ?? id);
  const skillNames = agent.skill_ids.map((id) => catalog?.skills.find((s) => s.id === id)?.name ?? id);

  return (
    <div className="w-full px-6 py-10">
      <Link href="/agents" className="text-sm text-ink-soft hover:text-accent">
        &larr; Agents
      </Link>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-bold tracking-tight text-ink">{agent.name}</h1>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={handleNewConversation} disabled={busy}>
            New conversation
          </Button>
          <Button variant="secondary" onClick={handleDelete} disabled={busy}>
            Delete
          </Button>
        </div>
      </div>
      {error && <p className="mt-3 text-sm text-status-error">{error}</p>}

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card className="p-4 lg:col-span-2">
          {conversationId ? (
            <AgentChat key={conversationId} agentId={agentId} conversationId={conversationId} />
          ) : (
            <p className="text-sm text-ink-soft">Loading...</p>
          )}
        </Card>

        <div className="space-y-6">
          <Card className="p-4">
            <h2 className="text-sm font-semibold text-ink">Knowledge base</h2>
            {agent.documents.length === 0 ? (
              <p className="mt-2 text-sm text-ink-soft">No documents attached yet.</p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {agent.documents.map((doc) => (
                  <li key={doc.id} className="flex items-center justify-between gap-2 text-sm text-ink">
                    <span className="truncate">{doc.title}</span>
                    <button
                      onClick={() => handleRemoveDocument(doc.id)}
                      disabled={busy}
                      className="shrink-0 text-xs text-ink-soft hover:text-status-error"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {addableDocs.length > 0 && (
              <div className="mt-3 flex items-center gap-2">
                <select
                  value={docToAdd}
                  onChange={(e) => setDocToAdd(e.target.value)}
                  className="min-w-0 flex-1 rounded-lg border border-line bg-paper px-2 py-1.5 text-sm text-ink"
                >
                  <option value="">Add a document...</option>
                  {addableDocs.map((job) => (
                    <option key={job.job_id} value={job.job_id}>
                      {displayTitle(job)}
                    </option>
                  ))}
                </select>
                <Button variant="outline" onClick={handleAddDocument} disabled={busy || !docToAdd}>
                  Add
                </Button>
              </div>
            )}
          </Card>

          <Card className="p-4">
            <h2 className="text-sm font-semibold text-ink">Tools &amp; skills</h2>
            <p className="mt-2 text-sm text-ink-soft">
              {toolNames.length > 0 ? `Tools: ${toolNames.join(", ")}` : "No tools selected."}
            </p>
            <p className="mt-1 text-sm text-ink-soft">
              {skillNames.length > 0 ? `Skills: ${skillNames.join(", ")}` : "No skills selected."}
            </p>
          </Card>

          <Card className="p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-ink">Memory</h2>
              {agent.memory && (
                <button onClick={handleClearMemory} disabled={busy} className="text-xs text-ink-soft hover:text-status-error">
                  Clear
                </button>
              )}
            </div>
            {agent.memory ? (
              <p className="mt-2 whitespace-pre-wrap text-sm text-ink-soft">{agent.memory}</p>
            ) : (
              <p className="mt-2 text-sm text-ink-soft">
                Nothing yet. When you start a new conversation, the agent remembers what mattered from this one.
              </p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
