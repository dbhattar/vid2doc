"use client";

import { useEffect, useState } from "react";

import Button from "@/components/Button";
import { apiFetch, ApiError } from "@/lib/api";

/** Public landing page for the unsubscribe link in announcement emails (see
 * backend/app/announcements.py). Outside the (app) group -- no auth. Needs an
 * explicit click rather than unsubscribing on load, so email link scanners
 * can't unsubscribe people by prefetching it. */
export default function UnsubscribePage() {
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setToken(new URLSearchParams(window.location.search).get("token"));
  }, []);

  async function handleUnsubscribe() {
    setState("busy");
    setError(null);
    try {
      await apiFetch("/api/announcements/unsubscribe", { method: "POST", body: JSON.stringify({ token }) });
      setState("done");
    } catch (err) {
      setState("idle");
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    }
  }

  return (
    <div className="min-h-screen bg-paper">
      <div className="mx-auto max-w-md px-6 py-16 text-center">
        <a href="https://framewrite.cc" className="font-display text-lg font-bold text-ink">
          Framewrite
        </a>
        {state === "done" ? (
          <p className="mt-8 text-sm text-ink">
            You&apos;re unsubscribed from Framewrite announcements. You&apos;ll still get emails about your own jobs.
          </p>
        ) : (
          <>
            <p className="mt-8 text-sm text-ink">Stop receiving Framewrite product updates and announcements?</p>
            <Button onClick={handleUnsubscribe} disabled={!token || state === "busy"} className="mt-4 justify-center">
              {state === "busy" ? "Unsubscribing..." : "Unsubscribe"}
            </Button>
            {error && <p className="mt-3 text-sm text-status-error">{error}</p>}
          </>
        )}
      </div>
    </div>
  );
}
