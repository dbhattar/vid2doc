"use client";

import { useState } from "react";

import Button from "@/components/Button";
import { apiFetch, ApiError } from "@/lib/api";

export type MeetingsRequestStatus = "pending" | "approved" | "declined" | null;

/** Shown on /meetings to users an admin hasn't enabled yet: Meetings is a
 * preview, so instead of a dead end they can ask for access. */
export default function MeetingsRequestAccess({
  initialStatus,
  onAuthError,
}: {
  initialStatus: MeetingsRequestStatus;
  onAuthError: (err: unknown) => boolean;
}) {
  const [status, setStatus] = useState<MeetingsRequestStatus>(initialStatus);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const data = await apiFetch<{ request_status: MeetingsRequestStatus }>("/api/features/meetings/request", {
        method: "POST",
        body: JSON.stringify({ message: message.trim() || null }),
      });
      setStatus(data.request_status);
    } catch (err) {
      if (onAuthError(err)) return;
      setError(err instanceof ApiError ? err.message : "Couldn't send your request.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mt-8 w-full max-w-2xl rounded-lg border border-line bg-paper p-6 shadow-sm">
      {status === "pending" ? (
        <>
          <h2 className="font-display text-lg font-bold text-ink">Request received</h2>
          <p className="mt-1 text-sm text-ink-soft">
            Thanks &mdash; we&apos;ll email you as soon as Meetings is turned on for your account.
          </p>
        </>
      ) : (
        <form onSubmit={handleSubmit}>
          <h2 className="font-display text-lg font-bold text-ink">
            {status === "declined" ? "Request again" : "Request preview access"}
          </h2>
          <p className="mt-1 text-sm text-ink-soft">
            Meetings is a preview and we&apos;re switching it on for a few people at a time.
            {status === "declined" && " Your last request wasn't approved yet -- you're welcome to ask again."}
          </p>
          <label htmlFor="meetings-request-note" className="mt-4 block text-xs font-medium text-ink-soft">
            What would you use it for? (optional)
          </label>
          <textarea
            id="meetings-request-note"
            value={message}
            maxLength={1000}
            onChange={(e) => setMessage(e.target.value)}
            rows={3}
            placeholder="e.g. weekly team standups on Google Meet"
            className="mt-1 w-full rounded-md border border-line bg-paper px-3 py-2 text-sm text-ink outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft"
          />
          {error && <p className="mt-2 text-sm text-status-error">{error}</p>}
          <Button type="submit" disabled={submitting} className="mt-4">
            {submitting ? "Sending..." : "Request access"}
          </Button>
        </form>
      )}
    </div>
  );
}
