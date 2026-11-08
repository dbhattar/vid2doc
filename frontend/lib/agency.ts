/** Public agency meetings -- see backend/app/topics.py and routes/agency_meetings.py. */

export type PublicTopic = {
  id: string;
  slug: string;
  name: string;
  description: string;
  meeting_count: number;
};

export type MeetingCard = {
  id: string;
  title: string;
  agency: string;
  meeting_date: string | null;
  duration_seconds: number | null;
  summary: string | null;
  // Only on a topic's meeting list: what was said about that topic, and where.
  topic_summary?: string;
  start_ts?: number | null;
};

export type MeetingTopic = {
  slug: string;
  name: string;
  summary: string;
  start_ts: number | null;
  end_ts: number | null;
};

export type TranscriptSegment = { speaker: string | null; text: string; start_ts: number | null };

export type PublicMeeting = MeetingCard & {
  source_url: string;
  topics: MeetingTopic[];
  segments: TranscriptSegment[];
};

export type TranscriptTurn = { speaker: string; start_ts: number; text: string };

/** 4521 -> "1:15:21", 75 -> "1:15". */
export function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

/** The official recording, opened at `seconds` (YouTube's &t= parameter). */
export function recordingLinkAt(sourceUrl: string, seconds: number | null): string {
  if (seconds == null) return sourceUrl;
  let host = "";
  try {
    host = new URL(sourceUrl).hostname;
  } catch {
    return sourceUrl;
  }
  if (/(^|\.)(youtube\.com|youtu\.be)$/.test(host)) {
    return `${sourceUrl}${sourceUrl.includes("?") ? "&" : "?"}t=${Math.floor(seconds)}s`;
  }
  // A direct file link: a query parameter could invalidate a signed URL, but a
  // media fragment is never sent to the server and browsers' players honour it.
  return `${sourceUrl.split("#")[0]}#t=${Math.floor(seconds)}`;
}

/** Consecutive segments by the same speaker, joined into one turn, so a
 * multi-hour transcript isn't thousands of tiny paragraphs. */
export function groupTurns(segments: TranscriptSegment[]): TranscriptTurn[] {
  const turns: TranscriptTurn[] = [];
  for (const s of segments) {
    const speaker = s.speaker || "Speaker";
    const last = turns[turns.length - 1];
    if (last && last.speaker === speaker) {
      last.text += ` ${s.text}`;
    } else {
      turns.push({ speaker, start_ts: s.start_ts ?? 0, text: s.text });
    }
  }
  return turns;
}

export function formatMeetingDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });
}
