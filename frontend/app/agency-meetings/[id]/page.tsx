import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import Card from "@/components/Card";
import ScrollToTime from "@/components/ScrollToTime";
import { formatDuration } from "@/lib/jobs";
import {
  formatMeetingDate,
  formatTimestamp,
  groupTurns,
  recordingLinkAt,
  type PublicMeeting,
  type TranscriptTurn,
} from "@/lib/agency";
import PublicShell from "@/components/PublicShell";
import { fetchPublic } from "@/lib/serverApi";

// Rendered per request, never prerendered: the build (a Docker image build)
// has no API to fetch from. fetchPublic's revalidate still caches at runtime.
export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

const load = (id: string) =>
  fetchPublic<PublicMeeting>(
    `/api/public/agency-meetings/${encodeURIComponent(id)}`,
  );

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const meeting = await load(id);
  if (!meeting) return { title: "Meeting not found — Framewrite" };
  return {
    title: `${meeting.title} — ${meeting.agency} — Framewrite`,
    description:
      meeting.summary?.slice(0, 200) ||
      `Summary and transcript of a public ${meeting.agency} meeting.`,
  };
}

/** The turn a topic's discussion starts in, for an in-page jump link. */
function anchorFor(
  turns: TranscriptTurn[],
  start: number | null,
): string | null {
  if (start == null) return null;
  let found: TranscriptTurn | null = null;
  for (const t of turns) {
    if (t.start_ts <= start) found = t;
    else break;
  }
  return found ? `#t-${Math.floor(found.start_ts)}` : null;
}

/** Public: one agency meeting -- AI summary, the topics it covered with where
 * they came up, a link to the official recording, and the transcript. */
export default async function AgencyMeetingPage({ params }: Props) {
  const { id } = await params;
  const meeting = await load(id);
  if (!meeting) notFound();
  const turns = groupTurns(meeting.segments);

  return (
    <PublicShell>
      <div className="min-h-screen bg-paper">
        <ScrollToTime />
        <div className="mx-auto max-w-2xl px-6 py-10">
          <a
            href="https://framewrite.cc"
            className="font-display text-lg font-bold text-ink"
          >
            Framewrite
          </a>
          <p className="mt-4 text-sm text-ink-soft">
            {meeting.agency}
            {meeting.meeting_date
              ? ` · ${formatMeetingDate(meeting.meeting_date)}`
              : ""}
            {meeting.duration_seconds
              ? ` · ${formatDuration(meeting.duration_seconds)}`
              : ""}
          </p>
          <h1 className="mt-1 font-display text-2xl font-bold tracking-tight text-ink">
            {meeting.title}
          </h1>
          <p className="mt-2 text-sm">
            <a
              href={meeting.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent hover:underline"
            >
              Watch the official recording
            </a>
          </p>

          <p className="mt-4 rounded-md bg-paper-shade px-3 py-2 text-xs text-ink-soft">
            The summary, topics and transcript were produced by AI from the
            public recording and can contain mistakes. The official recording is
            the record. To report a problem or ask for something to be removed,
            email{" "}
            <a href="mailto:contact@framewrite.cc" className="underline">
              contact@framewrite.cc
            </a>
            .
          </p>

          {meeting.summary && (
            <Card className="mt-6 p-6">
              <h2 className="text-sm font-semibold text-ink">Summary</h2>
              <p className="mt-2 whitespace-pre-line text-sm text-ink">
                {meeting.summary}
              </p>
            </Card>
          )}

          {meeting.topics.length > 0 && (
            <Card className="mt-6 p-6">
              <h2 className="text-sm font-semibold text-ink">
                Topics discussed
              </h2>
              <ul className="mt-3 divide-y divide-line">
                {meeting.topics.map((t) => {
                  const anchor = anchorFor(turns, t.start_ts);
                  return (
                    <li key={t.slug} className="py-3 first:pt-0 last:pb-0">
                      <Link
                        href={`/topics/${t.slug}`}
                        className="text-sm font-medium text-ink hover:underline"
                      >
                        {t.name}
                      </Link>
                      {t.summary && (
                        <p className="mt-1 text-sm text-ink">{t.summary}</p>
                      )}
                      {t.start_ts != null && (
                        <p className="mt-1 text-xs text-ink-soft">
                          {anchor && (
                            <a
                              href={anchor}
                              className="text-accent hover:underline"
                            >
                              Read from {formatTimestamp(t.start_ts)}
                            </a>
                          )}
                          {anchor && " · "}
                          <a
                            href={recordingLinkAt(
                              meeting.source_url,
                              t.start_ts,
                            )}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-accent hover:underline"
                          >
                            Watch from {formatTimestamp(t.start_ts)}
                          </a>
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}

          {turns.length > 0 && (
            <Card className="mt-6 p-6">
              <h2 className="text-sm font-semibold text-ink">Transcript</h2>
              <div className="mt-3 flex flex-col gap-3">
                {turns.map((turn, i) => (
                  <div
                    key={`${i}-${turn.start_ts}`}
                    id={`t-${Math.floor(turn.start_ts)}`}
                    data-turn-start={turn.start_ts}
                    className="scroll-mt-24 rounded-md px-2 py-1"
                  >
                    <p className="text-xs font-semibold text-ink-soft">
                      {turn.speaker} · {formatTimestamp(turn.start_ts)}
                    </p>
                    <p className="text-sm text-ink">{turn.text}</p>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </PublicShell>
  );
}
