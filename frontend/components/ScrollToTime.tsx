"use client";

import { useEffect } from "react";

/** Opens the transcript at the time in the page's `?t=` (seconds), as used by
 * the links in topic-alert emails: scrolls to the speaker turn that contains
 * it and highlights it. Renders nothing. */
export default function ScrollToTime() {
  useEffect(() => {
    const t = Number(new URLSearchParams(window.location.search).get("t"));
    if (!Number.isFinite(t) || t <= 0) return;
    let target: HTMLElement | null = null;
    for (const el of document.querySelectorAll<HTMLElement>("[data-turn-start]")) {
      if (Number(el.dataset.turnStart) <= t) target = el;
      else break;
    }
    if (!target) return;
    target.scrollIntoView({ block: "center" });
    target.classList.add("bg-accent-soft");
  }, []);
  return null;
}
