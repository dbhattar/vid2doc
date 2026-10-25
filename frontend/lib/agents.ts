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
  // Assistant-only: web pages the reply cited. Shown under it, never read aloud.
  sources: { title: string; url: string }[];
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

// OpenAI web search leaves citation markers in a reply -- "\ue200cite\ue202turn0search0\ue201",
// wrapped in invisible private-use characters, so they show up as "citeturn0search0".
// The backend strips them from new replies (agents.py's strip_citation_markers); this
// covers messages saved before that.
export function stripCitationMarkers(text: string): string {
  return text.replace(/\ue200[^\ue201]*\ue201|[\ue000-\uf8ff]/g, "");
}
