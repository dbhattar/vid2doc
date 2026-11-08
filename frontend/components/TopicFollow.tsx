"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { buttonClassName } from "@/components/Button";
import { apiFetch } from "@/lib/api";
import { getToken } from "@/lib/auth";

type FollowState = {
  signedIn: boolean;
  loaded: boolean;
  followed: Set<string>;
  busy: string | null;
  error: string | null;
  toggle: (topicId: string) => void;
};

/** The signed-in user's followed topics, loaded once. Signed-out visitors can
 * browse everything; following needs an account. */
function useFollowedTopics(): FollowState {
  const [signedIn, setSignedIn] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [followed, setFollowed] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const request = getToken()
      ? apiFetch<{ topic_ids: string[] }>("/api/me/topic-subscriptions")
      : Promise.resolve(null);
    request
      .then((r) => {
        if (!r) return;
        setSignedIn(true);
        setFollowed(new Set(r.topic_ids));
      })
      .catch(() => {
        // An expired or invalid session reads as signed out.
      })
      .finally(() => setLoaded(true));
  }, []);

  function toggle(topicId: string) {
    const next = new Set(followed);
    if (!next.delete(topicId)) next.add(topicId);
    setBusy(topicId);
    setError(null);
    apiFetch<{ topic_ids: string[] }>("/api/me/topic-subscriptions", {
      method: "PUT",
      body: JSON.stringify({ topic_ids: [...next] }),
    })
      .then((r) => setFollowed(new Set(r.topic_ids)))
      .catch(() => setError("Couldn't update your topics. Please try again."))
      .finally(() => setBusy(null));
  }

  return { signedIn, loaded, followed, busy, error, toggle };
}

function FollowButton({ topicId, state, returnTo }: { topicId: string; state: FollowState; returnTo: string }) {
  if (!state.loaded) {
    return <span className={buttonClassName("outline", "pointer-events-none opacity-50")}>Follow</span>;
  }
  if (!state.signedIn) {
    return (
      <Link href={`/login?next=${encodeURIComponent(returnTo)}`} className={buttonClassName("outline")}>
        Sign in to follow
      </Link>
    );
  }
  const following = state.followed.has(topicId);
  return (
    <button
      type="button"
      onClick={() => state.toggle(topicId)}
      disabled={state.busy === topicId}
      aria-pressed={following}
      className={buttonClassName(following ? "outline" : "primary")}
    >
      {following ? "Following" : "Follow"}
    </button>
  );
}

/** Follow button for a single topic page. */
export function FollowTopic({ topicId, returnTo }: { topicId: string; returnTo: string }) {
  const state = useFollowedTopics();
  return (
    <div>
      <FollowButton topicId={topicId} state={state} returnTo={returnTo} />
      {state.error && <p className="mt-2 text-sm text-status-error">{state.error}</p>}
    </div>
  );
}

type TopicRow = { id: string; slug: string; name: string; description: string; meeting_count: number };

/** The topic list with a follow button per row -- one subscriptions request
 * for the whole list. */
export function TopicList({ topics }: { topics: TopicRow[] }) {
  const state = useFollowedTopics();
  return (
    <>
      {state.error && <p className="mt-4 text-sm text-status-error">{state.error}</p>}
      <ul className="mt-6 divide-y divide-line rounded-lg border border-line bg-paper">
        {topics.map((t) => (
          <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div className="min-w-0">
              <Link href={`/topics/${t.slug}`} className="font-medium text-ink hover:underline">
                {t.name}
              </Link>
              {t.description && <p className="text-sm text-ink-soft">{t.description}</p>}
              <p className="text-xs text-ink-soft">
                {t.meeting_count} {t.meeting_count === 1 ? "meeting" : "meetings"}
              </p>
            </div>
            <FollowButton topicId={t.id} state={state} returnTo="/topics" />
          </li>
        ))}
      </ul>
    </>
  );
}
