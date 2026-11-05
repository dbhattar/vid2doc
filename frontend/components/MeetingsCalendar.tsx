"use client";

import { useMemo } from "react";

import { dayKey, meetingDate, type Meeting } from "@/lib/meetings";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MAX_CHIPS = 3;

const DOT_COLORS: Record<Meeting["status"], string> = {
  scheduled: "bg-accent",
  joining: "bg-status-info",
  recording: "bg-status-error",
  processing: "bg-status-info",
  done: "bg-status-success",
  failed: "bg-status-error",
  cancelled: "bg-ink-soft",
  awaiting_payment: "bg-accent",
};

/** Month grid that fills the Meetings view. Clicking a day calls `onOpenDay`,
 * which opens that day's panel (its meetings plus the form to add one). */
export default function MeetingsCalendar({
  month,
  onMonthChange,
  meetings,
  selectedDay,
  onOpenDay,
}: {
  month: Date; // any date within the month shown
  onMonthChange: (month: Date) => void;
  meetings: Meeting[];
  selectedDay: string | null;
  onOpenDay: (key: string) => void;
}) {
  const todayKey = dayKey(new Date());

  const byDay = useMemo(() => {
    const map = new Map<string, Meeting[]>();
    for (const m of meetings) {
      const key = dayKey(meetingDate(m));
      map.set(key, [...(map.get(key) ?? []), m]);
    }
    for (const list of map.values()) {
      list.sort((a, b) => meetingDate(a).getTime() - meetingDate(b).getTime());
    }
    return map;
  }, [meetings]);

  // Whole weeks, Sunday first, padded with the neighbouring months' days.
  const cells = useMemo(() => {
    const first = new Date(month.getFullYear(), month.getMonth(), 1);
    const start = new Date(first);
    start.setDate(1 - first.getDay());
    const daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    const count = Math.ceil((first.getDay() + daysInMonth) / 7) * 7;
    return Array.from({ length: count }, (_, i) => {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      return d;
    });
  }, [month]);

  const shift = (delta: number) => onMonthChange(new Date(month.getFullYear(), month.getMonth() + delta, 1));
  const weeks = cells.length / 7;

  return (
    <div className="flex flex-1 flex-col">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-xl font-bold text-ink">
          {month.toLocaleDateString(undefined, { month: "long", year: "numeric" })}
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => shift(-1)}
            aria-label="Previous month"
            className="rounded-md border border-line px-2.5 py-1 text-sm text-ink hover:bg-paper-shade"
          >
            ←
          </button>
          <button
            onClick={() => onMonthChange(new Date())}
            className="rounded-md border border-line px-2.5 py-1 text-sm text-ink hover:bg-paper-shade"
          >
            Today
          </button>
          <button
            onClick={() => shift(1)}
            aria-label="Next month"
            className="rounded-md border border-line px-2.5 py-1 text-sm text-ink hover:bg-paper-shade"
          >
            →
          </button>
        </div>
      </div>

      <div className="mt-3 flex flex-1 flex-col overflow-hidden rounded-lg border border-line bg-paper shadow-sm">
        <div className="grid grid-cols-7 border-b border-line bg-paper-shade text-center text-xs font-semibold text-ink-soft">
          {WEEKDAYS.map((w) => (
            <div key={w} className="py-2">
              {w}
            </div>
          ))}
        </div>
        <div
          className="grid flex-1 grid-cols-7"
          style={{ gridTemplateRows: `repeat(${weeks}, minmax(6.5rem, 1fr))` }}
        >
          {cells.map((d, i) => {
            const key = dayKey(d);
            const inMonth = d.getMonth() === month.getMonth();
            const dayMeetings = byDay.get(key) ?? [];
            const selected = key === selectedDay;
            return (
              <button
                key={key}
                type="button"
                onClick={() => onOpenDay(key)}
                aria-label={`${d.toLocaleDateString(undefined, { month: "long", day: "numeric" })}, ${dayMeetings.length} meeting${dayMeetings.length === 1 ? "" : "s"}`}
                aria-pressed={selected}
                className={`flex min-w-0 flex-col items-start gap-1 border-line p-2 text-left transition-colors hover:bg-paper-shade ${
                  i % 7 !== 6 ? "border-r" : ""
                } ${i < cells.length - 7 ? "border-b" : ""} ${selected ? "bg-accent-soft" : ""} ${inMonth ? "" : "opacity-50"}`}
              >
                <span
                  className={`flex h-6 w-6 items-center justify-center rounded-full text-xs ${
                    key === todayKey ? "bg-accent font-semibold text-accent-ink" : "text-ink"
                  }`}
                >
                  {d.getDate()}
                </span>
                {dayMeetings.slice(0, MAX_CHIPS).map((m) => (
                  <span key={m.id} className="flex w-full min-w-0 items-center gap-1.5 text-xs leading-tight text-ink">
                    <span className={`h-2 w-2 shrink-0 rounded-full ${DOT_COLORS[m.status]}`} />
                    <span className="truncate">
                      {meetingDate(m).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}{" "}
                      {m.title ?? "Meeting"}
                    </span>
                  </span>
                ))}
                {dayMeetings.length > MAX_CHIPS && (
                  <span className="text-xs text-ink-soft">+{dayMeetings.length - MAX_CHIPS} more</span>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
