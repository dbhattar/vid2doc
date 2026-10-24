"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import Button from "@/components/Button";
import { apiFetch, ApiError } from "@/lib/api";

type Recipient = { id: string; email: string; display_name: string | null; announcements_opt_out: boolean };

type Announcement = {
  id: string;
  subject: string;
  created_at: string;
  counts: { pending: number; sending: number; sent: number; failed: number; skipped: number };
};

const POLL_INTERVAL_MS = 5000;
const TAGS = ["Update", "New feature", "Announcement"];

/** Admin-only: compose an announcement and queue it for everyone or for
 * specific users. The worker sends the emails one at a time with a delay
 * between each (see backend/app/announcements.py); the list below shows
 * progress. */
export default function AnnouncementsPage() {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [tag, setTag] = useState(TAGS[0]);
  const [ctaLabel, setCtaLabel] = useState("");
  const [ctaUrl, setCtaUrl] = useState("");
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [audience, setAudience] = useState<"all" | "selected">("all");
  const [users, setUsers] = useState<Recipient[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [history, setHistory] = useState<Announcement[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadHistory = useCallback(() => {
    apiFetch<{ announcements: Announcement[] }>("/api/admin/announcements")
      .then((data) => setHistory(data.announcements))
      .catch(() => {});
  }, []);

  useEffect(() => {
    apiFetch<{ users: Recipient[] }>("/api/admin/users")
      .then((data) => setUsers(data.users))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load users."));
    loadHistory();
  }, [loadHistory]);

  const inProgress = history.some((a) => a.counts.pending + a.counts.sending > 0);
  useEffect(() => {
    if (!inProgress) return;
    const id = setInterval(loadHistory, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [inProgress, loadHistory]);

  const subscribed = useMemo(() => users.filter((u) => !u.announcements_opt_out), [users]);
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return users.filter((u) => !q || u.email.toLowerCase().includes(q) || (u.display_name ?? "").toLowerCase().includes(q));
  }, [users, search]);

  const recipientCount = audience === "all" ? subscribed.length : selected.size;

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectVisible() {
    setSelected((prev) => {
      const next = new Set(prev);
      visible.filter((u) => !u.announcements_opt_out).forEach((u) => next.add(u.id));
      return next;
    });
  }

  const templateFields = {
    subject,
    body,
    tag,
    cta_label: ctaLabel.trim() || null,
    cta_url: ctaUrl.trim() || null,
  };

  async function preview() {
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<{ html: string }>("/api/admin/announcements/preview", {
        method: "POST",
        body: JSON.stringify(templateFields),
      });
      setPreviewHtml(result.html);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to render preview.");
    } finally {
      setBusy(false);
    }
  }

  async function send(test: boolean) {
    const who = audience === "all" ? `all ${recipientCount} subscribed users` : `${recipientCount} selected users`;
    if (!test && !confirm(`Queue this for ${who}? Emails go out one at a time, and can't be recalled once sent.`)) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await apiFetch<{ recipient_count: number }>("/api/admin/announcements", {
        method: "POST",
        body: JSON.stringify({
          ...templateFields,
          test,
          user_ids: audience === "selected" ? Array.from(selected) : null,
        }),
      });
      if (test) {
        setNotice("Test email sent to you.");
      } else {
        setNotice(`Queued for ${result.recipient_count} users. They'll be sent one at a time.`);
        setSubject("");
        setBody("");
        setSelected(new Set());
        loadHistory();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to send.");
    } finally {
      setBusy(false);
    }
  }

  const ready = subject.trim() !== "" && body.trim() !== "" && (audience === "all" || selected.size > 0);
  const inputClass =
    "w-full rounded-md border border-line bg-paper px-3 py-2 text-sm text-ink outline-none transition-shadow focus:border-accent focus:ring-2 focus:ring-accent-soft";

  return (
    <div className="w-full px-6 py-10">
      <Link href="/admin" className="text-sm text-accent hover:underline">
        &larr; Admin
      </Link>
      <h1 className="mt-2 font-display text-2xl font-bold tracking-tight text-ink">Send an announcement</h1>
      <p className="mt-1 text-sm text-ink-soft">
        Each user gets their own email, sent one at a time. Anyone who has unsubscribed is skipped.
      </p>

      <div className="mt-6 max-w-2xl space-y-4">
        <input
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          maxLength={200}
          placeholder="Subject"
          className={inputClass}
        />
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          maxLength={10000}
          rows={10}
          placeholder="Write your update. Plain text -- leave a blank line between paragraphs."
          className={inputClass}
        />

        <div className="grid gap-3 sm:grid-cols-[auto_1fr_1fr]">
          <select value={tag} onChange={(e) => setTag(e.target.value)} className={inputClass} aria-label="Email tag">
            {TAGS.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <input
            value={ctaLabel}
            onChange={(e) => setCtaLabel(e.target.value)}
            maxLength={60}
            placeholder="Button label (default: Open Framewrite)"
            className={inputClass}
          />
          <input
            value={ctaUrl}
            onChange={(e) => setCtaUrl(e.target.value)}
            maxLength={2000}
            placeholder="Button link (default: your dashboard)"
            className={inputClass}
          />
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-semibold text-ink">Send to</legend>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input type="radio" checked={audience === "all"} onChange={() => setAudience("all")} className="accent-accent" />
            All users ({subscribed.length} subscribed)
          </label>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="radio"
              checked={audience === "selected"}
              onChange={() => setAudience("selected")}
              className="accent-accent"
            />
            Specific users ({selected.size} selected)
          </label>
        </fieldset>

        {audience === "selected" && (
          <div className="rounded-lg border border-line">
            <div className="flex flex-wrap items-center gap-3 border-b border-line p-3">
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by name or email"
                className={`${inputClass} flex-1`}
              />
              <button type="button" onClick={selectVisible} className="text-sm text-accent hover:underline">
                Select shown
              </button>
              <button type="button" onClick={() => setSelected(new Set())} className="text-sm text-ink-soft hover:underline">
                Clear
              </button>
            </div>
            <ul className="max-h-72 divide-y divide-line overflow-y-auto">
              {visible.map((u) => (
                <li key={u.id}>
                  <label
                    className={`flex items-center gap-3 px-3 py-2 text-sm ${
                      u.announcements_opt_out ? "cursor-not-allowed text-ink-soft" : "cursor-pointer text-ink hover:bg-paper-shade"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(u.id)}
                      disabled={u.announcements_opt_out}
                      onChange={() => toggle(u.id)}
                      className="h-4 w-4 accent-accent"
                    />
                    <span className="truncate">
                      {u.display_name ? `${u.display_name} · ` : ""}
                      {u.email}
                    </span>
                    {u.announcements_opt_out && <span className="ml-auto text-xs">unsubscribed</span>}
                  </label>
                </li>
              ))}
              {visible.length === 0 && <li className="px-3 py-4 text-sm text-ink-soft">No users match.</li>}
            </ul>
          </div>
        )}

        <div className="flex items-center gap-3">
          <Button variant="outline" onClick={preview} disabled={busy || subject.trim() === "" || body.trim() === ""}>
            Preview
          </Button>
          <Button variant="outline" onClick={() => send(true)} disabled={busy || !ready}>
            Send test to me
          </Button>
          <Button onClick={() => send(false)} disabled={busy || !ready}>
            {busy ? "Queueing..." : `Send to ${recipientCount} ${recipientCount === 1 ? "user" : "users"}`}
          </Button>
        </div>
        {previewHtml && (
          <div>
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold text-ink">Preview (as you&apos;d receive it)</p>
              <button type="button" onClick={() => setPreviewHtml(null)} className="text-sm text-ink-soft hover:underline">
                Close
              </button>
            </div>
            {/* sandbox with no flags: the email is static markup, nothing in it should run */}
            <iframe
              title="Email preview"
              srcDoc={previewHtml}
              sandbox=""
              className="mt-2 h-[640px] w-full rounded-lg border border-line bg-white"
            />
          </div>
        )}
        {notice && <p className="text-sm text-ink">{notice}</p>}
        {error && <p className="text-sm text-status-error">{error}</p>}
      </div>

      {history.length > 0 && (
        <div className="mt-10 max-w-2xl">
          <h2 className="font-sans text-sm font-semibold text-ink-soft">Recent announcements</h2>
          <ul className="mt-2 divide-y divide-line rounded-lg border border-line">
            {history.map((a) => {
              const total = Object.values(a.counts).reduce((x, y) => x + y, 0);
              const waiting = a.counts.pending + a.counts.sending;
              return (
                <li key={a.id} className="flex items-center justify-between gap-4 px-3 py-2 text-sm">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-ink">{a.subject}</p>
                    <p className="text-xs text-ink-soft">{new Date(a.created_at).toLocaleString()}</p>
                  </div>
                  <p className="shrink-0 text-xs text-ink-soft">
                    {a.counts.sent}/{total} sent
                    {waiting > 0 && ` · ${waiting} waiting`}
                    {a.counts.failed > 0 && ` · ${a.counts.failed} failed`}
                    {a.counts.skipped > 0 && ` · ${a.counts.skipped} skipped`}
                  </p>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
