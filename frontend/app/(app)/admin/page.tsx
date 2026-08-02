"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Card from "@/components/Card";
import { GlobeIcon, MicrophoneIcon, ShieldIcon, UsersIcon, VideoCameraIcon, WalletIcon } from "@/components/icons";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { formatCents } from "@/lib/billing";
import { formatBytes, formatDuration } from "@/lib/jobs";

type AdminStats = {
  user_count: number;
  total_revenue_cents: number;
  total_spent_cents: number;
  job_counts: { video: number; audio: number; total: number };
  total_source_size_bytes: number;
  trial_job_count: number;
  top_spenders: { id: string; email: string; display_name: string | null; spent_cents: number }[];
};

type AdminTrialJob = {
  id: string;
  job_type: "video" | "audio";
  status: string;
  duration_seconds: number | null;
  source_size_bytes: number | null;
  client_ip: string | null;
  error_message: string | null;
  created_at: string;
};

const TRIAL_STATUS_COLORS: Record<string, string> = {
  queued: "text-status-info",
  processing: "text-status-warning",
  awaiting_review: "text-status-info",
  done: "text-status-success",
  failed: "text-status-error",
};

type AdminUser = {
  id: string;
  email: string;
  display_name: string | null;
  is_admin: boolean;
  created_at: string;
  spent_cents: number;
  job_count: number;
};

type AdminFeedback = {
  id: string;
  user_id: string;
  email: string;
  display_name: string | null;
  message: string;
  created_at: string;
};

function StatCard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-ink-soft">
        {icon}
        <span className="font-mono text-xs font-medium uppercase tracking-wide">{label}</span>
      </div>
      <p className="mt-2 font-display text-2xl font-bold text-ink">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-ink-soft">{sub}</p>}
    </Card>
  );
}

export default function AdminPage() {
  const router = useRouter();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [feedback, setFeedback] = useState<AdminFeedback[] | null>(null);
  const [trialJobs, setTrialJobs] = useState<AdminTrialJob[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  function load() {
    apiFetch<AdminStats>("/api/admin/stats")
      .then(setStats)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/dashboard");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Failed to load admin stats.");
      });
    apiFetch<{ users: AdminUser[] }>("/api/admin/users")
      .then((data) => setUsers(data.users))
      .catch(() => {
        // Non-critical for the stats cards above to render.
      });
    apiFetch<{ feedback: AdminFeedback[] }>("/api/admin/feedback")
      .then((data) => setFeedback(data.feedback))
      .catch(() => {
        // Non-critical for the rest of the page to render.
      });
    apiFetch<{ jobs: AdminTrialJob[] }>("/api/admin/trial-jobs")
      .then((data) => setTrialJobs(data.jobs))
      .catch(() => {
        // Non-critical for the rest of the page to render.
      });
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleToggleAdmin(user: AdminUser) {
    const next = !user.is_admin;
    if (!confirm(next ? `Make ${user.email} an admin?` : `Revoke admin access for ${user.email}?`)) return;
    setTogglingId(user.id);
    try {
      await apiFetch(`/api/admin/users/${user.id}/admin`, {
        method: "POST",
        body: JSON.stringify({ is_admin: next }),
      });
      setUsers((prev) => prev?.map((u) => (u.id === user.id ? { ...u, is_admin: next } : u)) ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update admin status.");
    } finally {
      setTogglingId(null);
    }
  }

  return (
    <div className="w-full px-6 py-10">
      <h1 className="font-display text-2xl font-bold tracking-tight text-ink">Admin</h1>
      <p className="mt-1 text-sm text-ink-soft">Platform-wide usage and revenue.</p>

      {error && <p className="mt-4 text-sm text-status-error">{error}</p>}

      {!stats && !error && <p className="mt-6 text-sm text-ink-soft">Loading...</p>}

      {stats && (
        <>
          <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard icon={<UsersIcon className="h-4 w-4" />} label="Users" value={stats.user_count.toLocaleString()} />
            <StatCard
              icon={<WalletIcon className="h-4 w-4" />}
              label="Revenue"
              value={formatCents(stats.total_revenue_cents)}
              sub="total top-ups"
            />
            <StatCard
              icon={<WalletIcon className="h-4 w-4" />}
              label="Spent"
              value={formatCents(stats.total_spent_cents)}
              sub="on processing"
            />
            <StatCard
              icon={<VideoCameraIcon className="h-4 w-4" />}
              label="Jobs processed"
              value={stats.job_counts.total.toLocaleString()}
              sub={`${formatBytes(stats.total_source_size_bytes)} total`}
            />
          </div>

          <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3">
            <Card className="flex items-center gap-2 p-4">
              <VideoCameraIcon className="h-4 w-4 text-accent" />
              <span className="text-sm text-ink-soft">Video</span>
              <span className="ml-auto text-sm font-semibold text-ink">{stats.job_counts.video.toLocaleString()}</span>
            </Card>
            <Card className="flex items-center gap-2 p-4">
              <MicrophoneIcon className="h-4 w-4 text-ink-soft" />
              <span className="text-sm text-ink-soft">Audio</span>
              <span className="ml-auto text-sm font-semibold text-ink">{stats.job_counts.audio.toLocaleString()}</span>
            </Card>
            <Card className="flex items-center gap-2 p-4">
              <GlobeIcon className="h-4 w-4 text-ink-soft" />
              <span className="text-sm text-ink-soft">Anonymous trials</span>
              <span className="ml-auto text-sm font-semibold text-ink">{stats.trial_job_count.toLocaleString()}</span>
            </Card>
          </div>

          <h2 className="mt-8 font-mono text-sm font-semibold uppercase tracking-wide text-ink-soft">Top 5 spenders</h2>
          {stats.top_spenders.length === 0 ? (
            <p className="mt-2 text-sm text-ink-soft">No spending yet.</p>
          ) : (
            <ul className="mt-2 divide-y divide-line border-2 border-line bg-paper">
              {stats.top_spenders.map((u, i) => (
                <li key={u.id} className="flex items-center justify-between px-4 py-3">
                  <div className="flex items-center gap-3">
                    <span className="font-display w-4 text-sm font-bold text-accent">{i + 1}</span>
                    <div>
                      <p className="text-sm font-medium text-ink">{u.display_name || u.email}</p>
                      <p className="text-xs text-ink-soft">{u.email}</p>
                    </div>
                  </div>
                  <span className="text-sm font-semibold text-ink">{formatCents(u.spent_cents)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <h2 className="mt-8 font-mono text-sm font-semibold uppercase tracking-wide text-ink-soft">All users</h2>
      {users === null ? (
        <p className="mt-2 text-sm text-ink-soft">Loading...</p>
      ) : (
        <div className="mt-2 overflow-x-auto border-2 border-line bg-paper">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line font-mono text-xs uppercase tracking-wide text-ink-soft">
                <th className="px-4 py-3 font-medium">User</th>
                <th className="px-4 py-3 font-medium">Joined</th>
                <th className="px-4 py-3 font-medium">Jobs</th>
                <th className="px-4 py-3 font-medium">Spent</th>
                <th className="px-4 py-3 font-medium">Admin</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="px-4 py-3">
                    <p className="font-medium text-ink">{u.display_name || u.email}</p>
                    <p className="text-xs text-ink-soft">{u.email}</p>
                  </td>
                  <td className="px-4 py-3 text-ink-soft">{new Date(u.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-3 text-ink-soft">{u.job_count}</td>
                  <td className="px-4 py-3 text-ink-soft">{formatCents(u.spent_cents)}</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => handleToggleAdmin(u)}
                      disabled={togglingId === u.id}
                      className={`flex items-center gap-1.5 border-2 px-2.5 py-1 text-xs font-medium transition-colors disabled:cursor-default disabled:opacity-50 ${
                        u.is_admin
                          ? "border-accent bg-accent-soft text-accent hover:bg-accent/20"
                          : "border-line text-ink-soft hover:bg-paper-shade hover:text-ink"
                      }`}
                    >
                      <ShieldIcon className="h-3.5 w-3.5" />
                      {u.is_admin ? "Admin" : "Make admin"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 className="mt-8 font-mono text-sm font-semibold uppercase tracking-wide text-ink-soft">
        Anonymous trial jobs
      </h2>
      {trialJobs === null ? (
        <p className="mt-2 text-sm text-ink-soft">Loading...</p>
      ) : trialJobs.length === 0 ? (
        <p className="mt-2 text-sm text-ink-soft">No trial jobs yet.</p>
      ) : (
        <div className="mt-2 overflow-x-auto border-2 border-line bg-paper">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line font-mono text-xs uppercase tracking-wide text-ink-soft">
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Duration</th>
                <th className="px-4 py-3 font-medium">Size</th>
                <th className="px-4 py-3 font-medium">IP</th>
                <th className="px-4 py-3 font-medium">Submitted</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {trialJobs.map((j) => (
                <tr key={j.id}>
                  <td className="px-4 py-3">
                    <span className={`font-mono text-xs font-semibold uppercase tracking-wide ${TRIAL_STATUS_COLORS[j.status] ?? "text-ink-soft"}`}>
                      {j.status.replaceAll("_", " ")}
                    </span>
                    {j.status === "failed" && j.error_message && (
                      <p className="mt-0.5 max-w-xs truncate text-xs text-status-error" title={j.error_message}>
                        {j.error_message}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3 capitalize text-ink-soft">{j.job_type}</td>
                  <td className="px-4 py-3 text-ink-soft">{formatDuration(j.duration_seconds)}</td>
                  <td className="px-4 py-3 text-ink-soft">{j.source_size_bytes ? formatBytes(j.source_size_bytes) : "—"}</td>
                  <td className="px-4 py-3 font-mono text-xs text-ink-soft">{j.client_ip || "—"}</td>
                  <td className="px-4 py-3 text-ink-soft">{new Date(j.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 className="mt-8 font-mono text-sm font-semibold uppercase tracking-wide text-ink-soft">Recent feedback</h2>
      {feedback === null ? (
        <p className="mt-2 text-sm text-ink-soft">Loading...</p>
      ) : feedback.length === 0 ? (
        <p className="mt-2 text-sm text-ink-soft">No feedback yet.</p>
      ) : (
        <ul className="mt-2 divide-y divide-line border-2 border-line bg-paper">
          {feedback.map((f) => (
            <li key={f.id} className="px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-ink">{f.display_name || f.email}</p>
                <p className="shrink-0 text-xs text-ink-soft">{new Date(f.created_at).toLocaleString()}</p>
              </div>
              <p className="mt-1 whitespace-pre-wrap text-sm text-ink-soft">{f.message}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
