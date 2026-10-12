"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { buttonClassName } from "@/components/Button";
import Pagination from "@/components/Pagination";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { formatCents } from "@/lib/billing";
import { formatDuration } from "@/lib/jobs";

const PAGE_SIZE = 20;

type PublicStatusFilter = "pending" | "approved" | "rejected";

const STATUS_TABS: { value: PublicStatusFilter; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
];

type AdminPublicJobSubmission = {
  id: string;
  user_id: string | null;
  email: string | null;
  display_name: string | null;
  title: string | null;
  duration_seconds: number | null;
  billed_cents: number;
  public_refund_cents: number | null;
  public_consented_at: string | null;
  // Only meaningful once public_status === "approved" -- see
  // backend/app/models.py's Job.public_hidden.
  public_hidden: boolean;
};

export default function AdminPublicJobsPage() {
  const router = useRouter();
  const [statusFilter, setStatusFilter] = useState<PublicStatusFilter>("pending");
  const [submissions, setSubmissions] = useState<AdminPublicJobSubmission[] | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  function load() {
    const offset = (page - 1) * PAGE_SIZE;
    apiFetch<{ jobs: AdminPublicJobSubmission[]; total: number }>(
      `/api/admin/public-jobs?status=${statusFilter}&limit=${PAGE_SIZE}&offset=${offset}`
    )
      .then((data) => {
        setSubmissions(data.jobs);
        setTotal(data.total);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearSession();
          router.replace("/login");
          return;
        }
        if (err instanceof ApiError && err.status === 403) {
          router.replace("/admin");
          return;
        }
        setError(err instanceof ApiError ? err.message : "Failed to load submissions.");
      });
  }

  // Switching tabs re-fetches from page 1 -- a page number valid for one
  // status's pagination is likely out of range for another's.
  useEffect(() => {
    setPage(1);
  }, [statusFilter]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, statusFilter]);

  async function handleApprove(item: AdminPublicJobSubmission) {
    if (
      !confirm(
        `Approve and refund ${formatCents(item.public_refund_cents ?? 0)} to ${item.email}? This makes the document public immediately and cannot be undone.`
      )
    )
      return;
    setBusyId(item.id);
    try {
      await apiFetch(`/api/admin/public-jobs/${item.id}/approve`, { method: "POST" });
      setSubmissions((prev) => prev?.filter((s) => s.id !== item.id) ?? null);
      setTotal((prev) => prev - 1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to approve.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleReject(item: AdminPublicJobSubmission) {
    if (!confirm(`Reject this submission? ${item.email} keeps their existing balance -- no refund is issued.`)) return;
    setBusyId(item.id);
    try {
      await apiFetch(`/api/admin/public-jobs/${item.id}/reject`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setSubmissions((prev) => prev?.filter((s) => s.id !== item.id) ?? null);
      setTotal((prev) => prev - 1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to reject.");
    } finally {
      setBusyId(null);
    }
  }

  // Unlike approve/reject above, this never removes the row -- it stays in
  // the Approved tab either way, just with its own hidden state flipped (see
  // backend/app/models.py's Job.public_hidden for why this is a reversible
  // display toggle, not a moderation decision).
  async function handleToggleHidden(item: AdminPublicJobSubmission) {
    setBusyId(item.id);
    try {
      const action = item.public_hidden ? "unhide" : "hide";
      await apiFetch(`/api/admin/public-jobs/${item.id}/${action}`, { method: "POST" });
      setSubmissions(
        (prev) => prev?.map((s) => (s.id === item.id ? { ...s, public_hidden: !item.public_hidden } : s)) ?? null
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update visibility.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="w-full px-6 py-10">
      <Link href="/admin" className="text-sm text-ink-soft hover:underline">
        &larr; Back to Admin
      </Link>

      <h1 className="mt-2 font-display text-2xl font-bold tracking-tight text-ink">Public showcase queue</h1>
      <p className="mt-1 text-sm text-ink-soft">
        Users who opted a completed video job into the public showcase for a partial refund. Approving makes the
        document public immediately and permanently. Once approved, an item can still be hidden from the homepage
        carousel without un-approving it.
      </p>

      <div className="mt-4 flex gap-1 border-b border-line">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setStatusFilter(tab.value)}
            className={`px-3 py-2 text-sm font-medium transition-colors ${
              statusFilter === tab.value
                ? "border-b-2 border-accent text-ink"
                : "text-ink-soft hover:text-ink"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {error && <p className="mt-4 text-sm text-status-error">{error}</p>}

      {submissions === null ? (
        <p className="mt-6 text-sm text-ink-soft">Loading...</p>
      ) : submissions.length === 0 ? (
        <p className="mt-6 text-sm text-ink-soft">
          {statusFilter === "pending" ? "Nothing pending review." : `No ${statusFilter} submissions.`}
        </p>
      ) : (
        <>
          <div className="mt-6 overflow-x-auto rounded-lg border border-line bg-paper shadow-sm">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-line font-sans text-xs text-ink-soft">
                  <th className="px-4 py-3 font-semibold">User</th>
                  <th className="px-4 py-3 font-semibold">Title</th>
                  <th className="px-4 py-3 font-semibold">Duration</th>
                  <th className="px-4 py-3 font-semibold">Billed / Refund</th>
                  <th className="px-4 py-3 font-semibold">Submitted</th>
                  <th className="px-4 py-3 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {submissions.map((item) => (
                  <tr key={item.id}>
                    <td className="whitespace-nowrap px-4 py-3">
                      {item.user_id ? (
                        <Link href={`/admin/users/${item.user_id}`} className="font-medium text-ink hover:underline">
                          {item.display_name || item.email}
                        </Link>
                      ) : (
                        <span className="text-ink-soft">—</span>
                      )}
                    </td>
                    <td className="max-w-xs px-4 py-3">
                      <p className="truncate text-ink" title={item.title ?? undefined}>
                        {item.title || "Untitled"}
                      </p>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-ink-soft">{formatDuration(item.duration_seconds)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-ink-soft">
                      {formatCents(item.billed_cents)}
                      <p className="mt-0.5 text-xs">{formatCents(item.public_refund_cents ?? 0)} refund</p>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-ink-soft">
                      {item.public_consented_at ? new Date(item.public_consented_at).toLocaleString() : "—"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Link href={`/admin/public-jobs/${item.id}`} className={buttonClassName("outline", "px-2.5 py-1 text-xs")}>
                          Preview
                        </Link>
                        {statusFilter === "pending" && (
                          <>
                            <button
                              onClick={() => handleApprove(item)}
                              disabled={busyId === item.id}
                              className={buttonClassName("primary", "px-2.5 py-1 text-xs disabled:cursor-default")}
                            >
                              Approve
                            </button>
                            <button
                              onClick={() => handleReject(item)}
                              disabled={busyId === item.id}
                              className="text-xs text-status-error hover:underline disabled:cursor-default disabled:opacity-50"
                            >
                              Reject
                            </button>
                          </>
                        )}
                        {statusFilter === "approved" && (
                          <button
                            onClick={() => handleToggleHidden(item)}
                            disabled={busyId === item.id}
                            className={buttonClassName(
                              item.public_hidden ? "primary" : "outline",
                              "px-2.5 py-1 text-xs disabled:cursor-default"
                            )}
                          >
                            {item.public_hidden ? "Show on homepage" : "Hide from homepage"}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </>
      )}
    </div>
  );
}
