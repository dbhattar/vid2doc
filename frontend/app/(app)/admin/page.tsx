"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { MicrophoneIcon, ShieldIcon, UsersIcon, VideoCameraIcon, WalletIcon } from "@/components/icons";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { formatCents } from "@/lib/billing";
import { formatBytes } from "@/lib/jobs";

type AdminStats = {
  user_count: number;
  total_revenue_cents: number;
  total_spent_cents: number;
  job_counts: { video: number; audio: number; total: number };
  total_source_size_bytes: number;
  top_spenders: { id: string; email: string; display_name: string | null; spent_cents: number }[];
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

function StatCard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-2xl border border-brand-border bg-surface p-4 shadow-soft">
      <div className="flex items-center gap-2 text-muted">
        {icon}
        <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
      </div>
      <p className="mt-2 text-2xl font-bold text-brand-navy">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
    </div>
  );
}

export default function AdminPage() {
  const router = useRouter();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
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
    <div className="mx-auto w-full max-w-4xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-brand-navy">Admin</h1>
      <p className="mt-1 text-sm text-muted">Platform-wide usage and revenue.</p>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {!stats && !error && <p className="mt-6 text-sm text-muted">Loading...</p>}

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

          <div className="mt-3 grid grid-cols-2 gap-3">
            <div className="flex items-center gap-2 rounded-2xl border border-brand-border bg-surface p-4 shadow-soft">
              <VideoCameraIcon className="h-4 w-4 text-brand-amber-dark" />
              <span className="text-sm text-muted">Video</span>
              <span className="ml-auto text-sm font-semibold text-foreground">{stats.job_counts.video.toLocaleString()}</span>
            </div>
            <div className="flex items-center gap-2 rounded-2xl border border-brand-border bg-surface p-4 shadow-soft">
              <MicrophoneIcon className="h-4 w-4 text-brand-navy" />
              <span className="text-sm text-muted">Audio</span>
              <span className="ml-auto text-sm font-semibold text-foreground">{stats.job_counts.audio.toLocaleString()}</span>
            </div>
          </div>

          <h2 className="mt-8 text-sm font-semibold uppercase tracking-wide text-muted">Top 5 spenders</h2>
          {stats.top_spenders.length === 0 ? (
            <p className="mt-2 text-sm text-muted">No spending yet.</p>
          ) : (
            <ul className="mt-2 divide-y divide-brand-border overflow-hidden rounded-2xl border border-brand-border bg-surface shadow-soft">
              {stats.top_spenders.map((u, i) => (
                <li key={u.id} className="flex items-center justify-between px-4 py-3">
                  <div className="flex items-center gap-3">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-amber-soft text-xs font-semibold text-brand-amber-dark">
                      {i + 1}
                    </span>
                    <div>
                      <p className="text-sm font-medium text-foreground">{u.display_name || u.email}</p>
                      <p className="text-xs text-muted">{u.email}</p>
                    </div>
                  </div>
                  <span className="text-sm font-semibold text-foreground">{formatCents(u.spent_cents)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <h2 className="mt-8 text-sm font-semibold uppercase tracking-wide text-muted">All users</h2>
      {users === null ? (
        <p className="mt-2 text-sm text-muted">Loading...</p>
      ) : (
        <div className="mt-2 overflow-x-auto rounded-2xl border border-brand-border bg-surface shadow-soft">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-brand-border text-xs uppercase tracking-wide text-muted">
                <th className="px-4 py-3 font-medium">User</th>
                <th className="px-4 py-3 font-medium">Joined</th>
                <th className="px-4 py-3 font-medium">Jobs</th>
                <th className="px-4 py-3 font-medium">Spent</th>
                <th className="px-4 py-3 font-medium">Admin</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-border">
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="px-4 py-3">
                    <p className="font-medium text-foreground">{u.display_name || u.email}</p>
                    <p className="text-xs text-muted">{u.email}</p>
                  </td>
                  <td className="px-4 py-3 text-muted">{new Date(u.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-3 text-muted">{u.job_count}</td>
                  <td className="px-4 py-3 text-muted">{formatCents(u.spent_cents)}</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => handleToggleAdmin(u)}
                      disabled={togglingId === u.id}
                      className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors disabled:cursor-default disabled:opacity-50 ${
                        u.is_admin
                          ? "border-brand-amber/50 bg-brand-amber-soft text-brand-amber-dark hover:bg-brand-amber/20"
                          : "border-brand-border text-muted hover:bg-brand-navy-soft hover:text-brand-navy"
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
    </div>
  );
}
