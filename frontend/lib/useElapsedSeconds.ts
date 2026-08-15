"use client";

import { useEffect, useState } from "react";

/** Live-ticking seconds since `startedAt`, updated once a second while
 * `active`. Distinct from formatElapsed() in jobs.ts, which is an explicit
 * one-shot updated_at-minus-created_at snapshot for a job that's stopped
 * changing -- this is for a job still in flight, where polling alone (every
 * 3-4s) would otherwise look static between server updates. */
export function useElapsedSeconds(startedAt: string, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active, startedAt]);

  return Math.max(0, (now - new Date(startedAt).getTime()) / 1000);
}
