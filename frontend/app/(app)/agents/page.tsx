"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import Card from "@/components/Card";
import { buttonClassName } from "@/components/Button";
import { BotIcon } from "@/components/icons";
import { ApiError } from "@/lib/api";
import { fetchAgents, type Agent } from "@/lib/agents";

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAgents()
      .then(setAgents)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load agents."));
  }, []);

  return (
    <div className="w-full px-6 py-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight text-ink">Agents</h1>
          <p className="mt-1 text-sm text-ink-soft">
            Chat with an AI agent that knows your documents, can use tools, and remembers past conversations.
          </p>
        </div>
        <Link href="/agents/new" className={buttonClassName("primary")}>
          New agent
        </Link>
      </div>

      {error && <p className="mt-4 text-sm text-status-error">{error}</p>}

      {agents === null ? (
        !error && <p className="mt-6 text-sm text-ink-soft">Loading...</p>
      ) : agents.length === 0 ? (
        <p className="mt-6 rounded-lg border border-dashed border-line p-6 text-center text-sm text-ink-soft">
          No agents yet. Create one from your finished documents.
        </p>
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent) => (
            <Link key={agent.id} href={`/agents/${agent.id}`}>
              <Card className="h-full p-4 transition-colors hover:border-ink">
                <div className="flex items-center gap-2.5">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
                    <BotIcon className="h-4 w-4" />
                  </span>
                  <h2 className="truncate text-sm font-semibold text-ink">{agent.name}</h2>
                </div>
                <p className="mt-2 text-xs text-ink-soft">
                  {agent.tool_ids.length} tools · {agent.skill_ids.length} skills
                  {agent.memory ? " · has memory" : ""}
                </p>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
