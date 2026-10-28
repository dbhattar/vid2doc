"use client";

import { useEffect, useRef, useState } from "react";

import { buttonClassName } from "@/components/Button";
import { apiFetch, ApiError } from "@/lib/api";
import type { ChatMessage } from "@/lib/jobs";

function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

/** Message list + input for a chat-enabled job (see GET/POST
 * /api/jobs/{id}/chat/messages). Each of an assistant message's citations
 * renders a button that calls onCitationClick -- the job detail page wires
 * this to MediaPreviewPlayer's playRange. */
export default function ChatPanel({
  jobId,
  onCitationClick,
}: {
  jobId: string;
  onCitationClick: (startSeconds: number, endSeconds: number | null) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // Grow with the text (wrapping onto new lines) up to the max-h cap,
    // then scroll; resets to one row once the input is cleared on send.
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);

  useEffect(() => {
    apiFetch<{ messages: ChatMessage[] }>(`/api/jobs/${jobId}/chat/messages`)
      .then((res) => setMessages(res.messages))
      .catch(() => {
        // First load with no history yet, or a transient failure -- either
        // way, an empty list (the "ask a question" prompt below) is the
        // right fallback, not an error banner.
      })
      .finally(() => setLoaded(true));
  }, [jobId]);

  useEffect(() => {
    // Scroll only this panel's own message list, not scrollIntoView on a
    // bottom-anchor element -- that walks up every scrollable ancestor,
    // including the whole page, and was dragging the entire UI upward on
    // every new message since this panel sits lower on the page.
    const container = scrollContainerRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, [messages]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const message = input.trim();
    if (!message || busy) return;

    setBusy(true);
    setError(null);
    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: `local-${Date.now()}`, role: "user", content: message, citation_seconds: null, citations: [], created_at: new Date().toISOString() },
    ]);

    try {
      const reply = await apiFetch<ChatMessage>(`/api/jobs/${jobId}/chat/messages`, {
        method: "POST",
        body: JSON.stringify({ message }),
      });
      setMessages((prev) => [...prev, reply]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to get an answer.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-[28rem] flex-col">
      <div ref={scrollContainerRef} className="flex-1 space-y-3 overflow-y-auto pr-1">
        {loaded && messages.length === 0 && (
          <p className="text-sm text-ink-soft">Ask a question about this document.</p>
        )}
        {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "text-right" : "text-left"}>
            <p
              className={`inline-block max-w-[85%] rounded-lg px-3 py-2 text-left text-sm ${
                m.role === "user" ? "bg-accent text-accent-ink" : "bg-paper-shade text-ink"
              }`}
            >
              {m.content}
            </p>
            {m.citations.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                {m.citations.map((c) => (
                  <button
                    key={`${c.start_seconds}-${c.end_seconds}`}
                    onClick={() => onCitationClick(c.start_seconds, c.end_seconds)}
                    className="text-xs text-accent hover:underline"
                  >
                    {c.end_seconds != null
                      ? `▶ Play ${formatTimestamp(c.start_seconds)}–${formatTimestamp(c.end_seconds)}`
                      : `▶ Jump to ${formatTimestamp(c.start_seconds)}`}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="mt-3 flex items-end gap-2">
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            // Enter sends, Shift+Enter inserts a newline. Skipped while an
            // IME composition is open, where Enter confirms the candidate.
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="Ask a question..."
          disabled={busy}
          rows={1}
          className="max-h-32 flex-1 resize-none rounded-lg border border-line bg-paper px-3 py-2 text-sm text-ink outline-none focus:border-accent disabled:opacity-50"
        />
        <button type="submit" disabled={busy || !input.trim()} className={buttonClassName("primary")}>
          {busy ? "..." : "Send"}
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-status-error">{error}</p>}
    </div>
  );
}
