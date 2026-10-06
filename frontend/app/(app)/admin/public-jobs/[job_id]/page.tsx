"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { buttonClassName } from "@/components/Button";
import Card from "@/components/Card";
import DocumentPreview from "@/components/DocumentPreview";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { formatCents } from "@/lib/billing";
import { formatDuration } from "@/lib/jobs";

type AdminPublicJobDetail = {
  id: string;
  user_id: string | null;
  email: string | null;
  display_name: string | null;
  title: string | null;
  duration_seconds: number | null;
  billed_cents: number;
  public_status: "pending" | "approved" | "rejected";
  public_refund_cents: number | null;
  public_consented_at: string | null;
  document_url?: string;
  video_url?: string;
};

export default function AdminPublicJobDetailPage() {
  const router = useRouter();
  const params = useParams<{ job_id: string }>();
  const [submission, setSubmission] = useState<AdminPublicJobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function handleError(err: unknown) {
    if (err instanceof ApiError && err.status === 401) {
      clearSession();
      router.replace("/login");
      return;
    }
    if (err instanceof ApiError && (err.status === 403 || err.status === 404)) {
      router.replace("/admin/public-jobs");
      return;
    }
    setError(err instanceof ApiError ? err.message : "Failed to load submission.");
  }

  useEffect(() => {
    apiFetch<AdminPublicJobDetail>(`/api/admin/public-jobs/${params.job_id}`).then(setSubmission).catch(handleError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.job_id]);

  async function handleApprove() {
    if (!submission) return;
    if (
      !confirm(
        `Approve and refund ${formatCents(submission.public_refund_cents ?? 0)} to ${submission.email}? This makes the document public immediately and cannot be undone.`
      )
    )
      return;
    setBusy(true);
    try {
      await apiFetch(`/api/admin/public-jobs/${submission.id}/approve`, { method: "POST" });
      router.push("/admin/public-jobs");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to approve.");
      setBusy(false);
    }
  }

  async function handleReject() {
    if (!submission) return;
    if (!confirm(`Reject this submission? ${submission.email} keeps their existing balance -- no refund is issued.`)) return;
    setBusy(true);
    try {
      await apiFetch(`/api/admin/public-jobs/${submission.id}/reject`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      router.push("/admin/public-jobs");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to reject.");
      setBusy(false);
    }
  }

  if (error) return <p className="w-full px-6 py-10 text-sm text-status-error">{error}</p>;
  if (!submission) return <p className="w-full px-6 py-10 text-sm text-ink-soft">Loading...</p>;

  return (
    <div className="w-full px-6 py-10">
      <Link href="/admin/public-jobs" className="text-sm text-ink-soft hover:underline">
        &larr; Back to public showcase queue
      </Link>

      <h1 className="mt-2 font-display text-2xl font-bold tracking-tight text-ink">
        {submission.title || "Untitled"}
      </h1>
      <p className="mt-1 text-sm text-ink-soft">
        Submitted by{" "}
        {submission.user_id ? (
          <Link href={`/admin/users/${submission.user_id}`} className="text-accent hover:underline">
            {submission.display_name || submission.email}
          </Link>
        ) : (
          "—"
        )}
      </p>

      <div className="mt-6 grid grid-cols-3 gap-3">
        <Card className="p-4">
          <p className="font-sans text-xs font-medium text-ink-soft">Duration</p>
          <p className="mt-2 font-display text-2xl font-bold text-ink">{formatDuration(submission.duration_seconds)}</p>
        </Card>
        <Card className="p-4">
          <p className="font-sans text-xs font-medium text-ink-soft">Billed</p>
          <p className="mt-2 font-display text-2xl font-bold text-ink">{formatCents(submission.billed_cents)}</p>
        </Card>
        <Card className="p-4">
          <p className="font-sans text-xs font-medium text-ink-soft">Refund if approved</p>
          <p className="mt-2 font-display text-2xl font-bold text-ink">{formatCents(submission.public_refund_cents ?? 0)}</p>
        </Card>
      </div>

      {submission.public_status === "pending" && (
        <div className="mt-6 flex items-center gap-3">
          <button onClick={handleApprove} disabled={busy} className={buttonClassName("primary")}>
            {busy ? "Working..." : "Approve"}
          </button>
          <button
            onClick={handleReject}
            disabled={busy}
            className="text-sm text-status-error hover:underline disabled:cursor-default disabled:opacity-50"
          >
            Reject
          </button>
        </div>
      )}
      {submission.public_status !== "pending" && (
        <p className="mt-6 text-sm text-ink-soft">
          Already <strong className="text-ink">{submission.public_status}</strong>.
        </p>
      )}

      {error && <p className="mt-3 text-sm text-status-error">{error}</p>}

      {submission.video_url && (
        <Card className="mt-6 overflow-hidden p-0">
          {/* Plain <video src>, not AuthenticatedVideo -- this points at the
              public S3 archive (same as document_url below), so it needs no
              Bearer token and streams directly. */}
          <video controls className="w-full" src={submission.video_url} />
        </Card>
      )}

      {submission.document_url ? (
        <Card className="mt-6 p-6">
          <DocumentPreview markdownUrl={submission.document_url} bordered={false} external />
        </Card>
      ) : (
        <p className="mt-6 text-sm text-ink-soft">No document available to preview.</p>
      )}
    </div>
  );
}
