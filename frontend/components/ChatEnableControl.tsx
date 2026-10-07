"use client";

import { useState } from "react";

import { buttonClassName } from "@/components/Button";
import { ChatIcon } from "@/components/icons";
import { apiFetch, ApiError } from "@/lib/api";
import { formatCents } from "@/lib/billing";
import type { Job } from "@/lib/jobs";

/** Owner-only: permanently enables chat-with-document on a completed job for
 * a flat one-time fee (see routes/chat.py). Modeled on
 * PublicConsentControl.tsx's inline-confirm pattern -- this also moves real
 * money and is irreversible (archives the document + original media to a
 * private S3 prefix, with no un-enable path), so it gets the same weight
 * instead of a one-line toggle. */
export default function ChatEnableControl({ job, onUpdated }: { job: Job; onUpdated: (job: Job) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  async function handleSubmit() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/jobs/${job.job_id}/chat/enable`, { method: "POST" });
      onUpdated({ ...job, chat_enabled: true });
      setConfirming(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to enable chat.");
    } finally {
      setBusy(false);
    }
  }

  const fee = job.chat_enable_fee_cents != null ? formatCents(job.chat_enable_fee_cents) : "a one-time fee";

  if (job.chat_enabled) {
    return (
      <div className="mt-4 rounded-lg border border-line bg-paper-shade p-4">
        <p className="text-sm text-ink">Chat is enabled for this document -- ask it anything below.</p>
      </div>
    );
  }

  if (confirming) {
    return (
      <div className="mt-4 rounded-lg border border-line bg-paper-shade p-4">
        <p className="text-sm text-ink">
          Enabling chat costs {fee}, one time, for unlimited questions after that. This is <strong>permanent</strong>:
          it archives this document and its original video/audio so both keep working even after the usual 7-day
          retention period, with no way to turn it back off.
        </p>
        <div className="mt-3 flex items-center gap-3">
          <button onClick={handleSubmit} disabled={busy} className={buttonClassName("primary")}>
            {busy ? "Enabling..." : "Enable chat"}
          </button>
          <button
            onClick={() => setConfirming(false)}
            disabled={busy}
            className="text-sm text-ink-soft hover:underline disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
        {error && <p className="mt-2 text-sm text-status-error">{error}</p>}
      </div>
    );
  }

  return (
    <div className="mt-4">
      <button onClick={() => setConfirming(true)} className={buttonClassName("outline")}>
        <ChatIcon className="h-4 w-4" />
        Enable chat with this document
      </button>
      {error && <p className="mt-2 text-sm text-status-error">{error}</p>}
    </div>
  );
}
