"use client";

import { useEffect, useState } from "react";

import { fetchAuthenticatedBlob } from "@/lib/api";

/** Generated videos are served behind Bearer-token auth (no cookie session
 * in this app), so a plain <video src> can't authenticate -- fetch as a
 * blob instead, same technique as AuthenticatedImage, and play it through a
 * throwaway object URL. Acceptable for the short v1 outputs this feature
 * produces; doesn't support scrubbing/range-requests well for long videos,
 * since the whole file downloads before playback can start. */
export default function AuthenticatedVideo({ src, className = "" }: { src: string; className?: string }) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let url: string | null = null;
    setObjectUrl(null);
    setFailed(false);

    fetchAuthenticatedBlob(src)
      .then((blob) => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setObjectUrl(url);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [src]);

  if (failed) {
    return <div className={`flex items-center justify-center bg-paper-shade text-xs text-ink-soft ${className}`}>Failed to load video</div>;
  }
  if (!objectUrl) {
    return <div className={`flex animate-pulse items-center justify-center bg-paper-shade text-xs text-ink-soft ${className}`}>Loading video...</div>;
  }
  return <video src={objectUrl} controls className={className} />;
}
