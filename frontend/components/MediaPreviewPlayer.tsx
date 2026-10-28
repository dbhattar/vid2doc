"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";

export type MediaPreviewHandle = {
  /** Seeks the player to this moment and starts playback -- called when the
   * user clicks a chat answer's citation timestamp. */
  seekTo: (seconds: number) => void;
  /** Plays just [start, end]: seeks to start, plays, and pauses at end. A
   * null end plays from start onward, like seekTo. The auto-pause is dropped
   * if the user scrubs outside the range. */
  playRange: (startSeconds: number, endSeconds: number | null) => void;
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
    const clearRangeRef = useRef<(() => void) | null>(null);
    const refreshingRef = useRef(false);

    useEffect(() => {
      setSrc(null);
      setFailed(false);
      apiFetch<{ url: string }>(`/api/jobs/${jobId}/chat/media-url`)
        .then((res) => setSrc(res.url))
        .catch(() => setFailed(true));
    }, [jobId]);

    function playFrom(el: HTMLMediaElement, seconds: number) {
      el.currentTime = seconds;
      el.play().catch(() => {
        // Autoplay can be blocked until the user interacts with the
        // player directly -- the seek itself still took effect either way.
      });
    }

    useImperativeHandle(ref, () => ({
      seekTo(seconds: number) {
        const el = mediaRef.current;
        if (!el) return;
        clearRangeRef.current?.();
        playFrom(el, seconds);
      },
      playRange(start: number, end: number | null) {
        const el = mediaRef.current;
        if (!el) return;
        clearRangeRef.current?.();
        playFrom(el, start);
        el.scrollIntoView({ block: "nearest", behavior: "smooth" });
        if (end == null) return;

        const clear = () => {
          el.removeEventListener("timeupdate", onTimeUpdate);
          el.removeEventListener("seeking", onSeeking);
          clearRangeRef.current = null;
        };
        const onTimeUpdate = () => {
          if (el.currentTime >= end) {
            el.pause();
            clear();
          }
        };
        // Our own seek to `start` also fires "seeking", landing inside the
        // range, so only a scrub outside it counts as the user leaving.
        const onSeeking = () => {
          if (el.currentTime < start - 0.5 || el.currentTime > end + 0.5) clear();
        };
        el.addEventListener("timeupdate", onTimeUpdate);
        el.addEventListener("seeking", onSeeking);
        clearRangeRef.current = clear;
      },
    }));

    // The presigned URL expires (15 min) and is only fetched once, so a long
    // session would otherwise end in a dead player. On a media error, fetch
    // a fresh URL and resume where playback was.
    function handleError() {
      const el = mediaRef.current;
      if (!el || refreshingRef.current) return;
      refreshingRef.current = true;
      const resumeAt = el.currentTime;
      const wasPlaying = !el.paused;
      apiFetch<{ url: string }>(`/api/jobs/${jobId}/chat/media-url`)
        .then((res) => {
          el.addEventListener(
            "loadedmetadata",
            () => {
              el.currentTime = resumeAt;
              if (wasPlaying) el.play().catch(() => {});
            },
            { once: true }
          );
          setSrc(res.url);
        })
        .catch(() => setFailed(true))
        .finally(() => {
          refreshingRef.current = false;
        });
    }

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
      <video ref={mediaRef} src={src} controls onError={handleError} className={className} />
    ) : (
      <audio ref={mediaRef} src={src} controls onError={handleError} className={`w-full ${className}`} />
    );
  }
);

export default MediaPreviewPlayer;
