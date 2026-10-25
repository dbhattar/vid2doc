"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import AgentVoiceControls, { useSpeech, useVoiceSettings } from "@/components/AgentVoiceControls";
import { buttonClassName } from "@/components/Button";
import { SpeakerIcon, SpeakerOffIcon } from "@/components/icons";
import { ApiError, apiFetch } from "@/lib/api";
import { stripCitationMarkers, type AgentMessage } from "@/lib/agents";
import { markdownToSpeech, speak, stopSpeaking } from "@/lib/phononSpeech";

const TOOL_LABELS: Record<string, string> = {
  search_documents: "searched documents",
  read_document: "read a document",
  web_search: "searched the web",
  research_topic: "researched a topic",
  fetch_url: "fetched a web page",
  email_me: "emailed you",
  save_to_drive: "saved to Drive",
};

// Compact chat-bubble styling for the markdown agents reply with (cf. the
// full-page styling in DocumentPreview.tsx). Raw HTML in the reply is never
// rendered -- react-markdown escapes it by default.
const MARKDOWN_COMPONENTS: Components = {
  h1: ({ children }) => <h3 className="mt-3 mb-1 font-display text-base font-bold first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mt-3 mb-1 font-display text-base font-bold first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mt-3 mb-1 font-semibold first:mt-0">{children}</h4>,
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-accent underline hover:no-underline">
      {children}
    </a>
  ),
  ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
  blockquote: ({ children }) => (
    <blockquote className="mb-2 border-l-4 border-accent pl-3 text-ink-soft">{children}</blockquote>
  ),
  code: ({ children }) => (
    <code className="rounded-sm border border-line bg-paper px-1 py-0.5 font-mono text-xs">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="mb-2 overflow-x-auto rounded-md border border-line bg-paper p-3 font-mono text-xs last:mb-0 [&_code]:border-0 [&_code]:bg-transparent [&_code]:p-0">
      {children}
    </pre>
  ),
  hr: () => <hr className="my-3 border-line" />,
  table: ({ children }) => (
    <div className="mb-2 overflow-x-auto last:mb-0">
      <table className="w-full border border-line text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border border-line bg-paper px-2 py-1 text-left font-semibold">{children}</th>,
  td: ({ children }) => <td className="border border-line px-2 py-1">{children}</td>,
};

/** Message list + input for one agent conversation (see
 * GET/POST /api/agents/{id}/conversations/{cid}/messages). Not streaming --
 * same as ChatPanel; each reply arrives whole, with the names of any tools
 * the agent used shown under it. Remount (key by conversation id) to switch
 * conversations -- state isn't reset on prop change. */
export default function AgentChat({ agentId, conversationId }: { agentId: string; conversationId: string }) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [voice, updateVoice] = useVoiceSettings();
  const speech = useSpeech();
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const basePath = `/api/agents/${agentId}/conversations/${conversationId}/messages`;

  useEffect(() => {
    apiFetch<{ messages: AgentMessage[] }>(basePath)
      .then((res) => setMessages(res.messages))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, [basePath]);

  useEffect(() => {
    // Scroll only this panel's own list -- see ChatPanel for why not scrollIntoView.
    const container = scrollContainerRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, [messages, busy]);

  // Also silences any reply still being read when the conversation changes or the page closes.
  useEffect(() => stopSpeaking, []);

  function toggleSpeak(m: AgentMessage) {
    if (speech.speakingId === m.id) {
      stopSpeaking();
    } else {
      void speak(m.id, markdownToSpeech(stripCitationMarkers(m.content)), voice.voiceId).catch(() => {});
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const message = input.trim();
    if (!message || busy) return;

    setBusy(true);
    setError(null);
    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: `local-${Date.now()}`, role: "user", content: message, tools_used: [], sources: [], created_at: new Date().toISOString() },
    ]);

    try {
      const reply = await apiFetch<AgentMessage>(basePath, { method: "POST", body: JSON.stringify({ message }) });
      setMessages((prev) => [...prev, reply]);
      if (voice.auto) void speak(reply.id, markdownToSpeech(stripCitationMarkers(reply.content)), voice.voiceId).catch(() => {});
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to get an answer.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-[32rem] flex-col">
      <AgentVoiceControls settings={voice} onChange={updateVoice} />
      <div ref={scrollContainerRef} className="flex-1 space-y-3 overflow-y-auto pr-1">
        {loaded && messages.length === 0 && <p className="text-sm text-ink-soft">Say something to your agent.</p>}
        {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "text-right" : "text-left"}>
            <div
              className={`inline-block max-w-[85%] rounded-lg px-3 py-2 text-left text-sm ${
                m.role === "user" ? "whitespace-pre-wrap bg-accent text-accent-ink" : "bg-paper-shade text-ink"
              }`}
            >
              {m.role === "user" ? (
                m.content
              ) : (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
                  {stripCitationMarkers(m.content)}
                </ReactMarkdown>
              )}
            </div>
            {m.role === "assistant" && !m.id.startsWith("local-") && (
              <button
                type="button"
                onClick={() => toggleSpeak(m)}
                className="mt-1 inline-flex items-center gap-1 text-xs text-ink-soft hover:text-ink"
              >
                {speech.speakingId === m.id ? (
                  <>
                    <SpeakerOffIcon className="h-3.5 w-3.5" /> Stop
                  </>
                ) : (
                  <>
                    <SpeakerIcon className="h-3.5 w-3.5" /> Listen
                  </>
                )}
              </button>
            )}
            {m.sources?.length > 0 && (
              <div className="mt-1 text-xs text-ink-soft">
                <p className="font-medium">Sources</p>
                <ol className="mt-0.5 list-decimal space-y-0.5 pl-5">
                  {m.sources.map((s) => (
                    <li key={s.url}>
                      <a href={s.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                        {s.title}
                      </a>
                    </li>
                  ))}
                </ol>
              </div>
            )}
            {m.tools_used.length > 0 && (
              <p className="mt-1 text-xs text-ink-soft">
                Used: {m.tools_used.map((t) => TOOL_LABELS[t] ?? t).join(", ")}
              </p>
            )}
          </div>
        ))}
        {busy && <p className="text-sm text-ink-soft">Thinking...</p>}
      </div>

      <form onSubmit={handleSubmit} className="mt-3 flex items-center gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Message your agent..."
          disabled={busy}
          className="flex-1 rounded-lg border border-line bg-paper px-3 py-2 text-sm text-ink outline-none focus:border-accent disabled:opacity-50"
        />
        <button type="submit" disabled={busy || !input.trim()} className={buttonClassName("primary")}>
          {busy ? "..." : "Send"}
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-status-error">{error}</p>}
    </div>
  );
}
