import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import Card from "@/components/Card";
import { FollowTopic } from "@/components/TopicFollow";
import { formatDuration } from "@/lib/jobs";
import {
  formatMeetingDate,
  formatTimestamp,
  type MeetingCard,
} from "@/lib/agency";
import PublicShell from "@/components/PublicShell";
import { fetchPublic } from "@/lib/serverApi";

// Rendered per request, never prerendered: the build (a Docker image build)
// has no API to fetch from. fetchPublic's revalidate still caches at runtime.
export const dynamic = "force-dynamic";

type Props = { params: Promise<{ slug: string }> };
type Topic = { id: string; slug: string; name: string; description: string };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const topic = await fetchPublic<Topic>(
    `/api/public/topics/${encodeURIComponent(slug)}`,
  );
  if (!topic) return { title: "Topic not found — Framewrite" };
  return {
    title: `${topic.name} in public meetings — Framewrite`,
    description:
      topic.description ||
      `Public agency meetings that discussed ${topic.name}.`,
  };
}

/** Public: the meetings that covered one topic, newest first. */
export default async function TopicPage({ params }: Props) {
  const { slug } = await params;
  const topic = await fetchPublic<Topic>(
    `/api/public/topics/${encodeURIComponent(slug)}`,
  );
  if (!topic) notFound();
  const data = await fetchPublic<{ meetings: MeetingCard[] }>(
    `/api/public/topics/${encodeURIComponent(slug)}/meetings`,
  );
  const meetings = data?.meetings ?? [];

  return (
    <PublicShell>
      <div className="min-h-screen bg-paper">
        <div className="mx-auto max-w-2xl px-6 py-10">
          <a
            href="https://framewrite.cc"
            className="font-display text-lg font-bold text-ink"
          >
            Framewrite
          </a>
          <p className="mt-4 text-sm">
            <Link href="/topics" className="text-accent hover:underline">
              All topics
            </Link>
          </p>
          <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <h1 className="font-display text-2xl font-bold tracking-tight text-ink">
                {topic.name}
              </h1>
              {topic.description && (
                <p className="mt-1 text-sm text-ink-soft">
                  {topic.description}
                </p>
              )}
            </div>
            <FollowTopic
              topicId={topic.id}
              returnTo={`/topics/${topic.slug}`}
            />
          </div>

          {meetings.length === 0 ? (
            <p className="mt-8 text-sm text-ink-soft">
              No meetings have covered this topic yet.
            </p>
          ) : (
            <ul className="mt-6 flex flex-col gap-4">
              {meetings.map((m) => (
                <li key={m.id}>
                  <Card className="p-5">
                    <p className="text-xs text-ink-soft">
                      {m.agency}
                      {m.meeting_date
                        ? ` · ${formatMeetingDate(m.meeting_date)}`
                        : ""}
                      {m.duration_seconds
                        ? ` · ${formatDuration(m.duration_seconds)}`
                        : ""}
                    </p>
                    <Link
                      href={`/agency-meetings/${m.id}${m.start_ts ? `?t=${Math.floor(m.start_ts)}` : ""}`}
                      className="mt-1 block font-medium text-ink hover:underline"
                    >
                      {m.title}
                    </Link>
                    {m.topic_summary && (
                      <p className="mt-2 text-sm text-ink">{m.topic_summary}</p>
                    )}
                    {m.start_ts != null && (
                      <p className="mt-1 text-xs text-ink-soft">
                        Discussed from {formatTimestamp(m.start_ts)}
                      </p>
                    )}
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </PublicShell>
  );
}
