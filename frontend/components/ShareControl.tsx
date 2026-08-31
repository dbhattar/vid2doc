"use client";

import { useState } from "react";

import { buttonClassName } from "@/components/Button";
import { ShareIcon } from "@/components/icons";
import { apiFetch, ApiError } from "@/lib/api";
import type { Job } from "@/lib/jobs";

/** Owner-only: turns a completed job's public share link on/off. Mirrors the
 * reveal-box/copy pattern from settings/api-keys, but the URL isn't a
 * one-time secret -- it stays visible and copyable for as long as sharing
 * is on. */
export default function ShareControl({ job, onUpdated }: { job: Job; onUpdated: (job: Job) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleEnable() {
    setBusy(true);
    setError(null);
    try {
      const { share_url } = await apiFetch<{ share_token: string; share_url: string }>(
        `/api/jobs/${job.job_id}/share`,
        { method: "POST" }
      );
      onUpdated({ ...job, share_url });
      setCopied(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to enable sharing.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDisable() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/jobs/${job.job_id}/share`, { method: "DELETE" });
      onUpdated({ ...job, share_url: null });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to disable sharing.");
    } finally {
      setBusy(false);
    }
  }

  function handleCopy() {
    if (!job.share_url) return;
    navigator.clipboard.writeText(job.share_url);
    setCopied(true);
  }

  if (!job.share_url) {
    return (
      <div className="mt-4">
        <button onClick={handleEnable} disabled={busy} className={buttonClassName("outline")}>
          <ShareIcon className="h-4 w-4" />
          {busy ? "Sharing..." : "Share"}
        </button>
        {error && <p className="mt-2 text-sm text-status-error">{error}</p>}
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-lg border border-line bg-paper-shade p-4">
      <p className="text-sm text-ink">This document is publicly viewable at:</p>
      <div className="mt-2 flex items-center gap-2">
        <code className="flex-1 overflow-x-auto rounded-md border border-line bg-paper px-3 py-2 text-sm">{job.share_url}</code>
        <button onClick={handleCopy} className={buttonClassName("outline", "shrink-0")}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <button onClick={handleDisable} disabled={busy} className="mt-3 text-sm text-status-error hover:underline disabled:opacity-50">
        {busy ? "Disabling..." : "Disable sharing"}
      </button>
      {error && <p className="mt-2 text-sm text-status-error">{error}</p>}
    </div>
  );
}
