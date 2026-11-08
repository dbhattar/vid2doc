"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Button from "@/components/Button";
import Card from "@/components/Card";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { formatDuration } from "@/lib/jobs";

type Source = {
  id: string;
  agency_name: string;
  feed_url: string;
  title_filter: string | null;
  enabled: boolean;
  last_polled_at: string | null;
};
type Topic = { id: string; slug: string; name: string; description: string; active: boolean; meeting_count: number; subscriber_count: number };
type Suggestion = { id: string; name: string; mentions: number };
type AgencyMeeting = {
  id: string;
  agency: string;
  title: string;
  status: string;
  meeting_date: string | null;
  duration_seconds: number | null;
  has_summary: boolean;
  error_message: string | null;
};

const MEETING_ACTIONS: Record<string, { action: string; label: string }[]> = {
  ready: [
    { action: "retag", label: "Re-tag" },
    { action: "hide", label: "Hide" },
  ],
  hidden: [{ action: "unhide", label: "Restore" }],
  failed: [{ action: "retry", label: "Retry" }],
};

const INPUT =
  "rounded-md border border-line bg-paper px-3 py-2 text-sm text-ink outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft";

/** Admin: public agency meetings -- sources to poll, meetings, topics and
 * suggested topics (backend/app/agency_ingest.py, routes/agency_admin.py).
 * Polling itself is switched on under Admin > Settings > Agency ingest. */
export default function AdminAgencyPage() {
  const router = useRouter();
  const [sources, setSources] = useState<Source[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [meetings, setMeetings] = useState<AgencyMeeting[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [agencyName, setAgencyName] = useState("");
  const [feedUrl, setFeedUrl] = useState("");
  const [titleFilter, setTitleFilter] = useState("");
  const [addSourceId, setAddSourceId] = useState("");
  const [addUrl, setAddUrl] = useState("");
  const [topicName, setTopicName] = useState("");
  const [topicDescription, setTopicDescription] = useState("");

  const fail = useCallback(
    (err: unknown, fallback: string) => {
      if (err instanceof ApiError && err.status === 401) {
        clearSession();
        router.replace("/login");
      } else if (err instanceof ApiError && err.status === 403) {
        router.replace("/admin");
      } else {
        setError(err instanceof ApiError ? err.message : fallback);
      }
    },
    [router],
  );

  const load = useCallback(() => {
    Promise.all([
      apiFetch<{ sources: Source[] }>("/api/admin/agency/sources"),
      apiFetch<{ topics: Topic[]; suggestions: Suggestion[] }>("/api/admin/agency/topics"),
      apiFetch<{ meetings: AgencyMeeting[] }>("/api/admin/agency/meetings"),
    ])
      .then(([s, t, m]) => {
        setSources(s.sources);
        setTopics(t.topics);
        setSuggestions(t.suggestions);
        setMeetings(m.meetings);
      })
      .catch((err) => fail(err, "Failed to load."));
  }, [fail]);

  useEffect(() => {
    load();
  }, [load]);

  async function run(key: string, call: () => Promise<unknown>, fallback: string) {
    setBusy(key);
    setError(null);
    try {
      await call();
      load();
      return true;
    } catch (err) {
      fail(err, fallback);
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function addSource(e: React.FormEvent) {
    e.preventDefault();
    const ok = await run(
      "add-source",
      () =>
        apiFetch("/api/admin/agency/sources", {
          method: "POST",
          body: JSON.stringify({ agency_name: agencyName, feed_url: feedUrl, title_filter: titleFilter || null }),
        }),
      "Couldn't add that source.",
    );
    if (ok) {
      setAgencyName("");
      setFeedUrl("");
      setTitleFilter("");
    }
  }

  async function addMeeting(e: React.FormEvent) {
    e.preventDefault();
    const ok = await run(
      "add-meeting",
      () =>
        apiFetch("/api/admin/agency/meetings", {
          method: "POST",
          body: JSON.stringify({ source_id: addSourceId || sources[0]?.id, url: addUrl }),
        }),
      "Couldn't add that recording.",
    );
    if (ok) setAddUrl("");
  }

  async function addTopic(e: React.FormEvent) {
    e.preventDefault();
    const ok = await run(
      "add-topic",
      () =>
        apiFetch("/api/admin/agency/topics", {
          method: "POST",
          body: JSON.stringify({ name: topicName, description: topicDescription }),
        }),
      "Couldn't add that topic.",
    );
    if (ok) {
      setTopicName("");
      setTopicDescription("");
    }
  }

  return (
    <div className="w-full max-w-4xl px-6 py-10">
      <Link href="/admin" className="text-sm text-accent hover:underline">
        &larr; Admin
      </Link>
      <h1 className="mt-2 font-display text-2xl font-bold tracking-tight text-ink">Public agency meetings</h1>
      <p className="mt-1 text-sm text-ink-soft">
        Recordings are polled from the sources below, processed, tagged with topics and published. Turn polling on under{" "}
        <Link href="/admin/settings" className="text-accent hover:underline">
          Settings &rarr; Agency ingest
        </Link>
        .
      </p>
      {error && <p className="mt-4 text-sm text-status-error">{error}</p>}

      <Card className="mt-8 p-6">
        <h2 className="text-sm font-semibold text-ink">Sources</h2>
        {sources.length === 0 ? (
          <p className="mt-3 text-sm text-ink-soft">No sources yet.</p>
        ) : (
          <ul className="mt-3 divide-y divide-line">
            {sources.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink">{s.agency_name}</p>
                  <p className="truncate text-xs text-ink-soft">{s.feed_url}</p>
                  <p className="text-xs text-ink-soft">
                    {s.title_filter ? `Titles matching /${s.title_filter}/ · ` : ""}
                    {s.last_polled_at ? `Last polled ${new Date(s.last_polled_at).toLocaleString()}` : "Never polled"}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    disabled={busy === s.id}
                    onClick={() =>
                      run(
                        s.id,
                        () => apiFetch(`/api/admin/agency/sources/${s.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !s.enabled }) }),
                        "Couldn't update that source.",
                      )
                    }
                  >
                    {s.enabled ? "Disable" : "Enable"}
                  </Button>
                  <Button
                    variant="outline"
                    disabled={busy === s.id}
                    onClick={() => {
                      if (!confirm(`Delete ${s.agency_name} and all of its meetings?`)) return;
                      run(s.id, () => apiFetch(`/api/admin/agency/sources/${s.id}`, { method: "DELETE" }), "Couldn't delete that source.");
                    }}
                  >
                    Delete
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={addSource} className="mt-4 flex flex-wrap items-end gap-3 border-t border-line pt-4">
          <input className={`${INPUT} w-44`} placeholder="Agency name" value={agencyName} onChange={(e) => setAgencyName(e.target.value)} required />
          <input className={`${INPUT} w-72`} placeholder="YouTube channel or playlist URL" value={feedUrl} onChange={(e) => setFeedUrl(e.target.value)} required />
          <input className={`${INPUT} w-52`} placeholder="Title filter (regex, optional)" value={titleFilter} onChange={(e) => setTitleFilter(e.target.value)} />
          <Button type="submit" disabled={busy === "add-source"}>
            Add source
          </Button>
        </form>
      </Card>

      <Card className="mt-6 p-6">
        <h2 className="text-sm font-semibold text-ink">Meetings</h2>
        <form onSubmit={addMeeting} className="mt-3 flex flex-wrap items-end gap-3">
          <select className={INPUT} value={addSourceId || sources[0]?.id || ""} onChange={(e) => setAddSourceId(e.target.value)} aria-label="Source">
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.agency_name}
              </option>
            ))}
          </select>
          <input className={`${INPUT} w-80`} placeholder="Add one recording: YouTube URL or direct video-file link" value={addUrl} onChange={(e) => setAddUrl(e.target.value)} required />
          <Button type="submit" disabled={busy === "add-meeting" || sources.length === 0}>
            Process now
          </Button>
        </form>
        {meetings.length === 0 ? (
          <p className="mt-4 text-sm text-ink-soft">No meetings yet.</p>
        ) : (
          <ul className="mt-4 divide-y divide-line">
            {meetings.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink">
                    {m.status === "ready" ? (
                      <Link href={`/agency-meetings/${m.id}`} className="hover:underline">
                        {m.title}
                      </Link>
                    ) : (
                      m.title
                    )}
                  </p>
                  <p className="text-xs text-ink-soft">
                    {m.agency} · {m.status}
                    {m.status === "ready" && !m.has_summary ? " (untagged)" : ""}
                    {m.duration_seconds ? ` · ${formatDuration(m.duration_seconds)}` : ""}
                    {m.error_message ? ` · ${m.error_message}` : ""}
                  </p>
                </div>
                <div className="flex gap-2">
                  {(MEETING_ACTIONS[m.status] ?? []).map((a) => (
                    <Button
                      key={a.action}
                      variant="outline"
                      disabled={busy === m.id}
                      onClick={() =>
                        run(m.id, () => apiFetch(`/api/admin/agency/meetings/${m.id}/${a.action}`, { method: "POST" }), `Couldn't ${a.label.toLowerCase()} that meeting.`)
                      }
                    >
                      {a.label}
                    </Button>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="mt-6 p-6">
        <h2 className="text-sm font-semibold text-ink">Topics</h2>
        <p className="text-xs text-ink-soft">Meetings are only ever tagged with these. Inactive topics are hidden and stop notifying.</p>
        {topics.length > 0 && (
          <ul className="mt-3 divide-y divide-line">
            {topics.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
                <div className="min-w-0">
                  <p className={`text-sm font-medium ${t.active ? "text-ink" : "text-ink-soft line-through"}`}>{t.name}</p>
                  <p className="text-xs text-ink-soft">
                    {t.meeting_count} meetings · {t.subscriber_count} followers{t.description ? ` · ${t.description}` : ""}
                  </p>
                </div>
                <Button
                  variant="outline"
                  disabled={busy === t.id}
                  onClick={() => run(t.id, () => apiFetch(`/api/admin/agency/topics/${t.id}`, { method: "PATCH", body: JSON.stringify({ active: !t.active }) }), "Couldn't update that topic.")}
                >
                  {t.active ? "Deactivate" : "Activate"}
                </Button>
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={addTopic} className="mt-4 flex flex-wrap items-end gap-3 border-t border-line pt-4">
          <input className={`${INPUT} w-48`} placeholder="Topic name" value={topicName} onChange={(e) => setTopicName(e.target.value)} required />
          <input className={`${INPUT} w-80`} placeholder="Short description (optional)" value={topicDescription} onChange={(e) => setTopicDescription(e.target.value)} />
          <Button type="submit" disabled={busy === "add-topic"}>
            Add topic
          </Button>
        </form>

        {suggestions.length > 0 && (
          <div className="mt-6 border-t border-line pt-4">
            <h3 className="text-sm font-semibold text-ink">Suggested by the tagger</h3>
            <p className="text-xs text-ink-soft">Seen in meetings but not on your list. Approving adds a topic; past meetings aren&apos;t re-tagged until you re-tag them.</p>
            <ul className="mt-3 divide-y divide-line">
              {suggestions.map((s) => (
                <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 py-2 first:pt-0 last:pb-0">
                  <p className="text-sm text-ink">
                    {s.name} <span className="text-xs text-ink-soft">· {s.mentions} {s.mentions === 1 ? "mention" : "mentions"}</span>
                  </p>
                  <div className="flex gap-2">
                    {(["approve", "reject"] as const).map((action) => (
                      <Button
                        key={action}
                        variant="outline"
                        disabled={busy === s.id}
                        onClick={() => run(s.id, () => apiFetch(`/api/admin/agency/suggestions/${s.id}/${action}`, { method: "POST" }), `Couldn't ${action} that suggestion.`)}
                      >
                        {action === "approve" ? "Approve" : "Reject"}
                      </Button>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>
    </div>
  );
}
