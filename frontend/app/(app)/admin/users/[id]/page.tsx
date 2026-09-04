"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import AdminActivityFeed, { type AdminActivityEvent } from "@/components/AdminActivityFeed";
import Card from "@/components/Card";
import { ShieldIcon } from "@/components/icons";
import Pagination from "@/components/Pagination";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { formatCents } from "@/lib/billing";

const PAGE_SIZE = 20;

type AdminUserDetail = {
  id: string;
  email: string;
  display_name: string | null;
  is_admin: boolean;
  created_at: string;
  spent_cents: number;
  job_count: number;
};

export default function AdminUserDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [user, setUser] = useState<AdminUserDetail | null>(null);
  const [activity, setActivity] = useState<AdminActivityEvent[] | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);

  function handleError(err: unknown) {
    if (err instanceof ApiError && err.status === 401) {
      clearSession();
      router.replace("/login");
      return;
    }
    if (err instanceof ApiError && (err.status === 403 || err.status === 404)) {
      router.replace("/admin");
      return;
    }
    setError(err instanceof ApiError ? err.message : "Failed to load user.");
  }

  useEffect(() => {
    apiFetch<AdminUserDetail>(`/api/admin/users/${params.id}`).then(setUser).catch(handleError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  useEffect(() => {
    const offset = (page - 1) * PAGE_SIZE;
    apiFetch<{ activity: AdminActivityEvent[]; total: number }>(
      `/api/admin/users/${params.id}/activity?limit=${PAGE_SIZE}&offset=${offset}`
    )
      .then((data) => {
        setActivity(data.activity);
        setTotal(data.total);
      })
      .catch(handleError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id, page]);

  return (
    <div className="w-full px-6 py-10">
      <Link href="/admin" className="text-sm text-ink-soft hover:underline">
        &larr; Back to Admin
      </Link>

      {error && <p className="mt-4 text-sm text-status-error">{error}</p>}

      {!user && !error && <p className="mt-6 text-sm text-ink-soft">Loading...</p>}

      {user && (
        <>
          <div className="mt-2 flex items-center gap-2">
            <h1 className="font-display text-2xl font-bold tracking-tight text-ink">
              {user.display_name || user.email}
            </h1>
            {user.is_admin && (
              <span className="flex items-center gap-1 rounded-full border border-accent bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent">
                <ShieldIcon className="h-3 w-3" /> Admin
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-ink-soft">{user.email}</p>

          <div className="mt-6 grid grid-cols-3 gap-3">
            <Card className="p-4">
              <p className="text-xs font-medium text-ink-soft">Joined</p>
              <p className="mt-2 font-display text-lg font-bold text-ink">
                {new Date(user.created_at).toLocaleDateString()}
              </p>
            </Card>
            <Card className="p-4">
              <p className="text-xs font-medium text-ink-soft">Jobs</p>
              <p className="mt-2 font-display text-lg font-bold text-ink">{user.job_count}</p>
            </Card>
            <Card className="p-4">
              <p className="text-xs font-medium text-ink-soft">Spent</p>
              <p className="mt-2 font-display text-lg font-bold text-ink">{formatCents(user.spent_cents)}</p>
            </Card>
          </div>

          <h2 className="mt-8 font-sans text-sm font-semibold text-ink-soft">Activity</h2>
          {activity === null ? (
            <p className="mt-2 text-sm text-ink-soft">Loading...</p>
          ) : (
            <>
              <AdminActivityFeed events={activity} showUser={false} />
              <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
            </>
          )}
        </>
      )}
    </div>
  );
}
