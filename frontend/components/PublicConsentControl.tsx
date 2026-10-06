"use client";

import { useState } from "react";

import { buttonClassName } from "@/components/Button";
import { GlobeIcon } from "@/components/icons";
import { apiFetch, ApiError } from "@/lib/api";
import { formatCents } from "@/lib/billing";
import type { Job } from "@/lib/jobs";

/** Owner-only: opts a completed job_type === "video" job into the public
 * showcase in exchange for a partial refund. Modeled on ShareControl.tsx's
 * shape, with one addition ShareControl doesn't need: an inline confirm
 * step before submitting, since this moves real money and -- unlike
 * ShareControl's toggle -- is irreversible once approved. */
export default function PublicConsentControl({ job, onUpdated }: { job: Job; onUpdated: (job: Job) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  async function handleSubmit() {
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<{ public_status: "pending"; public_refund_cents: number }>(
        `/api/jobs/${job.job_id}/public-consent`,
        { method: "POST" }
      );
      onUpdated({ ...job, public_status: result.public_status, public_consent_refund_cents: result.public_refund_cents });
      setConfirming(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit for public review.");
    } finally {
      setBusy(false);
    }
  }

  const refundAmount = job.public_consent_refund_cents != null ? formatCents(job.public_consent_refund_cents) : null;

  if (job.public_status === "pending") {
    return (
      <div className="mt-4 rounded-lg border border-line bg-paper-shade p-4">
        <p className="text-sm text-ink">
          Submitted for review. You&apos;ll get your {refundAmount} refund once an admin approves this for the public
          showcase.
        </p>
      </div>
    );
  }

  if (job.public_status === "approved") {
    return (
      <div className="mt-4 rounded-lg border border-line bg-paper-shade p-4">
        <p className="text-sm text-ink">This document is featured in the Framewrite public showcase.</p>
        {job.public_showcase_url && (
          <a
            href={job.public_showcase_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-block text-sm text-accent hover:underline"
          >
            View it live →
          </a>
        )}
      </div>
    );
  }

  if (job.public_status === "rejected") {
    return (
      <div className="mt-4 rounded-lg border border-line bg-paper-shade p-4">
        <p className="text-sm text-ink-soft">This document wasn&apos;t approved for the public showcase.</p>
      </div>
    );
  }

  if (confirming) {
    return (
      <div className="mt-4 rounded-lg border border-line bg-paper-shade p-4">
        <p className="text-sm text-ink">
          Making this public gets you a {refundAmount} refund, but is <strong>permanent</strong> -- the document will
          be publicly viewable (and may be featured on the Framewrite homepage) with no way to take it down later.
        </p>
        <div className="mt-3 flex items-center gap-3">
          <button onClick={handleSubmit} disabled={busy} className={buttonClassName("primary")}>
            {busy ? "Submitting..." : "Submit for review"}
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
        <GlobeIcon className="h-4 w-4" />
        Make public for a refund
      </button>
      {error && <p className="mt-2 text-sm text-status-error">{error}</p>}
    </div>
  );
}
