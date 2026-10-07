"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";

export type MediaPreviewHandle = {
  /** Seeks the player to this moment and starts playback -- called when the
   * user clicks a chat answer's citation timestamp. */
  seekTo: (seconds: number) => void;
};

/** Plays the archived source media for a chat-enabled job (see
 * GET /api/jobs/{id}/chat/media-url) via a short-lived presigned S3 URL --
 * unlike AuthenticatedVideo, no blob-fetch-with-Bearer-token technique is
 * needed here: the presigned URL carries its own signed auth, and S3
 * natively supports Range requests against it, so scrubbing/seeking works
 * with no extra code. */
const MediaPreviewPlayer = forwardRef<MediaPreviewHandle, { jobId: string; kind: "video" | "audio"; className?: string }>(
  function MediaPreviewPlayer({ jobId, kind, className = "" }, ref) {
    const mediaRef = useRef<HTMLVideoElement & HTMLAudioElement>(null);
    const [src, setSrc] = useState<string | null>(null);
    const [failed, setFailed] = useState(false);

    useEffect(() => {
      setSrc(null);
      setFailed(false);
      apiFetch<{ url: string }>(`/api/jobs/${jobId}/chat/media-url`)
        .then((res) => setSrc(res.url))
        .catch(() => setFailed(true));
    }, [jobId]);

    useImperativeHandle(ref, () => ({
      seekTo(seconds: number) {
        const el = mediaRef.current;
        if (!el) return;
        el.currentTime = seconds;
        el.play().catch(() => {
          // Autoplay can be blocked until the user interacts with the
          // player directly -- the seek itself still took effect either way.
        });
      },
    }));

    if (failed) {
      return (
        <div className={`flex items-center justify-center bg-paper-shade text-xs text-ink-soft ${className}`}>
          Failed to load media
        </div>
      );
    }
    if (!src) {
      return (
        <div className={`flex animate-pulse items-center justify-center bg-paper-shade text-xs text-ink-soft ${className}`}>
          Loading media...
        </div>
      );
    }
    return kind === "video" ? (
      <video ref={mediaRef} src={src} controls className={className} />
    ) : (
      <audio ref={mediaRef} src={src} controls className={`w-full ${className}`} />
    );
  }
);

export default MediaPreviewPlayer;
