"use client";

import { useEffect, useRef, useState } from "react";

import { FeedbackIcon } from "@/components/icons";
import { apiFetch, ApiError } from "@/lib/api";

export default function FeedbackButton() {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  function toggle() {
    setOpen((o) => !o);
    setError(null);
    setSent(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!message.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await apiFetch("/api/feedback", { method: "POST", body: JSON.stringify({ message: message.trim() }) });
      setMessage("");
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to send feedback.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={toggle}
        title="Feedback / feature requests"
        className="flex items-center justify-center rounded-lg p-2 text-muted transition-colors hover:bg-brand-navy-soft hover:text-brand-navy"
      >
        <FeedbackIcon className="h-5 w-5" />
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-2 w-80 rounded-xl border border-brand-border bg-surface p-4 shadow-soft">
          {sent ? (
            <div className="text-center">
              <p className="text-sm font-medium text-foreground">Thanks for the feedback!</p>
              <button
                onClick={() => setOpen(false)}
                className="mt-3 text-sm text-muted hover:text-brand-amber-dark hover:underline"
              >
                Close
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit}>
              <p className="text-sm font-semibold text-foreground">Feedback or feature request</p>
              <p className="mt-1 text-xs text-muted">
                Tell us what&apos;s working, what&apos;s not, or what you&apos;d like to see.
              </p>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={4}
                placeholder="Type your feedback here..."
                className="mt-3 w-full resize-none rounded-lg border border-brand-border bg-surface px-3 py-2 text-sm outline-none transition-shadow focus:border-brand-amber-dark focus:ring-2 focus:ring-brand-amber-soft"
              />
              {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
              <button
                type="submit"
                disabled={submitting || !message.trim()}
                className="mt-3 w-full rounded-lg bg-brand-navy px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-navy-hover disabled:cursor-default disabled:opacity-50"
              >
                {submitting ? "Sending..." : "Send feedback"}
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
