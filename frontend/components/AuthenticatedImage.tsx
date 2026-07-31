"use client";

import { useEffect, useState } from "react";

import { getToken } from "@/lib/auth";

/** Frame thumbnails are served behind Bearer-token auth (no cookie session
 * in this app), so a plain `<img src>` can't authenticate -- fetch as a
 * blob instead, same technique as `downloadAuthenticated`, and render it
 * through a throwaway object URL. */
export default function AuthenticatedImage({ src, alt, className = "" }: { src: string; alt: string; className?: string }) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let url: string | null = null;
    setObjectUrl(null);
    setFailed(false);

    const token = getToken();
    fetch(src, { headers: token ? { Authorization: `Bearer ${token}` } : undefined })
      .then((res) => {
        if (!res.ok) throw new Error(res.statusText);
        return res.blob();
      })
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
    return <div className={`flex items-center justify-center bg-paper-shade text-xs text-ink-soft ${className}`}>Failed to load</div>;
  }
  if (!objectUrl) {
    return <div className={`animate-pulse bg-paper-shade ${className}`} />;
  }
  return <img src={objectUrl} alt={alt} className={className} />;
}
