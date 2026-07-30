"use client";

import { useEffect, useRef, useState } from "react";

import Button from "@/components/Button";
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
        className="flex items-center justify-center p-2 text-ink-soft transition-colors hover:bg-paper-shade hover:text-ink"
      >
        <FeedbackIcon className="h-5 w-5" />
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-2 w-80 border-2 border-line bg-paper p-4">
          {sent ? (
            <div className="text-center">
              <p className="text-sm font-medium text-ink">Thanks for the feedback!</p>
              <button
                onClick={() => setOpen(false)}
                className="mt-3 text-sm text-ink-soft hover:text-accent hover:underline"
              >
                Close
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit}>
              <p className="text-sm font-semibold text-ink">Feedback or feature request</p>
              <p className="mt-1 text-xs text-ink-soft">
                Tell us what&apos;s working, what&apos;s not, or what you&apos;d like to see.
              </p>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={4}
                placeholder="Type your feedback here..."
                className="mt-3 w-full resize-none border-2 border-line bg-paper px-3 py-2 text-sm outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft"
              />
              {error && <p className="mt-2 text-sm text-status-error">{error}</p>}
              <Button type="submit" disabled={submitting || !message.trim()} className="mt-3 w-full justify-center">
                {submitting ? "Sending..." : "Send feedback"}
              </Button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
