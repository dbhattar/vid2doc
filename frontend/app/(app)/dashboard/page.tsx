"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Card from "@/components/Card";
import DocumentCard from "@/components/DocumentCard";
import { ClapperboardIcon, MicrophoneIcon, VideoCameraIcon, WalletIcon } from "@/components/icons";
import JobRow from "@/components/JobRow";
import Pagination from "@/components/Pagination";
import { apiFetch, ApiError } from "@/lib/api";
import { clearSession } from "@/lib/auth";
import { formatCents } from "@/lib/billing";
import { displayTitle, isActiveJob, type Job } from "@/lib/jobs";

const POLL_INTERVAL_MS = 4000;
const DOCUMENTS_PAGE_SIZE = 12;

// The holistic "everything at a glance" view -- balance, documents by type,
// what's currently in progress across both. Uploading itself now lives on
// the Video/Audio pages (see ./video, ./audio), which is where that flow can
// keep evolving independently without cluttering this overview.
export default function DashboardPage() {
  const router = useRouter();
  const [balanceCents, setBalanceCents] = useState<number | null>(null);
  const [spentCents, setSpentCents] = useState<number | null>(null);
  const [walletError, setWalletError] = useState<string | null>(null);

  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [cancellingJobId, setCancellingJobId] = useState<string | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const [videoCount, setVideoCount] = useState<number | null>(null);
  const [audioCount, setAudioCount] = useState<number | null>(null);
  const [videoGenCount, setVideoGenCount] = useState<number | null>(null);

  const [documentsPage, setDocumentsPage] = useState(1);
  const [documents, setDocuments] = useState<Job[] | null>(null);
  const [documentsTotal, setDocumentsTotal] = useState(0);
  const [documentsError, setDocumentsError] = useState<string | null>(null);

  const handleAuthError = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) {
        clearSession();
        router.replace("/login");
        return true;
      }
      return false;
    },
    [router],
  );

  const loadWallet = useCallback(() => {
    apiFetch<{ balance_cents: number; spent_cents: number }>("/api/billing/wallet")
      .then((data) => {
        setBalanceCents(data.balance_cents);
        setSpentCents(data.spent_cents);
      })
      .catch((err) => {
        if (handleAuthError(err)) return;
        setWalletError(err instanceof ApiError ? err.message : "Failed to load wallet.");
      });
  }, [handleAuthError]);

  const loadJobs = useCallback(() => {
    apiFetch<{ jobs: Job[]; total: number }>("/api/jobs?limit=50")
      .then((data) => setJobs(data.jobs))
      .catch((err) => {
        if (handleAuthError(err)) return;
        setLoadError(err instanceof ApiError ? err.message : "Failed to load jobs.");
      });
  }, [handleAuthError]);

  const loadStats = useCallback(() => {
    Promise.all([
      apiFetch<{ total: number }>("/api/jobs?status=done&job_type=video&limit=1"),
      apiFetch<{ total: number }>("/api/jobs?status=done&job_type=audio&limit=1"),
      apiFetch<{ total: number }>("/api/jobs?status=done&job_type=video_gen&limit=1"),
    ])
      .then(([video, audio, videoGen]) => {
        setVideoCount(video.total);
        setAudioCount(audio.total);
        setVideoGenCount(videoGen.total);
      })
      .catch((err) => {
        handleAuthError(err);
      });
  }, [handleAuthError]);

  const loadDocuments = useCallback(
    (page: number) => {
      const offset = (page - 1) * DOCUMENTS_PAGE_SIZE;
      apiFetch<{ jobs: Job[]; total: number }>(`/api/jobs?status=done&limit=${DOCUMENTS_PAGE_SIZE}&offset=${offset}`)
        .then((data) => {
          setDocuments(data.jobs);
          setDocumentsTotal(data.total);
        })
        .catch((err) => {
          if (handleAuthError(err)) return;
          setDocumentsError(err instanceof ApiError ? err.message : "Failed to load documents.");
        });
    },
    [handleAuthError],
  );

  useEffect(() => {
    loadWallet();
    loadJobs();
    loadStats();
    loadDocuments(1);
  }, [loadWallet, loadJobs, loadStats, loadDocuments]);

  useEffect(() => {
    loadDocuments(documentsPage);
  }, [documentsPage, loadDocuments]);

  // Poll while at least one job is still queued/processing; also refreshes
  // the balance/stats/document grid so a job finishing mid-session shows up
  // without a manual reload.
  useEffect(() => {
    if (!jobs || !jobs.some(isActiveJob)) return;
    const id = setInterval(() => {
      loadWallet();
      loadJobs();
      loadStats();
      loadDocuments(documentsPage);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [jobs, loadWallet, loadJobs, loadStats, loadDocuments, documentsPage]);

  async function handleRetry(jobId: string) {
    setRetryingJobId(jobId);
    setRetryError(null);
    try {
      await apiFetch(`/api/jobs/${jobId}/retry`, { method: "POST" });
      loadJobs();
    } catch (err) {
      if (handleAuthError(err)) return;
      setRetryError(err instanceof ApiError ? err.message : "Retry failed.");
    } finally {
      setRetryingJobId(null);
    }
  }

  async function handleDelete(job: Job) {
    if (!confirm(`Delete "${displayTitle(job)}"? This can't be undone.`)) return;
    setDeletingJobId(job.job_id);
    setDeleteError(null);
    try {
      await apiFetch(`/api/jobs/${job.job_id}`, { method: "DELETE" });
      loadJobs();
    } catch (err) {
      if (handleAuthError(err)) return;
      setDeleteError(err instanceof ApiError ? err.message : "Delete failed.");
    } finally {
      setDeletingJobId(null);
    }
  }

  async function handleCancel(job: Job) {
    if (!confirm(`Cancel "${displayTitle(job)}"? Any charge for it will be refunded.`)) return;
    setCancellingJobId(job.job_id);
    setCancelError(null);
    try {
      await apiFetch(`/api/jobs/${job.job_id}/cancel`, { method: "POST" });
      loadJobs();
    } catch (err) {
      if (handleAuthError(err)) return;
      setCancelError(err instanceof ApiError ? err.message : "Cancel failed.");
    } finally {
      setCancellingJobId(null);
    }
  }

  const videoInProgress = jobs?.filter((j) => j.status !== "done" && j.job_type === "video") ?? null;
  const audioInProgress = jobs?.filter((j) => j.status !== "done" && j.job_type === "audio") ?? null;
  const videoGenInProgress = jobs?.filter((j) => j.status !== "done" && j.job_type === "video_gen") ?? null;
  const totalProcessed = (videoCount ?? 0) + (audioCount ?? 0) + (videoGenCount ?? 0);

  return (
    <div className="w-full px-6 py-10">
      <h1 className="font-display text-2xl font-bold tracking-tight text-ink">Dashboard</h1>
      <p className="mt-1 text-sm text-ink-soft">Everything happening across your videos and audio, at a glance.</p>

      <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="p-5 lg:col-span-1">
          <div className="flex items-center gap-2 text-ink-soft">
            <WalletIcon className="h-4 w-4" />
            <span className="font-mono text-xs font-medium uppercase tracking-wide">Wallet balance</span>
          </div>
          <p className="mt-2 font-display text-3xl font-bold tracking-tight text-ink">
            {balanceCents === null ? "—" : formatCents(balanceCents)}
          </p>
          <div className="mt-3 flex items-center justify-between text-xs text-ink-soft">
            <span>{spentCents === null ? "—" : `${formatCents(spentCents)} spent on processing`}</span>
            <Link href="/settings/billing" className="text-accent hover:underline">
              Add funds →
            </Link>
          </div>
          {walletError && <p className="mt-2 text-xs text-status-error">{walletError}</p>}
        </Card>

        <Card className="flex items-center gap-4 p-5">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center bg-accent-soft text-accent">
            <VideoCameraIcon className="h-5 w-5" />
          </span>
          <div>
            <p className="font-display text-2xl font-bold tracking-tight text-ink">{videoCount ?? "—"}</p>
            <p className="text-sm text-ink-soft">Video documents</p>
          </div>
        </Card>
        <Card className="flex items-center gap-4 p-5">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center bg-paper-shade text-ink-soft">
            <MicrophoneIcon className="h-5 w-5" />
          </span>
          <div>
            <p className="font-display text-2xl font-bold tracking-tight text-ink">{audioCount ?? "—"}</p>
            <p className="text-sm text-ink-soft">Audio transcripts</p>
          </div>
        </Card>
        <Card className="flex items-center gap-4 p-5">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center bg-paper-shade text-ink-soft">
            <ClapperboardIcon className="h-5 w-5" />
          </span>
          <div>
            <p className="font-display text-2xl font-bold tracking-tight text-ink">{videoGenCount ?? "—"}</p>
            <p className="text-sm text-ink-soft">Generated videos</p>
          </div>
        </Card>
      </div>

      {totalProcessed > 0 && (
        <p className="mt-3 text-xs text-ink-soft">{totalProcessed.toLocaleString()} document{totalProcessed === 1 ? "" : "s"} processed in total.</p>
      )}

      {((videoInProgress && videoInProgress.length > 0) ||
        (audioInProgress && audioInProgress.length > 0) ||
        (videoGenInProgress && videoGenInProgress.length > 0)) && (
        <div className="mt-10">
          <h2 className="text-sm font-semibold text-ink">In progress</h2>
          {loadError && <p className="mt-2 text-sm text-status-error">{loadError}</p>}
          {retryError && <p className="mt-2 text-sm text-status-error">{retryError}</p>}
          {deleteError && <p className="mt-2 text-sm text-status-error">{deleteError}</p>}
          {cancelError && <p className="mt-2 text-sm text-status-error">{cancelError}</p>}

          {videoInProgress && videoInProgress.length > 0 && (
            <div className="mt-3">
              <div className="flex items-center gap-2 font-mono text-xs font-medium uppercase tracking-wide text-ink-soft">
                <VideoCameraIcon className="h-3.5 w-3.5" /> Video
              </div>
              <ul className="mt-2 divide-y divide-line border-2 border-line bg-paper">
                {videoInProgress.map((job) => (
                  <JobRow
                    key={job.job_id}
                    job={job}
                    onRetry={handleRetry}
                    onDelete={handleDelete}
                    onCancel={handleCancel}
                    retryingJobId={retryingJobId}
                    deletingJobId={deletingJobId}
                    cancellingJobId={cancellingJobId}
                  />
                ))}
              </ul>
            </div>
          )}

          {audioInProgress && audioInProgress.length > 0 && (
            <div className="mt-6">
              <div className="flex items-center gap-2 font-mono text-xs font-medium uppercase tracking-wide text-ink-soft">
                <MicrophoneIcon className="h-3.5 w-3.5" /> Audio
              </div>
              <ul className="mt-2 divide-y divide-line border-2 border-line bg-paper">
                {audioInProgress.map((job) => (
                  <JobRow
                    key={job.job_id}
                    job={job}
                    onRetry={handleRetry}
                    onDelete={handleDelete}
                    onCancel={handleCancel}
                    retryingJobId={retryingJobId}
                    deletingJobId={deletingJobId}
                    cancellingJobId={cancellingJobId}
                  />
                ))}
              </ul>
            </div>
          )}

          {videoGenInProgress && videoGenInProgress.length > 0 && (
            <div className="mt-6">
              <div className="flex items-center gap-2 font-mono text-xs font-medium uppercase tracking-wide text-ink-soft">
                <ClapperboardIcon className="h-3.5 w-3.5" /> Video Gen
              </div>
              <ul className="mt-2 divide-y divide-line border-2 border-line bg-paper">
                {videoGenInProgress.map((job) => (
                  <JobRow
                    key={job.job_id}
                    job={job}
                    onRetry={handleRetry}
                    onDelete={handleDelete}
                    onCancel={handleCancel}
                    retryingJobId={retryingJobId}
                    deletingJobId={deletingJobId}
                    cancellingJobId={cancellingJobId}
                  />
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div className="mt-10">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink">Documents</h2>
          <Link href="/documents" className="text-sm text-ink-soft hover:text-accent hover:underline">
            View all →
          </Link>
        </div>
        {documentsError && <p className="mt-2 text-sm text-status-error">{documentsError}</p>}
        {documents === null ? (
          <p className="mt-3 text-sm text-ink-soft">Loading...</p>
        ) : documents.length === 0 ? (
          <p className="mt-3 border-2 border-dashed border-line p-6 text-center text-sm text-ink-soft">
            No documents yet -- upload a{" "}
            <Link href="/dashboard/video" className="underline hover:text-accent">
              video
            </Link>{" "}
            or{" "}
            <Link href="/dashboard/audio" className="underline hover:text-accent">
              audio
            </Link>{" "}
            file to get started.
          </p>
        ) : (
          <>
            <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {documents.map((job) => (
                <DocumentCard key={job.job_id} job={job} />
              ))}
            </div>
            <Pagination page={documentsPage} pageSize={DOCUMENTS_PAGE_SIZE} total={documentsTotal} onPageChange={setDocumentsPage} />
          </>
        )}
      </div>
    </div>
  );
}
