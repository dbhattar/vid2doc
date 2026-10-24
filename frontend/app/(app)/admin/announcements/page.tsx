"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import Button from "@/components/Button";
import { apiFetch, ApiError } from "@/lib/api";

/** Admin-only: compose and send an announcement email to every user who
 * hasn't unsubscribed. See backend/app/announcements.py. */
export default function AnnouncementsPage() {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [recipientCount, setRecipientCount] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<{ recipient_count: number }>("/api/admin/announcements/audience")
      .then((data) => setRecipientCount(data.recipient_count))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load audience."));
  }, []);

  async function send(test: boolean) {
    if (!test && !confirm(`Send this to ${recipientCount ?? "all"} users? This can't be undone.`)) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await apiFetch<{ recipient_count: number }>("/api/admin/announcements", {
        method: "POST",
        body: JSON.stringify({ subject, body, test }),
      });
      if (test) {
        setNotice("Test email sent to you.");
      } else {
        setNotice(`Sending to ${result.recipient_count} users in the background.`);
        setSubject("");
        setBody("");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to send.");
    } finally {
      setBusy(false);
    }
  }

  const ready = subject.trim() !== "" && body.trim() !== "";
  const inputClass =
    "w-full rounded-md border border-line bg-paper px-3 py-2 text-sm text-ink outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft";

  return (
    <div className="w-full px-6 py-10">
      <Link href="/admin" className="text-sm text-accent hover:underline">
        &larr; Admin
      </Link>
      <h1 className="mt-2 font-display text-2xl font-bold tracking-tight text-ink">Send an announcement</h1>
      <p className="mt-1 text-sm text-ink-soft">
        Emails every user who hasn&apos;t unsubscribed
        {recipientCount != null && ` (${recipientCount} right now)`}. Each email includes an unsubscribe link.
      </p>

      <div className="mt-6 max-w-2xl space-y-4">
        <input
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          maxLength={200}
          placeholder="Subject"
          className={inputClass}
        />
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          maxLength={10000}
          rows={12}
          placeholder="Write your update. Plain text -- leave a blank line between paragraphs."
          className={inputClass}
        />
        <div className="flex items-center gap-3">
          <Button variant="outline" onClick={() => send(true)} disabled={busy || !ready}>
            Send test to me
          </Button>
          <Button onClick={() => send(false)} disabled={busy || !ready}>
            {busy ? "Sending..." : "Send to all users"}
          </Button>
        </div>
        {notice && <p className="text-sm text-ink">{notice}</p>}
        {error && <p className="text-sm text-status-error">{error}</p>}
      </div>
    </div>
  );
}
