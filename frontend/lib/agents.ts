import { apiFetch } from "@/lib/api";

export type CatalogItem = {
  id: string;
  name: string;
  description: string;
  // Tools only: false when this user can't use the tool right now (e.g.
  // Google Drive not connected), with the reason to show. Skills omit both.
  available?: boolean;
  unavailable_reason?: string | null;
};
export type AgentCatalog = { tools: CatalogItem[]; skills: CatalogItem[] };

export type AgentDocument = { id: string; job_id: string; title: string; created_at: string };

export type Agent = {
  id: string;
  name: string;
  instructions: string;
  tool_ids: string[];
  skill_ids: string[];
  // Rolling summary of earlier conversations, written when a new
  // conversation starts -- see backend/app/agents.py.
  memory: string;
  created_at: string;
  updated_at: string;
};

export type AgentDetail = Agent & { documents: AgentDocument[] };

export type AgentMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  // Assistant-only: names of the tools the agent called for this reply.
  tools_used: string[];
  created_at: string;
};

export type AgentConversation = { id: string; created_at: string };

export function fetchCatalog() {
  return apiFetch<AgentCatalog>("/api/agents/catalog");
}

export function fetchAgents() {
  return apiFetch<{ agents: Agent[] }>("/api/agents").then((r) => r.agents);
}

export function fetchAgent(id: string) {
  return apiFetch<AgentDetail>(`/api/agents/${id}`);
}
