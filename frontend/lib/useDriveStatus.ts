"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

/** Drive connection status is a per-user fact, not a per-job one -- fetched
 * once here rather than threaded through every job/document object. */
export function useDriveStatus(): boolean {
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    apiFetch<{ connected: boolean; google_email: string | null }>("/api/drive/status")
      .then((data) => setConnected(data.connected))
      .catch(() => {
        // Non-critical -- Save to Drive buttons just stay in the
        // not-connected state if this fails.
      });
  }, []);

  return connected;
}
