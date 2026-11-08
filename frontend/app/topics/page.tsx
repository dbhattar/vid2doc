import type { Metadata } from "next";

import { TopicList } from "@/components/TopicFollow";
import type { PublicTopic } from "@/lib/agency";
import PublicShell from "@/components/PublicShell";
import { fetchPublic } from "@/lib/serverApi";

// Rendered per request, never prerendered: the build (a Docker image build)
// has no API to fetch from. fetchPublic's revalidate still caches at runtime.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Topics in public meetings — Framewrite",
  description:
    "Follow a topic and get an email when a public agency meeting discusses it. Summaries and transcripts of public meetings, sorted by topic.",
};

/** Public, unauthenticated: browse the topics Framewrite tracks across public
 * agency meetings and follow the ones you care about (following needs an
 * account). Server-rendered so search engines can read it. Outside the (app)
 * group on purpose, like app/showcase. */
export default async function TopicsPage() {
  const data = await fetchPublic<{ topics: PublicTopic[] }>(
    "/api/public/topics",
  );
  const topics = data?.topics ?? [];
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
          <h1 className="mt-4 font-display text-2xl font-bold tracking-tight text-ink">
            Topics in public meetings
          </h1>
          <p className="mt-1 text-sm text-ink-soft">
            Framewrite turns recordings of public agency meetings into summaries
            and transcripts, sorted by topic. Follow a topic and we&apos;ll
            email you when a new meeting discusses it.
          </p>
          {topics.length === 0 ? (
            <p className="mt-8 text-sm text-ink-soft">
              No topics yet. Check back soon.
            </p>
          ) : (
            <TopicList topics={topics} />
          )}
        </div>
      </div>
    </PublicShell>
  );
}
